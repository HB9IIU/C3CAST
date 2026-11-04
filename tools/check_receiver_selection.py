"""Browser regression for receiver pills and measured-carrier tuning, without hardware.

Requires development-only Playwright and installed Edge.
"""
import logging
from pathlib import Path
import re
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'webapp'))
import app
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

FAKE_SPECTRUM = """
window.WebSocket = class extends EventTarget {
 constructor() { super(); setTimeout(() => {
  this.dispatchEvent(new Event('open'));
  const bins=new Uint16Array(9001).fill(10000);
  for(let i=0;i<bins.length;i++){
   const f=10490.5+i*.001;
   if(Math.abs(f-10491.5)<.75||Math.abs(f-10494.25)<.1665||Math.abs(f-10496.25)<.25)bins[i]=30000;
  }
  this.dispatchEvent(new MessageEvent('message',{data:bins.buffer}));
 },50); }
 close() {}
};
"""
FAKE_PLAYER = """<script>
window.tunes=[];
addEventListener('message',e=>{if(e.source===parent&&e.data.type==='tune'){
 tunes.push(e.data);parent.postMessage({type:'rx',tuned:e.data,state:'locked',callsign:'TEST'},'*');
}});
</script>"""


def main():
    logging.getLogger('werkzeug').setLevel(logging.ERROR)
    server = make_server('127.0.0.1', 0, app.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page(viewport={'width': 1500, 'height': 1100})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.add_init_script(FAKE_SPECTRUM)
            entries = [dict(number=n, label=f'Test receiver {n}', available=False, state='running',
                            error='', url=f'http://127.0.0.1:3900{n}') for n in (1, 2)]
            page.route('**/api/receivers', lambda route: route.fulfill(json={'receivers': entries}))
            page.route(re.compile(r'http://127\.0\.0\.1:3900[12]/embed.*'),
                       lambda route: route.fulfill(content_type='text/html', body=FAKE_PLAYER))
            page.goto(f'http://127.0.0.1:{server.server_port}')
            frames = [page.frame_locator(f'[data-receiver="{n}"] iframe') for n in (1, 2)]
            for frame in frames:
                frame.locator('body').wait_for()
            canvas = page.locator('#spectrum')
            def click_signal(frequency):
                box = canvas.bounding_box()
                canvas.click(position={'x': (frequency-10490.5)/9*box['width'], 'y': 40})
            def tunes(n):
                return frames[n-1].locator('body').evaluate('()=>window.tunes')
            tx = page.locator('#freq').input_value()
            page.locator('[data-receiver="2"] .rx-pill').click()
            assert not tunes(1) and not tunes(2), 'Selecting a pill retuned a receiver'
            assert page.locator('[data-receiver="2"] .rx-pill').get_attribute('aria-pressed') == 'true'
            click_signal(10494.15)  # Off-centre click must find centre AND SR of the 333 kS/s carrier.
            frames[1].locator('body').evaluate('()=>new Promise(r=>setTimeout(r,50))')
            signal = tunes(2)[-1]
            assert abs(signal['centerMhz']-10494.25)<.005 and signal['sr']==333, signal
            assert not tunes(1), 'The unselected receiver was retuned'
            assert page.locator('#freq').input_value() == tx, 'RX click changed TX frequency'
            assert page.locator('[data-receiver="2"] .rx-rate').input_value() == '333'
            page.locator('[data-receiver="1"] .rx-pill').click()
            click_signal(10491.7)
            frames[0].locator('body').evaluate('()=>new Promise(r=>setTimeout(r,50))')
            assert tunes(1)[-1]['centerMhz'] == 10491.5 and tunes(1)[-1]['sr']==1500
            click_signal(10498.5)
            assert len(tunes(1))==1 and len(tunes(2))==1, 'Noise click retuned a receiver'
            assert 'No signal' in page.locator('#rxSpectrumMessage').inner_text()
            page.evaluate('window.QO_LOCKED=true')
            click_signal(10496.2)
            frames[0].locator('body').evaluate('()=>new Promise(r=>setTimeout(r,50))')
            assert tunes(1)[-1]['sr']==500, 'RX tuning was blocked by TX on-air lock'
            page.evaluate('window.QO_LOCKED=false;window.slotClicks=[];window.onBatcSlotSelected=x=>slotClicks.push(x);window.QO_ALLOWED_MHZ=[10492.75];window.batcRedraw()')
            box = canvas.bounding_box()
            canvas.click(position={'x': (10492.75-10490.5)/9*box['width'], 'y': box['height']-32})
            assert page.evaluate('window.slotClicks') == [10492.75], 'TX slot selection changed'
            assert len(tunes(1))==2 and len(tunes(2))==1, 'TX slot retuned a receiver'
            assert not errors, errors
            (ROOT/'output').mkdir(exist_ok=True)
            page.screenshot(path=str(ROOT/'output/receiver-pills.png'), full_page=True)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    print('Pills, measured centre/SR, beacon, noise rejection, RX while TX locked, and separate TX slots passed.')


if __name__ == '__main__':
    main()
