"""Single-window browser/stream ownership regression. Uses replay, never tuner hardware."""
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
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'webapp'))
import app
from window_session import WindowLease
from single_instance import MainInstance
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright, expect


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    output = ROOT/'output'
    output.mkdir(exist_ok=True)
    ffmpeg = ROOT/'tools/ffmpeg/bin/ffmpeg.exe'
    sample = output/'window-replay.ts'
    subprocess.run([str(ffmpeg), '-hide_banner', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i',
                    'testsrc2=size=320x180:rate=10', '-t', '2', '-c:v', 'libx264', '-g', '10',
                    '-f', 'mpegts', str(sample)], check=True, timeout=20)
    if os.name == 'nt':
        name = 'Local\\C3CAST.Test.' + uuid.uuid4().hex
        with MainInstance(name) as owner:
            assert owner.acquired
            code = 'from single_instance import MainInstance\nwith MainInstance('+repr(name)+') as instance: print(instance.acquired)'
            child = subprocess.run([sys.executable, '-c', code], cwd=ROOT/'webapp', capture_output=True, text=True, timeout=10)
            assert child.returncode == 0 and child.stdout.strip() == 'False', child
        with MainInstance(name) as replacement:
            assert replacement.acquired
        print('Cross-process instance lock passed.', flush=True)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        port = free_port()
        worker_url = f'http://127.0.0.1:{port}'
        log = open(Path(tmp)/'receiver.log', 'wb')
        worker = subprocess.Popen([sys.executable, '-u', str(ROOT/'webapp/receiver/webplayer.py'),
            '--no-browser', '--no-autotune', '--watch-stdin', '--port', str(port), '--ffmpeg', str(ffmpeg),
            '--input-ts', str(sample), '--settings', str(Path(tmp)/'settings.json'), '--logs', str(Path(tmp)/'logs')],
            stdin=subprocess.PIPE, stdout=log, stderr=log, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        server = None
        try:
            for attempt in range(100):
                try:
                    urllib.request.urlopen(worker_url+'/devices', timeout=.5).close()
                    break
                except OSError:
                    if attempt == 99: raise
                    time.sleep(.1)
            entries = [dict(number=1, label='Replay receiver', available=False, state='running', error='', url=worker_url),
                       dict(number=2, label='No receiver connected', available=False, state='stopped', error='', url=None)]
            with patch.dict(app.app.config, SINGLE_WINDOW=True), patch.object(app, 'WINDOW', WindowLease()), \
                 patch.object(app.receivers, 'status', return_value=entries), patch.object(app.receivers, 'start') as start, \
                 patch.object(app, 'find_esp', return_value={'connected': False, 'port': '', 'info': '', 'how': '', 'candidates': [], 'tried': []}), \
                 sync_playwright() as pw:
                server = make_server('127.0.0.1', 0, app.app, threaded=True)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                base = f'http://127.0.0.1:{server.server_port}'
                browser = pw.chromium.launch(channel='msedge', headless=True)
                context = browser.new_context()
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))

                def ready(target):
                    target.locator('.window-blocked').wait_for(state='hidden')
                    expect(target.locator('.wrap')).to_be_visible()
                    target.frame_locator('[data-receiver="1"] iframe').locator('#video').wait_for()

                def play():
                    page.evaluate('window.c3TuneReceiver({centerMhz:10491.5,sr:1500})')
                    video = page.frame_locator('[data-receiver="1"] iframe').locator('#video')
                    video.evaluate("v=>new Promise((resolve,reject)=>{const until=Date.now()+20000;const check=()=>{if(v.videoWidth&&v.currentTime>.3)resolve();else if(Date.now()>until)reject(Error('No video'));else setTimeout(check,100)};check()})")
                    return video

                page.goto(base)
                ready(page)
                video = play()
                before = video.evaluate('v=>v.currentTime')
                duplicate = context.new_page()
                duplicate.goto(base)
                expect(duplicate.locator('.window-blocked')).to_contain_text('C3CAST is already open')
                assert duplicate.locator('iframe').count() == 0
                denied = duplicate.evaluate("fetch('/api/receivers/1/start',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'}).then(r=>r.status)")
                assert denied == 409
                duplicate.screenshot(path=str(output/'duplicate-window.png'))
                duplicate.close()
                assert app.WINDOW.occupied() and app.WATCH['bye'] == 0
                video.evaluate('(v,t)=>new Promise(r=>{const check=()=>v.currentTime>t?r():setTimeout(check,50);check()})', before)
                start.assert_not_called()
                print('Duplicate tab blocked; owner video continues and duplicate close is harmless.', flush=True)

                other_context = browser.new_context()
                other = other_context.new_page()
                other.goto(base)
                expect(other.locator('.window-blocked')).to_be_visible()
                assert other.locator('iframe').count() == 0
                other_context.close()
                print('Separate browser context blocked by server lease.', flush=True)

                page.reload()
                ready(page)
                video = play()
                # A delayed pagehide from an old iframe must never stop the replacement's stream.
                with urllib.request.urlopen(urllib.request.Request(worker_url+'/stop?client=obsolete-document',
                    data=b'', headers={'Origin': worker_url}), timeout=5) as response:
                    assert response.status == 204
                before = video.evaluate('v=>v.currentTime')
                video.evaluate('(v,t)=>new Promise(r=>{const check=()=>v.currentTime>t+.2?r():setTimeout(check,50);check()})', before)
                print('Reload and stale receiver-stop protection passed.', flush=True)

                page.locator('a[href="/setup"]').first.click()
                expect(page.locator('text=Station settings')).to_be_visible()
                assert page.locator('.window-blocked').count() == 0
                page.locator('a[href="/"]').click()
                ready(page)
                page.close()
                next_context = browser.new_context()
                next_page = next_context.new_page()
                next_page.goto(base)
                ready(next_page)
                assert not errors, errors
                next_context.close()
                context.close()
                browser.close()
                print('Setup navigation and ownership after normal close passed.', flush=True)
        finally:
            if server:
                server.shutdown()
                server.server_close()
            worker.stdin.close()
            try:
                worker.wait(timeout=20)
            except subprocess.TimeoutExpired:
                worker.kill()
            log.close()


if __name__ == '__main__':
    main()
