"""Own the two browser receivers; never attach to another application's local services."""
import atexit
import json
import os
import socket
import subprocess
import threading
import time
import urllib.request

import paths
import tuner_assignment

_lock = threading.RLock()
_workers = {}
_closing = False


def _port(kind=socket.SOCK_STREAM):
    with socket.socket(socket.AF_INET, kind) as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def status():
    slots = tuner_assignment.slots()
    with _lock:
        for entry in _workers.values():
            if entry['state'] == 'running' and entry['proc'].poll() is not None:
                entry.update(state='error', error='Receiver stopped unexpectedly; press Receive to restart')
        return [dict(number=n, label=slots[n-1]['label'] if len(slots) >= n else 'No receiver connected',
                     available=len(slots) >= n, state=_workers.get(n, {}).get('state', 'stopped'),
                     error=_workers.get(n, {}).get('error', ''),
                     url=_workers.get(n, {}).get('url')) for n in (1, 2)]


def start(number):
    """Launch asynchronously; the page polls readiness without holding up transmission requests."""
    global _closing
    if number not in (1, 2):
        raise ValueError('Receiver must be 1 or 2')
    with _lock:
        if _closing:
            raise ValueError('C3CAST is closing')
        entry = _workers.get(number)
        if entry and entry['state'] in ('starting', 'running'):
            if entry['state'] == 'starting' or entry.get('proc') and entry['proc'].poll() is None:
                return
        slot = tuner_assignment.slot_for(number)
        if not slot:
            raise ValueError('No receiver connected')
        # Pico channel 2 belongs to the first receiver's hardware service.
        first = tuner_assignment.slot_for(1)
        shared = number == 2 and slot['tuner'] == 'picotuner' and slot['channel'] == 2 and first['tuner'] == 'picotuner'
        if shared:
            start(1)
        entry = dict(state='starting', error='', port=_port(), service_port=_port(), ts_port=_port(socket.SOCK_DGRAM), ts_port2=_port(socket.SOCK_DGRAM))
        if shared:
            entry['service_port'] = _workers[1]['service_port']
            entry['ts_port'] = _workers[1]['ts_port2']
            entry['primary_port'] = _workers[1]['port']
        entry['url'] = f"http://127.0.0.1:{entry['port']}"
        _workers[number] = entry
        threading.Thread(target=_launch, args=(number, slot, entry, shared), daemon=True).start()


def _launch(number, slot, entry, shared):
    try:
        data = paths.RECEIVER_DATA / str(number)
        data.mkdir(parents=True, exist_ok=True)
        ffmpeg = paths.RECEIVER / 'bin' / 'ffmpeg.exe'
        if not ffmpeg.is_file():
            raise ValueError('Receiver FFmpeg is missing; see docs/RECEIVERS.md')
        command = paths.worker_cmd('receiver') + [
            '--no-browser', '--no-autotune', '--watch-stdin', '--port', str(entry['port']),
            '--service-port', str(entry['service_port']), '--ts-port', str(entry['ts_port']),
            '--ts-port2', str(entry['ts_port2']),
            '--settings', str(data / 'settings.json'), '--logs', str(data / 'logs'),
            '--ffmpeg', str(ffmpeg), '--tuner', slot['tuner'], '--label', slot['label']]
        if shared:
            command += ['--channel', '2', '--primary-port', str(entry['primary_port'])]
        env = dict(os.environ)
        if slot['serial']:
            env['QOCAST_TUNER_SERIAL'] = slot['serial']
        else:
            env.pop('QOCAST_TUNER_SERIAL', None)
        with _lock:
            if _closing:
                return
            log = (data / 'server.log').open('wb')
            try:
                proc = subprocess.Popen(command, cwd=paths.RECEIVER, env=env, stdin=subprocess.PIPE,
                                        stdout=log, stderr=log,
                                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            finally:
                log.close()
            entry['proc'] = proc
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and proc.poll() is None and not _closing:
            try:
                with urllib.request.urlopen(entry['url'] + '/devices', timeout=.5) as response:
                    json.load(response)
                entry['state'] = 'running'
                return
            except (OSError, ValueError):
                time.sleep(.2)
        raise ValueError('Receiver did not start; check receivers/' + str(number) + '/server.log')
    except (OSError, ValueError) as error:
        entry.update(state='error', error=str(error))
        proc = entry.get('proc')
        if proc and proc.poll() is None:
            proc.stdin.close()


def stop():
    global _closing
    with _lock:
        _closing = True
        processes = [entry['proc'] for entry in _workers.values() if entry.get('proc')]
    # EOF asks the servers to clean up their demodulator and encoder before exiting.
    for proc in processes:
        if proc.poll() is None:
            try:
                proc.stdin.close()
            except OSError:
                pass
    for proc in processes:
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.terminate()
            proc.wait(timeout=5)


atexit.register(stop)
