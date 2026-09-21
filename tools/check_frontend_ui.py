"""Browser smoke tests using synthetic inputs and mocked API responses only.

Run with the frontend on localhost:3000:
    .venv/Scripts/python.exe tools/check_frontend_ui.py
Screenshots go to the gitignored demo_data/ui-review directory.
"""
from pathlib import Path
import time

from shoot_ui import Chrome

MOCKS = r"""
window.__errors = [];
addEventListener('error', event => window.__errors.push(event.message));
addEventListener('unhandledrejection', event => window.__errors.push(String(event.reason)));
window.__requests = [];
window.__responseDelay = 2200;
window.__status = 200;
window.__history = [];
window.__stoppedTracks = 0;
const realFetch = window.fetch.bind(window);
const disclaimer = 'This tool does not query any government database and is not official verification.';
window.fetch = (url, options) => {
  const path = new URL(String(url), location.href).pathname;
  let body;
  if (path === '/health') body = {status:'ok',uidai_certificate_loaded:false,uidai_certificate_fingerprint:null,uidai_certificate_fingerprints:[],uidai_certificates_loaded:0,uidai_certificate_pinned:false,consent_enforcement:true,consent_subjects_configured:1,face_models_ready:true,face_models_missing:[],face_models_dir:'models'};
  if (path === '/reasons') body = {reasons:{}};
  if (path === '/dashboard/history') body = {records:window.__history,disclaimer};
  if (path === '/dashboard/summary') body = {by_verdict:{},by_doc_type:{},trend:[],top_reasons:[],disclaimer};
  return body ? Promise.resolve(new Response(JSON.stringify(body), {headers:{'Content-Type':'application/json'}})) : realFetch(url, options);
};
window.__sample = () => {
  const canvas = document.createElement('canvas'); canvas.width=640; canvas.height=400;
  const ctx=canvas.getContext('2d'); ctx.fillStyle='#eee7d7';ctx.fillRect(0,0,640,400);
  ctx.fillStyle='#232b32';ctx.font='24px sans-serif';ctx.fillText('SYNTHETIC TEST DOCUMENT',40,60);
  ctx.fillStyle='#b8afa0';ctx.fillRect(40,100,140,180);
  for(let row=0;row<7;row++){ctx.fillStyle=row===3?'#a25636':'#746e63';ctx.fillRect(220,105+row*26,200+(row%3)*35,8);}
  ctx.fillStyle='#303738';for(let y=0;y<8;y++)for(let x=0;x<8;x++)if((x*y+x+y)%3)ctx.fillRect(500+x*10,280+y*10,8,8);
  return canvas;
};
window.__attach = async (index=0, count=1, type='image/png') => {
  const canvas=window.__sample();
  const blob=await new Promise(resolve=>canvas.toBlob(resolve,type));
  const dt=new DataTransfer();for(let i=0;i<count;i++)dt.items.add(new File([blob],`synthetic-${i}.png`,{type}));
  const input=document.querySelectorAll('input[type=file]')[index];
  if(!input)throw Error('Missing upload input '+index);
  input.files=dt.files;input.dispatchEvent(new Event('change',{bubbles:true}));
};
class TestXHR {
  upload={};
  open(method,url){this.url=url;}
  send(form){
    window.__requests.push({url:this.url,fields:[...form.keys()],challenge:form.get('challenge'),frames:form.getAll('frames').length});
    setTimeout(()=>this.upload.onload?.(),10);
    setTimeout(()=>{
      const png=window.__sample().toDataURL('image/png').split(',')[1];
      this.status=window.__status;
      const face=this.url.endsWith('/face');
      const details=face ? {face:{compared:true,is_match:true,distance:0.21,similarity:0.79,threshold:0.68,model:'ArcFace'},liveness:{checked:true,passed:true,challenge:'blink',detail:{}}} : {maps:{noise_map_png_base64:png,spectrum_png_base64:png},ela:{applicable:true,flagged_fraction:0.03,heatmap_png_base64:png,flagged_blocks:[]}};
      this.responseText=JSON.stringify(this.status===200 ? {record_id:'synthetic-ui-check',verdict:'UNVERIFIABLE',headline:'Not independently verifiable',decided_by:null,identity_binding:face?'BOUND':'NOT_ATTEMPTED',reasons:[],advisory:[],details,disclaimer} : {detail:'Synthetic service failure. Please try again.'});
      this.onload?.();
    },window.__responseDelay);
  }
}
window.XMLHttpRequest=TestXHR;
if(navigator.mediaDevices) navigator.mediaDevices.getUserMedia=async()=>{
  if(window.__cameraDenied)throw new DOMException('Permission denied','NotAllowedError');
  const canvas=window.__sample();const stream=canvas.captureStream(15);
  // A changing source makes video playback advance in headless browsers.
  const timer=setInterval(()=>canvas.getContext('2d').fillRect(0,0,1,1),66);
  for(const track of stream.getTracks()){
    const stop=track.stop.bind(track);track.stop=()=>{window.__stoppedTracks++;clearInterval(timer);stop();};
  }
  if(window.__cameraDelay)await new Promise(resolve=>setTimeout(resolve,window.__cameraDelay));
  return stream;
};
"""


