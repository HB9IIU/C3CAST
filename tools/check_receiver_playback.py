"""Offline integration check: recorded TS -> receiver -> FFmpeg -> real C3CAST page.

Uses Playwright/Edge for development only. Does not open receiver hardware or transmit RF.
"""
import json
import logging
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'webapp'))
import app
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright


def port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    output = ROOT / 'output'
    output.mkdir(exist_ok=True)
    rx_ff = ROOT / 'webapp/receiver/bin/ffmpeg.exe'
    tx_ff = ROOT / 'tools/ffmpeg/bin/ffmpeg.exe'
    encoders = [('h264', rx_ff, 'libx264'), ('h265', tx_ff, 'libx265'), ('h266', tx_ff, 'libvvenc')]
    # A known pattern and tone exercise video AND audio through the complete receive pipeline.
    for name, exe, encoder in encoders:
        command = [str(exe), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                   'testsrc2=size=320x180:rate=10', '-f', 'lavfi', '-i', 'sine=frequency=600:sample_rate=48000',
                   '-t', '3', '-c:v', encoder, '-g', '10', '-c:a', 'aac', '-f', 'mpegts']
        if name == 'h266':
            command += ['-pix_fmt', 'yuv420p10le', '-preset', 'faster']
        elif name == 'h265':
            command += ['-preset', 'ultrafast']
        command += [str(output / f'rx-{name}.ts')]
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=90)
    portable = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
    app_process = None
    app_log = None
    server = None
    if portable:
        app_port = port()
        base = f'http://127.0.0.1:{app_port}'
        env = dict(os.environ, C3CAST_NO_BROWSER='1', C3CAST_NO_AUTOQUIT='1', C3CAST_PORT=str(app_port))
        app_log = (output / 'portable-app.log').open('wb')
        app_process = subprocess.Popen([str(portable)], cwd=portable.parent, env=env, stdout=app_log, stderr=app_log,
                                       creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        rx_ff = portable.parent / '_internal/receiver/bin/ffmpeg.exe'
        deadline = time.monotonic() + 20
        while True:
            try:
                urllib.request.urlopen(base + '/api/receivers', timeout=.5).close()
                break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError('Portable app failed to start')
                time.sleep(.1)
    else:
        server = make_server('127.0.0.1', 0, app.app, threaded=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f'http://127.0.0.1:{server.server_port}'
    workers = []
    errors = []
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp, sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1500, 'height': 1250})
            page.on('pageerror', lambda error: errors.append(str(error)))
            absent = [dict(number=n, label='No receiver connected', available=False, state='stopped', error='', url=None) for n in (1, 2)]
            idle_route = lambda route: route.fulfill(json={'receivers': absent})
            page.route('**/api/receivers', idle_route)
            page.goto(base)
            page.locator('[data-receiver="2"]').wait_for()
            page.screenshot(path=str(output / 'c3cast-receivers-desktop.png'), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile page overflows'
            page.screenshot(path=str(output / 'c3cast-receivers-mobile.png'), full_page=True)
            page.set_viewport_size({'width': 1500, 'height': 1250})
            # Each codec is tested through the same embedded player used in production.
            for name, _, _ in encoders:
                entries, pair = [], []
                for n in (1, 2):
                    worker_port = port()
                    worker_log = open(Path(temp) / f'{name}-{n}.log', 'wb')
                    prefix = [str(portable), '--worker', 'receiver'] if portable else [
                        sys.executable, '-u', str(ROOT / 'webapp/receiver/webplayer.py')]
                    process = subprocess.Popen(prefix + [
                        '--port', str(worker_port), '--ffmpeg', str(rx_ff), '--input-ts', str(output / f'rx-{name}.ts'),
                        '--no-browser', '--no-autotune', '--watch-stdin', '--settings', str(Path(temp) / f'{name}-{n}.json'),
                        '--logs', str(Path(temp) / f'{name}-{n}')], stdin=subprocess.PIPE, stdout=worker_log, stderr=worker_log,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    workers.append((process, worker_log))
                    pair.append((process, worker_log))
                    url = f'http://127.0.0.1:{worker_port}'
                    deadline = time.monotonic() + 15
                    while True:
                        try:
                            urllib.request.urlopen(url + '/devices', timeout=.5).close()
                            break
                        except OSError:
                            if time.monotonic() > deadline:
                                raise RuntimeError('Replay server failed: ' + name)
                            time.sleep(.1)
                    entries.append(dict(number=n, label=f'Replay {name}', available=True, state='running', error='', url=url))
                page.unroute('**/api/receivers')
                page.route('**/api/receivers', lambda route, request, data=entries: route.fulfill(json={'receivers': data}))
                page.route('**/api/receivers/*/start', lambda route: route.fulfill(json={'ok': True}))
                page.reload()
                for n in (1, 2):
                    frame = page.frame_locator(f'[data-receiver="{n}"] iframe')
                    frame.locator('#video').wait_for(timeout=15000)
                    page.locator(f'[data-receiver="{n}"] button[type="submit"]').click()
                    frame.locator('#video').evaluate("v => new Promise((resolve,reject) => {const timer=setTimeout(()=>reject(new Error('No picture')),25000);const check=()=>{if(v.videoWidth>0&&v.currentTime>.3){clearTimeout(timer);resolve()}else setTimeout(check,100)};check()})")
                    print(name, 'RX', n, frame.locator('#video').evaluate('v=>({width:v.videoWidth,height:v.videoHeight,time:v.currentTime})'), flush=True)
                assert page.frame_locator('[data-receiver="2"] iframe').locator('#video').evaluate('v=>v.muted')
                page.screenshot(path=str(output / f'c3cast-receiver-{name}.png'), full_page=True)
                page.locator('[data-receiver="1"] .rx-stop').click()
                page.locator('[data-receiver="2"] .rx-stop').click()
                page.goto('about:blank')
                for process, worker_log in pair:
                    process.stdin.close()
                    process.wait(timeout=20)
                    worker_log.close()
                page.unroute('**/api/receivers')
                page.route('**/api/receivers', idle_route)
                page.unroute('**/api/receivers/*/start')
                page.goto(base)
            assert not errors, errors
            browser.close()
    finally:
        for process, log in workers:
            if process.poll() is None:
                process.stdin.close()
                try:
                    process.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    process.kill()
            log.close()
        if server:
            server.shutdown()
            server.server_close()
        if app_process:
            try:
                urllib.request.urlopen(urllib.request.Request(base + '/api/quit', data=b'{}',
                    headers={'Content-Type': 'application/json'}), timeout=5).close()
                app_process.wait(timeout=20)
            finally:
                if app_process.poll() is None:
                    app_process.terminate()
                app_log.close()
    print('Browser playback, layout, and shutdown checks passed. No RF used.', flush=True)


if __name__ == '__main__':
    main()
