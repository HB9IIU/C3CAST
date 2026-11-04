"""Offline integration check: recorded TS -> receiver -> FFmpeg -> real C3CAST page.

Uses Playwright/Edge for development only. Does not open receiver hardware or transmit RF.
"""
import json
import logging
import os
import re
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'webapp'))
import app
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect


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
                urllib.request.urlopen(base + '/api/window/state', timeout=.5).close()
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
            page.add_init_script("window.rxReports=[];addEventListener('message',e=>{if(e.data?.type==='rx')rxReports.push(e.data)})")
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
                    page.locator(f'[data-receiver="{n}"] .rx-pill').click()
                    page.evaluate("window.c3TuneReceiver({centerMhz:10491.5,sr:1500})")
                    frame.locator('#video').evaluate("v => new Promise((resolve,reject) => {const timer=setTimeout(()=>reject(new Error('No picture')),25000);const check=()=>{if(v.videoWidth>0&&v.currentTime>.3){clearTimeout(timer);resolve()}else setTimeout(check,100)};check()})")
                    print(name, 'RX', n, frame.locator('#video').evaluate('v=>({width:v.videoWidth,height:v.videoHeight,time:v.currentTime})'), flush=True)
                codec = {'h264': 'H.264', 'h265': 'H.265', 'h266': 'H.266'}[name]
                page.wait_for_function('(codec)=>window.rxReports.some(r=>r.info?.video===codec)', arg=codec)
                assert page.frame_locator('[data-receiver="2"] iframe').locator('#video').evaluate('v=>v.muted')
                if name == 'h264':
                    first = page.frame_locator('[data-receiver="1"] iframe')
                    second = page.frame_locator('[data-receiver="2"] iframe')
                    slider = page.locator('[data-receiver="1"] .rx-volume')
                    expect(slider).to_be_enabled()
                    expect(first.locator('#sound')).to_be_hidden()
                    expect(second.locator('#sound')).to_be_hidden()
                    slider.press('Home')
                    expect(first.locator('#video')).to_have_js_property('volume', 0)
                    expect(first.locator('#video')).to_have_js_property('muted', True)
                    slider.evaluate("input=>{input.value='0.35';input.dispatchEvent(new Event('input',{bubbles:true}))}")
                    expect(first.locator('#video')).to_have_js_property('volume', .35)
                    expect(first.locator('#video')).to_have_js_property('muted', False)
                    page.locator('[data-receiver="1"] .rx-mute').click()
                    expect(first.locator('#video')).to_have_js_property('muted', True)
                    page.locator('[data-receiver="1"] .rx-mute').click()
                    expect(first.locator('#video')).to_have_js_property('muted', False)
                    expect(first.locator('#video')).to_have_js_property('paused', False)
                    expect(second.locator('#video')).to_have_js_property('muted', True)
                    print('Header volume/mute control, independent RX 2 mute, and hidden video overlays passed.', flush=True)
                    panel = page.locator('[data-receiver="1"]')
                    frame_identity = first.locator('#video').evaluate('v=>window.popupIdentity=crypto.randomUUID()')
                    before_popup = first.locator('#video').evaluate('v=>v.currentTime')
                    first.locator('#video').click()
                    expect(panel).to_have_class(re.compile(r'rx-popup'))
                    assert page.evaluate('document.fullscreenElement===null')
                    assert first.locator('#video').evaluate('v=>window.popupIdentity') == frame_identity
                    first.locator('#video').evaluate('(v,before)=>new Promise(r=>{const check=()=>v.currentTime>before+.2?r():setTimeout(check,50);check()})', before_popup)
                    page.screenshot(path=str(output/'receiver-popup-desktop.png'))
                    first.locator('#video').press('Escape')
                    expect(panel).not_to_have_class(re.compile(r'rx-popup'))
                    expect(page.locator('.rx-backdrop')).to_have_count(0)
                    first.locator('#video').click()
                    panel.locator('.rx-popup-close').click()
                    expect(panel).not_to_have_class(re.compile(r'rx-popup'))
                    first.locator('#video').click()
                    page.locator('.rx-backdrop').click(position={'x':4,'y':4})
                    expect(panel).not_to_have_class(re.compile(r'rx-popup'))
                    page.set_viewport_size({'width':390,'height':844})
                    first.locator('#video').click()
                    expect(panel).to_have_class(re.compile(r'rx-popup'))
                    box = panel.bounding_box()
                    assert box['x'] >= 0 and box['x']+box['width'] <= 390.5, box
                    assert box['y'] >= 0 and box['y']+box['height'] <= 844.5, box
                    page.screenshot(path=str(output/'receiver-popup-mobile.png'))
                    panel.locator('.rx-popup-close').click()
                    page.set_viewport_size({'width':1500,'height':1100})
                    assert first.locator('#video').evaluate('v=>window.popupIdentity') == frame_identity
                    print('Enlarged popup, uninterrupted stream, Escape/Close/backdrop, desktop/mobile passed.', flush=True)

                    loss_url = entries[0]['url'] + '/status'
                    reception = {'locked': True}
                    def lost_status(route):
                        response = route.fetch()
                        report = response.json()
                        report['locked'] = reception['locked']
                        route.fulfill(json=report)
                    page.route(loss_url, lost_status)
                    expect(page.locator('[data-receiver="1"] .rx-lock')).to_have_text('LOCKED')
                    reception['locked'] = False
                    expect(first.locator('#wait')).to_contain_text('Signal lost', timeout=5000)
                    expect(page.locator('[data-receiver="1"] .rx-lock')).to_have_text('SIGNAL LOST')
                    expect(page.locator('[data-receiver="1"] .rx-eye-display canvas')).to_have_attribute('title', 'No signal quality')
                    reception['locked'] = True
                    expect(first.locator('#wait')).to_be_hidden(timeout=5000)
                    stalled_generation = first.locator('#video').evaluate('v=>{v.pause();progressAt=performance.now()-6000;return generation}')
                    expect(first.locator('#wait')).to_contain_text('Signal lost', timeout=3000)
                    expect(page.locator('[data-receiver="1"] .rx-lock')).to_have_text('SIGNAL LOST')
                    first.locator('#video').evaluate('v=>{progressAt=performance.now()-11000}')
                    first.locator('#video').evaluate("(v,old)=>new Promise((resolve,reject)=>{const deadline=Date.now()+20000;const check=()=>{if(generation>old&&v.videoWidth&&v.currentTime>.3&&!v.paused)resolve();else if(Date.now()>deadline)reject(Error('Stall did not recover'));else setTimeout(check,100)};check()})", stalled_generation)
                    expect(first.locator('#wait')).to_be_hidden(timeout=5000)
                    expect(first.locator('#video')).to_have_js_property('volume', .35)
                    expect(second.locator('#video')).to_have_js_property('muted', True)
                    print('Signal-loss overlay, dark eye, lock return, and automatic stalled-player recovery passed.', flush=True)

                page.screenshot(path=str(output / f'c3cast-receiver-{name}.png'), full_page=True)
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
                token = uuid.uuid4().hex
                for attempt in range(12):
                    try:
                        urllib.request.urlopen(urllib.request.Request(base + '/api/window/claim',
                            data=json.dumps({'token': token}).encode(),
                            headers={'Content-Type': 'application/json'}), timeout=5).close()
                        break
                    except urllib.error.HTTPError as error:
                        if error.code != 409 or attempt == 11: raise
                        time.sleep(.25)
                urllib.request.urlopen(urllib.request.Request(base + '/api/quit', data=b'{}',
                    headers={'Content-Type': 'application/json', 'X-C3CAST-Window': token}), timeout=5).close()
                app_process.wait(timeout=20)
            finally:
                if app_process.poll() is None:
                    app_process.terminate()
                app_log.close()
    print('Browser playback, layout, and shutdown checks passed. No RF used.', flush=True)


if __name__ == '__main__':
    main()
