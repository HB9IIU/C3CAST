"""Tuner backends: how a receiver is tuned, where its transport stream comes from and how its status is read.

A backend opens a session for one tuning and returns a source with read1(size) (like a pipe) that ends when the
stream ends. The server hands the source to FFmpeg. Standard library only.

  RtlSdrBackend   rtl_iq -> datvrx (software demodulator), status from datvrx's text lines
  ReplayBackend   a recorded transport stream (development)
  QocastBackend   MiniTiouner / PicoTuner through the bundled tuner service (tuner-service\):
                  tuning and status over its local HTTP API, the transport stream over loopback UDP
"""
import collections
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

from rx_status import pump


class ProcessSource:
    """The standard output of a decoder process."""

    def __init__(self, process):
        self.process = process

    def read1(self, size):
        return self.process.stdout.read1(size)

    def close(self):
        pass                                # the process is cleaned up with the session


class UdpSource:
    """A transport stream in loopback UDP datagrams. The tuner service only sends while the tuner is locked, so the
    stream ends when nothing arrives for `silence` seconds, or when no lock comes within `first_timeout`."""

    def __init__(self, port, first_timeout=30.0, silence=3.0):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(('127.0.0.1', port))
        self.sock.settimeout(first_timeout)
        self.silence, self.received = silence, False

    def read1(self, size):
        try:
            data = self.sock.recv(max(size, 65536))
        except (socket.timeout, OSError):
            return b''
        if not self.received:
            self.received = True
            self.sock.settimeout(self.silence)
        return data

    def close(self):
        self.sock.close()


class ConstellationScaler:
    """The demodulator gives raw signed bytes whose size depends on its gain. The display wants unit mean power
    (like datvrx's symbols), so the scale is taken from the recent points themselves."""

    def __init__(self, history=256):
        self.history = collections.deque(maxlen=history)
        self.last = None

    def clear(self):
        self.history.clear()
        self.last = None
        return []

    def add(self, raw):
        batch = [(p[0] - 256 if p[0] > 127 else p[0], p[1] - 256 if p[1] > 127 else p[1])
                 for p in raw if isinstance(p, (list, tuple)) and len(p) == 2 and all(isinstance(v, int) for v in p)]
        if not batch or batch == self.last:            # the same reading again: nothing new to show
            return []
        self.last = batch
        self.history.extend(batch)
        power = sum(i * i + q * q for i, q in self.history) / len(self.history)
        if power <= 0:
            return []
        scale = power ** 0.5
        return [(i / scale, q / scale) for i, q in batch]


