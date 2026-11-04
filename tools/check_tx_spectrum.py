"""Offline TX spectrum rendering regression; no hardware or RF."""
import logging
from pathlib import Path
import sys
import threading
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'webapp'))
import app
from werkzeug.serving import make_server
from playwright.sync_api import sync_playwright

FAKE='''
window.txLabels=[]; window.redTrace=[];
const proto=CanvasRenderingContext2D.prototype;
const clear=proto.clearRect,begin=proto.beginPath,move=proto.moveTo,line=proto.lineTo,stroke=proto.stroke,fillText=proto.fillText;
proto.clearRect=function(...args){txLabels=[];redTrace=[];return clear.apply(this,args)};
proto.beginPath=function(){this.recorded=[];return begin.call(this)};
proto.moveTo=function(x,y){this.recorded.push([x,y]);return move.call(this,x,y)};
proto.lineTo=function(x,y){this.recorded.push([x,y]);return line.call(this,x,y)};
proto.stroke=function(){if(this.strokeStyle==='#ff3b3b')redTrace=this.recorded.slice();return stroke.call(this)};
proto.fillText=function(text,...args){if(text.startsWith('TX'))txLabels.push({text,color:this.fillStyle});return fillText.call(this,text,...args)};
window.sendSpectrum=(power=25000,beacon=true)=>{
 const frame=new Uint16Array(9001).fill(10000);
 if(beacon)for(let i=400;i<1600;i++)frame[i]=40000;
 for(let i=3400;i<4100;i++)frame[i]=power;
 testSocket.dispatchEvent(new MessageEvent('message',{data:frame.buffer}));
};
window.WebSocket=class extends EventTarget{constructor(){super();window.testSocket=this;setTimeout(()=>{this.dispatchEvent(new Event('open'));sendSpectrum()},100)}close(){}};
'''

def main():
 logging.getLogger('werkzeug').setLevel(logging.ERROR)
 server=make_server('127.0.0.1',0,app.app,threaded=True)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 report=dict(state='idle',error='',buffer='',packets='',elapsed=0,settings={'freq':2404.75,'sr':500000},log=[],flashing=False,cpu_percent=12)
 try:
  with patch.object(app,'find_esp',return_value={'connected':False,'port':'','info':'','how':'','candidates':[],'tried':[]}),sync_playwright() as p:
   browser=p.chromium.launch(channel='msedge',headless=True)
   page=browser.new_page(viewport={'width':1500,'height':1100})
   errors=[]
   page.on('pageerror',lambda error:errors.append(str(error)))
   page.add_init_script(FAKE)
   page.route('**/api/receivers',lambda r:r.fulfill(json={'receivers':[]}))
   page.route('**/api/status',lambda r:r.fulfill(json=report))
   page.goto(f'http://127.0.0.1:{server.server_port}')
   page.wait_for_function('window.testSocket && document.querySelector("#specChipText").textContent==="live"')
   assert not page.evaluate('txLabels.length')
   report['state']='transmitting'
   page.wait_for_function('txLabels.some(label=>label.text==="TX -4.6 dB vs beacon")')
   assert page.evaluate('txLabels[0].color')=='#3ecf8e'
   assert page.evaluate('redTrace.length>2')
   bounds=page.evaluate('({first:redTrace[0][0],last:redTrace.at(-1)[0],width:document.querySelector("#spectrum").clientWidth})')
   assert abs((bounds['first']/bounds['width']*9+10490.5)-(10494.25-.3375))<.03,bounds
   page.locator('#spectrum').screenshot(path=str(ROOT/'output/tx-spectrum-below.png'))
   page.evaluate('sendSpectrum(50000)')
   page.wait_for_function('txLabels.some(label=>label.text==="TX +3.1 dB vs beacon")')
   assert page.evaluate('txLabels[0].color')=='#ef5350'
   page.locator('#spectrum').screenshot(path=str(ROOT/'output/tx-spectrum-above.png'))
   page.evaluate('sendSpectrum(25000,false)')
   page.wait_for_function('txLabels.some(label=>label.text==="TX")')
   report['state']='idle'
   page.wait_for_function('txLabels.length===0&&redTrace.length===0')
   assert not errors,errors
   browser.close()
   print('TX-only rendering, actual frequency/SR, red measured trace, below/above-beacon colours, missing beacon and stop cleanup passed. No RF.')
 finally:
  server.shutdown();server.server_close()

if __name__=='__main__':main()
