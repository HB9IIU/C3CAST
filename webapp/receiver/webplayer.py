"""QO-100 WebPlayer: live DATV video above, the BATC spectrum below, click a signal to tune (standard library only).

Receivers: RTL-SDR (software demodulator), MiniTiouner and PicoTuner (through the bundled tuner service).
The page lists what is plugged in and the user chooses; the choice is remembered in settings.json.
"""
import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import socket
import subprocess
import sys
from types import SimpleNamespace
import threading
import webbrowser
from urllib.parse import parse_qs, urlparse

import usb_devices
from rx_status import ReceiverStatus
from ts_info import TsInfo
from tuners import QocastBackend, ReplayBackend, RtlSdrBackend

ROOT = Path(__file__).resolve().parent


def ffmpeg_command(executable):
    """FFmpeg: the received transport stream in, H.264 / AAC fragmented MP4 for the browser out."""
    return [str(executable), '-hide_banner', '-loglevel', 'info', '-fflags', '+genpts+discardcorrupt',
            '-probesize', '1000000', '-analyzeduration', '1000000', '-f', 'mpegts', '-i', 'pipe:0',
            '-map', '0:v:0', '-map', '0:a:0?', '-vf', 'scale=1280:720:force_original_aspect_ratio=decrease:force_divisible_by=2,fps=25',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency', '-profile:v', 'baseline',
            '-level:v', '3.1', '-pix_fmt', 'yuv420p', '-crf', '23', '-g', '25', '-keyint_min', '25', '-sc_threshold', '0',
            '-c:a', 'aac', '-b:a', '96k', '-ar', '48000', '-ac', '2', '-avoid_negative_ts', 'make_zero',
            '-movflags', '+empty_moov+default_base_moof+frag_keyframe', '-frag_duration', '200000',
            '-flush_packets', '1', '-f', 'mp4', 'pipe:1']
SETTINGS = ROOT / 'settings.json'
STATIC = {'/': ('web/webplayer.html', 'text/html; charset=utf-8'),
          '/embed': ('web/embed.html', 'text/html; charset=utf-8'),
          '/spectrum.js': ('web/spectrum.js', 'text/javascript'),
          '/signal-finder.js': ('web/signal-finder.js', 'text/javascript'),
          '/constellation.js': ('web/constellation.js', 'text/javascript'),
          '/mse-init.js': ('web/mse-init.js', 'text/javascript'),
          '/magic-eye.js': ('web/magic-eye.js', 'text/javascript')}
LABELS = {'rtlsdr': 'RTL-SDR', 'minitiouner': 'MiniTiouner', 'picotuner': 'PicoTuner', 'replay': 'Recorded stream (test)'}
LNB_POWER = ('off', 'vertical', 'horizontal')       # the voltage the receiver puts on the coax: none, 13 V, 18 V
RF_INPUTS = ('A', 'B')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765, help='Local server port; 0 selects a free port')
    parser.add_argument('--lnb-lo', type=float, default=9750.0, help='LNB oscillator in MHz (default: 9750)')
    parser.add_argument('--lnb-correction', type=float, default=0.0, help='LNB error in MHz, added to the IF (e.g. 0.05 if the LNB runs 50 kHz high)')
    parser.add_argument('--gain', type=float, help='RTL-SDR RF gain in dB (default: the last choice on the page, else 40.2)')
    parser.add_argument('--tuner', choices=('rtlsdr', 'minitiouner', 'picotuner'), help='Use this receiver whatever is detected (testing)')
    parser.add_argument('--label', help='What the page says this receiver is (QOCAST assigns it), e.g. "MiniTiouner DA582LER"')
    parser.add_argument('--ffmpeg', type=Path, required=True, help="QOCAST's FFmpeg")
    parser.add_argument('--service-exe', type=Path, default=ROOT / 'tuner-service/bin/tuner-service.exe', help='The bundled tuner service, for MiniTiouner / PicoTuner')
    parser.add_argument('--service-port', type=int, default=8090, help="The tuner service's local control port")
    parser.add_argument('--ts-port', type=int, default=5001, help="Loopback UDP port where the tuner service sends the stream")
    parser.add_argument('--ts-port2', type=int, default=5002, help='Loopback UDP port for the second PicoTuner channel')
    parser.add_argument('--primary-port', type=int, help='First web receiver, which owns the shared PicoTuner service')
    parser.add_argument('--lnb-power', choices=LNB_POWER, help='LNB voltage from the MiniTiouner / PicoTuner (default: the last choice on the page, else off)')
    parser.add_argument('--rf-input', choices=RF_INPUTS, help='MiniTiouner / PicoTuner RF input (default: the last choice on the page, else A)')
    parser.add_argument('--logs', type=Path, default=ROOT / 'logs', help='Where the logs and the tuner service config go (a second copy needs its own)')
    parser.add_argument('--settings', type=Path, default=SETTINGS, help='Where the chosen receiver is remembered')
    parser.add_argument('--no-browser', action='store_true', help='Do not open the browser automatically')
    parser.add_argument('--channel', type=int, choices=(1, 2), default=1, help="2: the PicoTuner's second tuner, through the first player's tuner service (--service-port)")
    parser.add_argument('--no-autotune', action='store_true', help='Do not tune the QO-100 beacon by itself when the page opens')
    parser.add_argument('--watch-stdin', action='store_true', help='Shut down when the owning C3CAST process closes its pipe')
    parser.add_argument('--input-ts', type=Path, help='Development only: replay a recorded TS; clicks then do not retune')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535 or (args.gain is not None and not 0 <= args.gain <= 50):
        parser.error('Expected port 0–65535 and gain 0–50 dB.')
    if args.input_ts and not args.input_ts.is_file():
        parser.error('--input-ts file not found.')
    bin_dir = ROOT / 'bin'
    if not args.ffmpeg.is_file():
        parser.error('Missing ' + str(args.ffmpeg))
    env = os.environ.copy()
    env['PATH'] = str(bin_dir) + os.pathsep + env.get('PATH', '')
    return serve(args, bin_dir, env)