class RtlSdrBackend:
    id = 'rtlsdr'
    reconnect = False
    max_symbol_rate = 1500
    # The gain steps of the R820T / R828D tuner (RTL-SDR Blog V4 included), dB; as in DATVision's Pi player.
    GAIN_STEPS = (0.0, 0.9, 1.4, 2.7, 3.7, 7.7, 8.7, 12.5, 14.4, 15.7, 16.6, 19.7, 20.7, 22.9, 25.4, 28.0, 29.7,
                  32.8, 33.8, 36.4, 37.2, 38.6, 40.2, 42.1, 43.4, 43.9, 44.5, 48.0, 49.6)

    def __init__(self, bin_dir, lnb_lo, lnb_correction, gain):
        self.bin_dir, self.lnb_lo, self.lnb_correction = bin_dir, lnb_lo, lnb_correction
        self.gain = self.snap_gain(gain)

    @classmethod
    def snap_gain(cls, value):
        """The nearest gain the tuner really has."""
        return min(cls.GAIN_STEPS, key=lambda step: abs(step - value))

    def check(self, downlink_mhz, symbol_rate):
        if_mhz = downlink_mhz - self.lnb_lo + self.lnb_correction
        if not 25 <= symbol_rate <= self.max_symbol_rate:
            raise ValueError('Symbol rate must be 25–%d kS/s' % self.max_symbol_rate)
        if not 24 <= if_mhz <= 1766:
            raise ValueError('IF %.3f MHz is outside the stick range 24–1766 MHz' % if_mhz)
        return if_mhz

    def open(self, ctx, downlink_mhz, symbol_rate):
        if_mhz = self.check(downlink_mhz, symbol_rate)
        for name in ('rtl_iq.exe', 'datvrx.exe', 'librtlsdr.dll'):
            if not (self.bin_dir / name).is_file():
                raise ValueError('The RTL-SDR runtime is incomplete: missing ' + name)
        rate = 2560000 if symbol_rate >= 1250 else 2400000
        source = ctx.start([str(self.bin_dir / 'rtl_iq.exe'), str(round(if_mhz * 1e6)), str(rate), str(self.gain),
                            '--watch-stdin'], 'radio', stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        transport = ctx.start([str(self.bin_dir / 'datvrx.exe'), '-', '--rate', str(rate / 1e6), '--format', 'cu8',
                               '--rs', str(symbol_rate / 1000), '--std', '0', '--roll', '0.25', '--no-realtime',
                               '--cells', '1024'],
                              'receiver', stdin=source.stdout, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        source.stdout.close()
        # datvrx's status lines drive the lock, quality and constellation displays.
        ctx.pumps.append(threading.Thread(target=pump, args=(transport.stderr, ctx.files[-1], ctx.status), daemon=True))
        ctx.pumps[-1].start()
        print('Tuned: IF %.6f MHz, %d kS/s' % (if_mhz, symbol_rate), flush=True)
        return ProcessSource(transport)

    def shutdown(self):
        pass


class ReplayBackend:
    id = 'replay'
    reconnect = False
    max_symbol_rate = 1500

    def __init__(self, path, ffmpeg):
        self.path, self.ffmpeg = path, ffmpeg

    def check(self, downlink_mhz, symbol_rate):
        return None                          # the clicked carrier is ignored

    def open(self, ctx, downlink_mhz, symbol_rate):
        return ProcessSource(ctx.start([str(self.ffmpeg), '-hide_banner', '-loglevel', 'warning', '-re',
                                        '-stream_loop', '-1', '-i', str(self.path.resolve()), '-map', '0', '-c', 'copy',
                                        '-f', 'mpegts', 'pipe:1'], 'replay', stdout=subprocess.PIPE))

    def shutdown(self):
        pass


class QocastBackend:
    """MiniTiouner or PicoTuner, through the bundled tuner service. It is the only owner of the USB device; it is
    started here (headless, closing by itself if this program disappears) unless one is already answering."""
    reconnect = True                         # a hardware demodulator drops and regains lock: reconnect by itself
    max_symbol_rate = 10000

    def __init__(self, kind, service_exe, api_port, ts_port, lnb_lo, lnb_correction, lnb_power, rf_input, config_dir, channel=1, ts_port2=5002, primary_port=None):
        self.id = kind
        self.channel = channel               # 2: the PicoTuner's second tuner, served by receiver 1's service (never started here)
        self.ts_port2 = ts_port2
        self.primary_port = primary_port
        self.service_exe = Path(service_exe) if service_exe else None
        self.api_port, self.ts_port = api_port, ts_port
        self.lnb_lo, self.lnb_correction, self.lnb_power = lnb_lo, lnb_correction, lnb_power
        self.rf_input = 'A' if kind == 'picotuner' else rf_input      # a PicoTuner has no input to choose
        self.config_dir = config_dir
        self.service = None

    # ---- the tuner service's local API (http://127.0.0.1:<port>/api/v1/...)

    def api(self, method, path, body=None, timeout=2.0):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request('http://127.0.0.1:%d/api/v1/%s' % (self.api_port, path), data=data, method=method,
                                         headers={'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read() or b'{}')
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read()).get('error')
            except (ValueError, AttributeError):
                detail = None
            raise ValueError('The tuner refused the request: %s' % (detail or 'HTTP %d' % error.code))
        except (urllib.error.URLError, OSError, ValueError) as error:
            raise ConnectionError(str(error))

    def check(self, downlink_mhz, symbol_rate):
        if not 1 <= symbol_rate <= self.max_symbol_rate:
            raise ValueError('Symbol rate must be 1–%d kS/s' % self.max_symbol_rate)
        return None

    def ensure_service(self):
        try:
            if self.api('GET', 'health').get('ok'):
                return
        except ConnectionError:
            pass
        if self.channel == 2:
            if not self.primary_port:
                raise ValueError('The first receiver must be running: the PicoTuner\'s second tuner is served by it.')
            base = 'http://127.0.0.1:%d' % self.primary_port
            request = urllib.request.Request(base + '/prepare', data=b'', method='POST', headers={'Origin': base})
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    response.read()
                return
            except OSError as error:
                raise ValueError('Cannot start the shared PicoTuner service: ' + str(error))
        if self.service and self.service.poll() is None:
            deadline = time.monotonic() + 20
        else:
            if not self.service_exe or not self.service_exe.is_file():
                raise ValueError('The tuner service was not found (%s). Run Build-TunerService.cmd, or give '
                                 '--service-exe.' % (self.service_exe or 'no path'))
            config = self.config_dir / 'tuner-service.json'
            config.write_text(json.dumps({
                'receiver_type': self.id, 'lnb_offset_khz': round((self.lnb_lo - self.lnb_correction) * 1000),
                'rf_input': self.rf_input, 'lnb_power': self.lnb_power, 'control_port': self.api_port,
                'muted': True, 'always_on_top': False}, indent=2), encoding='utf-8')
            self.service = subprocess.Popen([str(self.service_exe), '--config', str(config), '--parent', str(os.getpid()),
                                            '--ts-udp', str(self.ts_port), '--ts-udp2', str(self.ts_port2)], cwd=str(self.service_exe.parent),
                                           creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))   # no console window
            deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.service and self.service.poll() is not None:
                if self.service.returncode == 2:
                    raise ValueError('Another player or tuner service is using the receiver. Close it, then press Receive again.')
                raise ValueError('The tuner service exited (code %s). Check server.log and the tuner-service log.' % self.service.returncode)
            try:
                if self.api('GET', 'health').get('ok'):
                    return
            except ConnectionError:
                time.sleep(0.3)
        raise ValueError('The tuner service did not start answering on port %d.' % self.api_port)

    def open(self, ctx, downlink_mhz, symbol_rate):
        self.check(downlink_mhz, symbol_rate)
        self.ensure_service()
        try:
            deadline = time.monotonic() + 5
            while not self.api('GET', 'health').get('source_connected') and time.monotonic() < deadline:
                time.sleep(.1)
            if not self.api('GET', 'health').get('source_connected'):
                raise ValueError('The tuner service cannot open the tuner. Is it plugged in, and not used by another program?')
            source = UdpSource(self.ts_port)                  # before tuning, so no data is missed
            ctx.on_close.append(source.close)
            self.api('POST', 'tune', {'request_id': uuid.uuid4().hex, 'tuner': self.channel, 'direct': False,
                                      'frequency_khz': round(downlink_mhz * 1000), 'symbol_rate_ksps': symbol_rate})
        except ConnectionError as error:
            raise ValueError('The tuner service stopped answering: %s' % error)
        except OSError as error:                              # the UDP port is taken (another session or program)
            raise ValueError('Cannot listen for the stream on UDP port %d: %s' % (self.ts_port, error))
        stop = threading.Event()
        poller = threading.Thread(target=self.poll_status, args=(stop, ctx.status), daemon=True)
        poller.start()
        ctx.on_close.append(stop.set)
        ctx.pumps.append(poller)
        print('Tuned: %.3f MHz, %d kS/s (%s)' % (downlink_mhz, symbol_rate, self.id), flush=True)
        return source

    def poll_status(self, stop, status):
        scaler = ConstellationScaler()
        while not stop.wait(0.25):
            try:
                reply = self.api('GET', 'status', timeout=1.0)
            except (ConnectionError, ValueError):
                continue
            receiver = reply.get('receiver') or {}
            if self.channel == 2:                             # the second tuner reports lock and MER only
                second = reply.get('tuner2') or {}
                status.set_hardware(second.get('locked'), None, second.get('mer_db'), None, 0, None, None)
                continue
            points = scaler.add(receiver.get('constellation') or []) if receiver.get('locked') else scaler.clear()
            status.set_hardware(receiver.get('locked'), receiver.get('modcod'), receiver.get('mer_db'),
                                receiver.get('db_margin'), receiver.get('lpdc_errors'), receiver.get('rf_level_db'), points)

    def set_input(self, lnb_power, rf_input):
        """LNB voltage (off / vertical / horizontal) and RF input (A / B). A running service saves it and retunes the
        current station by itself; otherwise it is used the next time the service starts."""
        if self.channel == 2:
            return                                            # shared with the first tuner: set there
        if self.id == 'picotuner':
            rf_input = 'A'
        changed = (lnb_power, rf_input) != (self.lnb_power, self.rf_input)
        self.lnb_power, self.rf_input = lnb_power, rf_input
        if not changed:
            return
        try:
            self.api('POST', 'input', {'lnb_power': lnb_power, 'rf_input': rf_input})
        except ConnectionError:
            pass                                              # not running: the new values are written at its next start

    def shutdown(self):
        if self.service and self.service.poll() is None:
            self.service.terminate()
            try:
                self.service.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.service.kill()