def click(browser, pattern):
    import json
    result = browser.js(f"""
      const node=[...document.querySelectorAll('button')].find(b=>new RegExp({json.dumps(pattern)},'i').test(b.innerText));
      if(!node)return false;node.scrollIntoView({{block:'center'}});node.click();return true;
    """, settle=0.15)
    assert result, f"Missing button: {pattern}"


def wait_for(browser, expression, timeout=12):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if browser.js(f"return Boolean({expression});"):
            return
        time.sleep(0.15)
    state = browser.js("return {errors:window.__errors,camera:document.querySelector('.camera-stage')?.className,videoWidth:document.querySelector('video')?.videoWidth,ticks:document.querySelectorAll('.is-filled').length,text:document.body.innerText.slice(-600)};")
    raise AssertionError(f"Timed out: {expression}; {state}")


def main():
    out = Path('demo_data/ui-review')
    browser = Chrome(1440, 1000)
    try:
        browser.send('Page.addScriptToEvaluateOnNewDocument', source=MOCKS)
        browser.navigate('http://localhost:3000', settle=2)
        browser.shoot(out / 'after-home.png')
        assert browser.js("return Boolean(document.querySelector('.app-header'));"), 'Frontend server must be running on localhost:3000'
        assert browser.js('return document.documentElement.scrollWidth <= innerWidth;')
        assert browser.js('return window.__errors;') == []
        print('PASS: desktop home, no overflow or runtime errors')

        click(browser, '^Run sample scan$')
        wait_for(browser, "document.querySelector('.synthetic-scan.is-scanning')")
        browser.shoot(out / 'home-scanning.png')
        click(browser, '^Verify$')
        click(browser, 'Start with PAN')
        browser.js('await window.__attach(); window.__responseDelay=4000;')
        click(browser, '^Run check$')
        wait_for(browser, "document.querySelector('.scan-preview__analysis.is-ready')")
        assert browser.js("return getComputedStyle(document.querySelector('.scan-preview__analysis')).animationName === 'field-reveal';")
        browser.shoot(out / 'document-scanning.png')
        click(browser, '^Show original$')
        assert browser.js("return getComputedStyle(document.querySelector('.scan-preview__analysis')).visibility === 'hidden';")
        wait_for(browser, "document.querySelector('.result-view')")
        assert browser.js("return document.querySelector('.forensic-maps')?.getBoundingClientRect().height > 0;")
        click(browser, '^Frequency spectrum$')
        assert browser.js("return document.querySelector('.forensic-maps img').alt.includes('frequency');")
        browser.shoot(out / 'document-result.png')
        browser.js('window.__responseDelay=100;')
        click(browser, '^Check another document$')
        click(browser, 'Start with PAN')
        browser.js('await window.__attach(); window.__status=503;')
        click(browser, '^Run check$')
        wait_for(browser, "document.body.innerText.includes('Synthetic service failure')")
        browser.js('window.__status=200;')
        click(browser, '^Run check$')
        wait_for(browser, "document.querySelector('.result-view')")
        print('PASS: animated image-derived heatmap, original toggle, visible server maps and error retry')

        click(browser, '^Check another document$')
        click(browser, 'Start with Passport')
        assert browser.js("return document.body.innerText.includes('Passport data page');")
        browser.js('await window.__attach(); window.__responseDelay=100;')
        click(browser, '^Run check$')
        wait_for(browser, "document.querySelector('.result-view')")
        assert browser.js("return window.__requests.at(-1).url.endsWith('/verify/passport');")
        print('PASS: passport picker, upload form, and API submission')

        click(browser, '^Face check$')
        wait_for(browser, "document.querySelector('.face-capture')")
        browser.js('await window.__attach();')
        browser.shoot(out / 'face-form.png')
        browser.js('window.__cameraDenied=true;')
        click(browser, '^Open camera$')
        wait_for(browser, "document.querySelector('[role=alert]')")
        assert browser.js('return window.__stoppedTracks;') == 0
        browser.js('window.__cameraDenied=false;window.__cameraDelay=500;')
        click(browser, '^Open camera$')
        click(browser, '^Cancel camera$')
        wait_for(browser, "window.__stoppedTracks === 1")
        browser.js('window.__cameraDelay=0;')
        click(browser, '^Open camera$')
        wait_for(browser, "document.querySelector('.camera-stage--ready')")
        click(browser, '^Begin .*capture$')
        wait_for(browser, "document.body.innerText.includes('Sequence captured')", timeout=35)
        assert browser.js('return window.__stoppedTracks;') == 2
        browser.js("document.querySelectorAll('input[name=face-challenge]')[1].click();", settle=.2)
        assert browser.js("return !document.body.innerText.includes('Sequence captured');")
        click(browser, '^Open camera$')
        wait_for(browser, "document.querySelector('.camera-stage--ready')")
        click(browser, '^Begin .*capture$')
        wait_for(browser, "document.body.innerText.includes('Sequence captured')", timeout=35)
        browser.js("""
          const input=document.querySelector('#face-consent-subject');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'synthetic-subject');
          input.dispatchEvent(new Event('input',{bubbles:true}));
        """)
        click(browser, '^Compare face$')
        wait_for(browser, "document.querySelector('.result-view')")
        assert browser.js("return document.querySelector('.face-evidence')?.innerText.includes('Unavailable');")
        assert browser.js("return window.__requests.at(-1).url.endsWith('/verify/face');")
        assert browser.js('return window.__requests.at(-1).frames >= 20;')
        assert browser.js("return window.__requests.at(-1).challenge === 'head_turn';")
        browser.shoot(out / 'face-result.png')
        assert browser.js('return window.__errors;') == []
        print('PASS: camera denial/retry, pending cancel cleanup, challenge reset, 20+ frames, face submission/result')

        click(browser, '^Dashboard$')
        wait_for(browser, "document.body.innerText.includes('No checks recorded yet.')")
        browser.js("""
          window.__history=[{id:'sample-pan',created_at:'2026-09-09T12:00:00Z',doc_type:'pan',qr_version:null,
            verdict:'UNVERIFIABLE',decided_by:null,binding:'NOT_ATTEMPTED',reason_codes:['PAN_FORMAT_OK'],advisory_codes:[],face_distance:null,liveness:null}];
        """)
        click(browser, '^Refresh$')
        wait_for(browser, "document.querySelector('.dashboard-filters')")
        browser.js("""
          const input=document.querySelector('input[type=search]');
          Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'no matching document');
          input.dispatchEvent(new Event('input',{bubbles:true}));
        """, settle=.2)
        assert browser.js("return document.body.innerText.includes('No checks match');")
        click(browser, '^Clear filters$')
        assert browser.js("return document.querySelectorAll('.dashboard-table tbody tr').length === 1;")
        browser.shoot(out / 'dashboard.png')
        print('PASS: empty dashboard, refresh, history search and filter reset')

        browser.send('Emulation.setDeviceMetricsOverride', width=390, height=844, deviceScaleFactor=1, mobile=True)
        click(browser, '^Home$')
        browser.shoot(out / 'mobile-home.png')
        assert browser.js('return document.documentElement.scrollWidth <= innerWidth;')
        click(browser, '^Face check$')
        browser.shoot(out / 'mobile-face.png')
        assert browser.js('return document.documentElement.scrollWidth <= innerWidth;')
        browser.send('Emulation.setEmulatedMedia', features=[{'name':'prefers-reduced-motion','value':'reduce'}])
        click(browser, '^Home$')
        click(browser, '^Run sample scan$')
        assert browser.js("return !document.querySelector('.synthetic-scan.is-scanning');")
        assert browser.js('return window.__errors;') == []
        print('PASS: mobile home/face layouts and reduced motion; no runtime errors')
    finally:
        browser.close()


if __name__ == '__main__':
    main()