def relay(source, sink, info):
    """Pass the transport stream on to the encoder, reading its station and stream tables on the way."""
    reading = True
    try:
        while True:
            block = source.read1(65536)
            if not block:
                break
            if reading:
                try:
                    info.feed_stream(block)
                except Exception as error:      # never let the display of names stop the video
                    reading = False
                    print('Stream information stopped:', error, flush=True)
            sink.write(block)
            sink.flush()
    except (OSError, ValueError):
        pass                                    # the encoder or the receiver ended: the session is closing
    finally:
        try:
            sink.close()
        except OSError:
            pass


def load_settings(path):
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def serve(args, bin_dir, env):
    logs = args.logs
    logs.mkdir(parents=True, exist_ok=True)
    viewer = threading.Lock()      # one stream at a time: a receiver has one owner
    guard = threading.Lock()
    active = []
    stopping = threading.Event()
    status = ReceiverStatus()
    stream_info = [TsInfo()]          # station and stream names of the running session
    session_id = [0]                  # counts the sessions, so a page can tell a new session's status from the old one's
    settings = load_settings(args.settings)

    def save_settings():
        try:
            args.settings.write_text(json.dumps(settings, indent=2), encoding='utf-8')
        except OSError as error:
            print('Could not save settings.json:', error, flush=True)

    # LNB voltage and RF input of a MiniTiouner / PicoTuner: an option given now wins, else the last choice, else off / A
    saved_power, saved_input = settings.get('lnb_power'), settings.get('rf_input')
    lnb_power = args.lnb_power or (saved_power if saved_power in LNB_POWER else 'off')
    rf_input = args.rf_input or (saved_input if saved_input in RF_INPUTS else 'A')
    saved_gain = settings.get('gain')
    gain = args.gain if args.gain is not None else (saved_gain if isinstance(saved_gain, (int, float)) and 0 <= saved_gain <= 50 else 40.2)
    backends = {'rtlsdr': RtlSdrBackend(bin_dir, args.lnb_lo, args.lnb_correction, gain)}
    for kind in ('minitiouner', 'picotuner'):
        backends[kind] = QocastBackend(kind, args.service_exe, args.service_port, args.ts_port, args.lnb_lo,
                                       args.lnb_correction, lnb_power, rf_input, logs, args.channel, args.ts_port2, args.primary_port)
    if args.input_ts:
        backends['replay'] = ReplayBackend(args.input_ts, args.ffmpeg)

    def devices():
        """What can be chosen now, and which one is chosen: (list, id or None)."""
        if args.input_ts:
            entries = [{'id': 'replay', 'label': LABELS['replay'], 'count': 1}]
        elif args.tuner:                  # assigned by QOCAST: this one, nothing else to choose
            entries = [{'id': args.tuner, 'label': args.label or LABELS[args.tuner], 'count': 1}]
        else:
            entries = [{'id': d['id'], 'count': d['count'],
                        'label': d['label']}
                       for d in usb_devices.detect()]
        ids = [entry['id'] for entry in entries]
        choice = args.tuner or ('replay' if args.input_ts else settings.get('tuner'))
        if args.tuner and choice not in ids:
            entries.append({'id': choice, 'label': LABELS[choice], 'count': 1})
            ids.append(choice)
        if choice not in ids:
            choice = ids[0] if len(ids) == 1 else None      # a single receiver needs no choosing
        return entries, choice

    client = [None]                   # the browser connection of the running stream, to cut it on stop

    def cleanup(processes):
        # Only rtl_iq is stopped by closing its input (that makes it release the USB stick). Any other input
        # pipe may be in the middle of a write by the relay thread: closing it here could block, so just terminate.
        graceful = [p for p in processes if getattr(p, 'graceful', False)]
        for process in graceful:
            if process.stdin and not process.stdin.closed:
                try:
                    process.stdin.close()
                except OSError:
                    pass
        for process in graceful:
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        for process in reversed(processes):
            if process.poll() is None:
                process.terminate()
        for process in processes:
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()

    def stop_session():
        try:
            if client[0]:
                client[0].shutdown(socket.SHUT_RDWR)    # a write to a browser that stopped reading would block forever
        except OSError:
            pass
        with guard:
            remaining = list(active)
        cleanup(remaining)
        if viewer.acquire(timeout=5):     # let the stream handler finish before the next tune
            viewer.release()

    class Handler(BaseHTTPRequestHandler):
        def reply(self, code, body=b'', ctype='text/plain; charset=utf-8'):
            self.send_response(code)
            self.send_header('Content-Type', ctype)
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.headers.get('Origin') != 'http://' + self.headers.get('Host', ''):
                return self.send_error(403)
            if self.path == '/prepare':
                _, choice = devices()
                backend = backends.get(choice)
                if not isinstance(backend, QocastBackend) or backend.channel != 1:
                    return self.reply(400, b'No primary hardware tuner selected')
                try:
                    backend.ensure_service()
                    return self.reply(200, b'{}', 'application/json')
                except (ValueError, ConnectionError) as error:
                    return self.reply(502, str(error).encode())
            if self.path == '/stop':
                stop_session()
                self.send_response(204)
                self.end_headers()
                return
            if self.path == '/select':
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 200:
                        raise ValueError('bad size')
                    chosen = json.loads(self.rfile.read(length)).get('id')
                except (ValueError, AttributeError):
                    return self.reply(400, b'Expected {"id": ...}')
                entries, _ = devices()
                if chosen not in [entry['id'] for entry in entries] or chosen == 'replay':
                    return self.reply(400, b'That receiver is not plugged in.')
                stop_session()                  # the old receiver is released before the new one is used
                settings['tuner'] = chosen
                save_settings()
                print('Receiver: %s' % LABELS[chosen], flush=True)
                self.send_response(204)
                self.end_headers()
                return
            if self.path == '/gain':             # RTL-SDR RF gain: used from the next tuning on
                _, choice = devices()
                if choice != 'rtlsdr':
                    return self.reply(400, b'Only the RTL-SDR has an RF gain setting.')
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 200:
                        raise ValueError('bad size')
                    wanted = float(json.loads(self.rfile.read(length))['gain'])
                    if not 0 <= wanted <= 50:
                        raise ValueError('range')
                except (ValueError, KeyError, TypeError, AttributeError):
                    return self.reply(400, b'Expected {"gain": dB between 0 and 50}')
                applied = backends['rtlsdr'].gain = RtlSdrBackend.snap_gain(wanted)     # a step the tuner really has
                settings['gain'] = applied
                save_settings()
                print('RF gain: %.1f dB' % applied, flush=True)
                return self.reply(200, json.dumps({'gain': applied}).encode(), 'application/json')
            if self.path == '/input':            # LNB voltage and RF input of a MiniTiouner / PicoTuner
                _, choice = devices()
                if choice not in ('minitiouner', 'picotuner'):
                    return self.reply(400, b'This receiver has no LNB power or input setting.')
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 200:
                        raise ValueError('bad size')
                    wanted = json.loads(self.rfile.read(length))
                    power = wanted.get('lnb_power', backends[choice].lnb_power)     # what is not sent stays as it is
                    rf = wanted.get('rf_input', backends[choice].rf_input)
                except (ValueError, AttributeError):
                    return self.reply(400, b'Expected {"lnb_power": ..., "rf_input": ...}')
                if power not in LNB_POWER or rf not in RF_INPUTS:
                    return self.reply(400, b'lnb_power is off, vertical or horizontal; rf_input is A or B.')
                settings['lnb_power'], settings['rf_input'] = power, rf
                save_settings()
                print('LNB power: %s, input %s' % (power, rf), flush=True)
                for kind in ('minitiouner', 'picotuner'):
                    try:
                        backends[kind].set_input(power, rf)      # a running service retunes by itself
                    except ValueError as error:
                        return self.reply(502, str(error).encode())
                self.send_response(204)
                self.end_headers()
                return
            self.send_error(404)

        def do_GET(self):
            url = urlparse(self.path)
            if url.path == '/status':
                return self.reply(200, json.dumps({**status.snapshot(), **stream_info[0].snapshot(), 'session': session_id[0]}).encode(), 'application/json')
            if url.path == '/devices':
                entries, choice = devices()
                backend = backends.get(choice)
                hardware = choice in ('minitiouner', 'picotuner')
                return self.reply(200, json.dumps({
                    'devices': entries, 'selected': choice,
                    'max_symbol_rate': backend.max_symbol_rate if backend else None,
                    'reconnect': bool(backend and backend.reconnect),
                    'autotune': not args.no_autotune,          # the page tunes the beacon by itself once a receiver is chosen
                    'controls': {'lnb_power': backends[choice].lnb_power, 'rf_input': backends[choice].rf_input} if hardware and args.channel == 1 else None,
                    'gain': {'value': backends['rtlsdr'].gain, 'steps': RtlSdrBackend.GAIN_STEPS} if choice == 'rtlsdr' else None,
                    }).encode(), 'application/json')
            if url.path in STATIC:
                name, ctype = STATIC[url.path]
                return self.reply(200, (ROOT / name).read_bytes(), ctype)
            if url.path != '/stream':
                return self.send_error(404)
            _, choice = devices()
            backend = backends.get(choice)
            if backend is None:
                return self.reply(409, b'Choose a receiver first.')
            query = parse_qs(url.query)
            try:
                downlink, symbol_rate = float(query['freq'][0]), int(query['sr'][0])
                if not 10490.0 <= downlink <= 10500.0:
                    raise ValueError('Downlink must be within the BATC spectrum, 10490–10500 MHz')
                backend.check(downlink, symbol_rate)
            except (KeyError, IndexError):
                return self.reply(400, b'Expected freq (downlink MHz) and sr (kS/s)')
            except ValueError as error:
                return self.reply(400, str(error).encode())
            if not viewer.acquire(timeout=1):
                return self.reply(409, b'Another session is still stopping; try again.')
            processes, files, pumps = [], [], []
            client[0] = self.connection
            session_id[0] += 1
            status.reset()
            info = stream_info[0] = TsInfo()

            def start(command, name, **kwargs):
                log = (logs / (name + '.log')).open('wb')
                files.append(log)
                with guard:       # shutdown cannot miss a child started now
                    if stopping.is_set():
                        raise RuntimeError('Server is stopping')
                    process = subprocess.Popen(command, env=env, **{'stderr': log, **kwargs})
                    process.graceful = name == 'radio'
                    processes.append(process)
                    active.append(process)
                return process
            ctx = SimpleNamespace(start=start, files=files, pumps=pumps, status=status, on_close=[])
            started = False
            try:
                source = backend.open(ctx, downlink, symbol_rate)
                encoder = start(ffmpeg_command(args.ffmpeg), 'mse', stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                pumps.append(threading.Thread(target=relay, args=(source, encoder.stdin, info), daemon=True))
                pumps[-1].start()
                status.set_running(True)
                self.send_response(200)
                self.send_header('Content-Type', 'video/mp4')
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                started = True
                while not stopping.is_set():
                    block = encoder.stdout.read1(65536)
                    if not block:
                        break
                    self.wfile.write(block)
                    self.wfile.flush()
            except ValueError as error:           # the receiver could not be used: say why, before any video
                print('Not tuned:', error, flush=True)
                if not started:
                    self.reply(502, str(error).encode())
            except (OSError, RuntimeError) as error:
                print('Session ended:', error, flush=True)
            finally:
                for close in ctx.on_close:
                    try:
                        close()
                    except Exception:
                        pass
                cleanup(processes)
                status.reset()
                stream_info[0] = TsInfo()
                for thread in pumps:      # the pipe closed with the process; finish before the log does
                    thread.join(timeout=2)
                with guard:
                    for process in processes:
                        active.remove(process)
                for file in files:
                    file.close()
                client[0] = None
                viewer.release()

        def log_request(self, code='-', size='-'):
            # The page asks for /status four times a second: only refusals and errors are worth a line.
            try:
                failed = int(code) >= 400
            except ValueError:
                failed = True
            if failed:
                print('%s -> %s' % (self.requestline, code), flush=True)

        def log_message(self, fmt, *values):
            print(fmt % values, flush=True)

    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    if args.watch_stdin:
        def watch_parent():
            sys.stdin.buffer.read()
            server.shutdown()
        threading.Thread(target=watch_parent, daemon=True).start()
    url = 'http://127.0.0.1:%d/' % server.server_port
    print('QO-100 WebPlayer: ' + url + '  (Ctrl+C stops the server)', flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        stopping.set()
        with guard:
            remaining = list(active)
        cleanup(remaining)
        for backend in backends.values():
            backend.shutdown()
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
