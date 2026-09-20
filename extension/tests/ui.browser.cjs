/* Optional real DOM/layout check. Requires Playwright; no API key is used. */
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),os=require('node:os');
const playwright=require('playwright');
const {worker}=require('./worker.cjs');
const base=path.resolve(__dirname,'..');
async function main(){
 const w=worker(),errors=[],closed=[];
 const browser=await playwright.chromium.launch({headless:true,...(process.env.FLUBBER_TEST_BROWSER?{executablePath:process.env.FLUBBER_TEST_BROWSER}:{}),args:['--no-sandbox','--disable-dev-shm-usage']});
 try{
  const context=await browser.newContext({viewport:{width:380,height:820},deviceScaleFactor:2});
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.exposeFunction('flubberMessage',message=>w.send(message.action));
  await page.exposeFunction('flubberClose',value=>closed.push(value));
  await page.addInitScript(()=>{
   window.__tabs=[];
   window.chrome={runtime:{id:'a'.repeat(32),sendMessage:message=>window.flubberMessage(message),getURL:p=>'chrome-extension://test/'+p},
    windows:{getCurrent:async()=>({id:55})},sidePanel:{close:value=>window.flubberClose(value)},
    tabs:{query:async()=>[{id:7,url:'https://example.test/account',active:true}],create:async v=>{window.__tabs.push(v.url);},onActivated:{addListener(){}},onUpdated:{addListener(){}}}};
   // Fake microphone (denied once, then allowed), WebRTC, and OpenAI Realtime transcription events.
   let denied=true;const track={enabled:true,stop(){}};
   Object.defineProperty(navigator,'mediaDevices',{value:{getUserMedia:async()=>{if(denied){denied=false;throw new DOMException('denied','NotAllowedError');}return {getTracks:()=>[track]};}}});
   class FakeChannel{send(raw){window.__sent=(window.__sent||[]).concat(JSON.parse(raw).type);if(JSON.parse(raw).type==='input_audio_buffer.commit')setTimeout(()=>{
     this.onmessage({data:JSON.stringify({type:'conversation.item.input_audio_transcription.delta',item_id:'i1',delta:'Use the second '})});
     this.onmessage({data:JSON.stringify({type:'conversation.item.input_audio_transcription.completed',item_id:'i1',transcript:'Use the second invoice instead.'})});},20);}close(){}}
   window.RTCPeerConnection=class{addTrack(){}createDataChannel(name){window.__channel=name;this.ch=new FakeChannel();return this.ch;}
     async createOffer(){return {type:'offer',sdp:'v=0 offer'};}async setLocalDescription(){}async setRemoteDescription(){setTimeout(()=>this.ch.onopen?.(),10);}close(){}};
   const realFetch=window.fetch.bind(window);
   window.fetch=async(url,options)=>{if(String(url).startsWith('https://api.openai.com/')){window.__realtime={url:String(url),auth:options.headers.Authorization,type:options.headers['Content-Type']};return new Response('v=0 answer',{status:201});}return realFetch(url,options);};
  });
  await page.goto('file://'+path.join(base,'sidepanel.html'));
  await page.locator('#task-input').waitFor({state:'visible'});
  await page.waitForFunction(()=>!document.getElementById('task-input').disabled);
  assert.equal(await page.locator('#send-button').isDisabled(),true);
  await page.locator('#task-input').fill('Find my latest invoice.');
  await page.locator('#send-button').click();
  assert.equal(await page.locator('#connection-dialog').evaluate(el=>el.open),true);
  await page.locator('#pairing-code').fill('sk-not-a-real-key-'.repeat(3));await page.locator('#connect-submit').click();
  await page.waitForFunction(()=>!document.getElementById('pairing-error').hidden);
  assert.match(await page.locator('#pairing-error').textContent(),/not your OpenAI/);
  await page.locator('#pairing-code').fill(w.remote.code);await page.locator('#connect-submit').click();
  await page.waitForFunction(()=>!document.getElementById('connection-dialog').open);
  await page.locator('#send-button').click();
  await page.waitForFunction(()=>document.getElementById('flubber').dataset.state==='running');
  assert.equal(await page.locator('#task-input').isEnabled(),true);
  await page.locator('#task-input').fill('Use the invoice from September instead.');await page.locator('#send-button').click();
  await page.waitForFunction(()=>document.getElementById('last-update').textContent.includes('September'));
  assert.equal(w.remote.current.updates.length,1);
  // Voice: first tap asks for mic permission in a tab, second tap listens, third tap sends a spoken correction.
  await page.locator('#mic-button').click();
  await page.waitForFunction(()=>!document.getElementById('panel-error').hidden);
  assert.match(await page.locator('#panel-error').textContent(),/Allow the microphone/);
  assert.deepEqual(await page.evaluate(()=>window.__tabs),['chrome-extension://test/permission.html']);
  await page.locator('#mic-button').click();
  await page.waitForFunction(()=>document.getElementById('flubber').dataset.state==='listening');
  const realtime=await page.evaluate(()=>window.__realtime);
  assert.equal(realtime.url,'https://api.openai.com/v1/realtime/calls');assert.equal(realtime.auth,'Bearer ek_test_ephemeral');assert.equal(realtime.type,'application/sdp');
  assert.equal(await page.evaluate(()=>window.__channel),'oai-events');
  await page.locator('#mic-button').click();
  await page.waitForFunction(()=>document.getElementById('last-update').textContent.includes('second invoice'));
  assert.deepEqual(w.remote.current.updates,['Use the invoice from September instead.','Use the second invoice instead.']);
  assert.equal(await page.locator('#mic-caption').textContent(),'Tap to talk');
  await page.locator('#stop-button').click();await page.waitForFunction(()=>document.getElementById('flubber').dataset.state==='stopped');
  await page.evaluate(()=>{document.getElementById('panel-error').hidden=true;});
  await page.locator('#history-tab').click();await page.locator('.history-row').waitFor();
  await page.locator('.history-row').first().click();await page.waitForFunction(()=>!document.getElementById('task-view').hidden);
  assert.equal(await page.locator('#task-input').inputValue(),'Find my latest invoice.');
  await page.locator('#send-button').click();await page.waitForFunction(()=>document.getElementById('flubber').dataset.state==='running');
  w.remote.current.status='completed';w.remote.current.result='<img src=x onerror=alert(1)> Saved, verified on page.';w.remote.current.steps=4;
  w.remote.current.events=[{label:'Entering text',at:Date.now()},{label:'Clicking a page control',at:Date.now()}];w.remote.history=[structuredClone(w.remote.current),...w.remote.history];
  await page.waitForFunction(()=>document.getElementById('flubber').dataset.state==='done');
  assert.equal(await page.locator('#task-result img').count(),0);
  assert.match(await page.locator('#task-result').textContent(),/<img src=x/);
  await page.locator('#new-task').click();await page.waitForFunction(()=>document.getElementById('task-input').value==='');
  await page.waitForTimeout(1400);assert.equal(await page.locator('#flubber').getAttribute('data-state'),'idle');
  const out=process.env.FLUBBER_TEST_OUTPUT || fs.mkdtempSync(path.join(os.tmpdir(),'flubber-ui-'));
  fs.mkdirSync(out,{recursive:true});
  await page.screenshot({path:path.join(out,'ready.png'),fullPage:true});
  for(const [width,height] of [[320,720],[380,820],[480,900]]){
   await page.setViewportSize({width,height});
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'horizontal overflow at '+width);
  }
  await page.setViewportSize({width:380,height:820});
  await page.locator('#task-input').fill('A saved draft.');await page.waitForTimeout(150);await page.reload();
  await page.waitForFunction(()=>!document.getElementById('task-input').disabled);assert.equal(await page.locator('#task-input').inputValue(),'A saved draft.');
  await page.locator('#close-panel').click();assert.equal(closed[0].windowId,55);
  assert.deepEqual(errors,[]);
  console.log('PASS: real DOM pairing, key rejection, task start, typed correction, voice permission + spoken correction, Stop, history reuse, literal results, reset/polling, draft restore, 320/380/480px layouts, and close control.');
  console.log('Internal QA screenshot:',path.join(out,'ready.png'));
 }finally{await browser.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
