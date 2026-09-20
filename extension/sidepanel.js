(() => {
  'use strict';
  const $=id=>document.getElementById(id), App=globalThis.FlubberState;
  const LIVE_URL='ws://127.0.0.1:8765/live', REALTIME_URL='https://api.openai.com/v1/realtime/calls';
  const input=$('task-input'), root=$('flubber');
  let app=null,ready=false,busy=false,sequence=0,applied=0,historyKey='',windowId=null;
  let connectionError='';
  const active=()=>app?.current && App.ACTIVE.includes(app.current.status);
  const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
  function error(error){$('panel-error').textContent=error.message || String(error);$('panel-error').hidden=false;}
  function clearError(){$('panel-error').hidden=true;}
  function say(text){$('voice-message').textContent=text;}
  async function send(action){
    if(!globalThis.chrome?.runtime?.id)throw new Error('Install Flubber in Chrome to use browser tasks. See README.md.');
    const result=await chrome.runtime.sendMessage({channel:'flubber',action});
    if(!result?.ok)throw new Error(result?.error || 'Reopen Flubber after reloading the extension.');
    return result;
  }
  async function request(action){
    const n=++sequence, result=await send(action);
    if(n>=applied){applied=n;render(result.state);}
    return result.state;
  }

  // ---------- Rendering ----------
  function composer(){
    input.disabled=!ready || busy;
    $('send-button').disabled=input.disabled || !input.value.trim() || app?.current?.status==='stopping';
    $('send-button').setAttribute('aria-label',active()?'Send task update':'Start task');
    $('composer-label').textContent=active()?'Update this task':'Or type a task';
    $('composer-hint').textContent=active()?'You can change your mind.':'Plain English works.';
    input.placeholder=active()?'Tell Flubber what to change...':'Cancel my subscription on this site...';
    $('mic-button').disabled=!ready || voice.stage==='connecting' || voice.stage==='transcribing';
  }
  function setView(view){
    for(const key of ['task','history']){
      const yes=key===view;$(key+'-view').hidden=!yes;$(key+'-tab').classList.toggle('active',yes);
      $(key+'-tab').setAttribute('aria-selected',String(yes));$(key+'-tab').tabIndex=yes?0:-1;
    }
  }
  function render(state){
    app=App.normalize(state);root.setAttribute('aria-busy','false');setView(app.view);
    const run=app.current, running=active(), status=run?.status || 'idle';
    root.dataset.state=voice.stage==='listening'?'listening':running?'running':status==='completed'?'done':status==='idle'?'idle':'stopped';
    const copy=status==='waiting'?['A little help?','Complete the step in Chrome, then reply below or by voice.']
      :running?['On it.','Follow along, or tap the mic to change the task.']
      :status==='completed'?['One less thing<br>to do.','Ready for whatever’s next.']
      :status==='failed'||status==='interrupted'?['Let’s take a look.','You can try again from the current page.']
      :status==='stopped'?['Back to you.','Pick it up whenever you’re ready.']
      :['What can I do<br>for you?','Tap the mic and say what you’d like done on this page.'];
    $('voice-title').innerHTML=copy[0];$('voice-subtitle').textContent=copy[1];
    $('status-title').textContent=running?(status==='waiting'?'Waiting for you':status==='stopping'?'Stopping...':run.message || 'Working on your task')
      :status==='completed'?'Task complete':status==='failed'?'Task needs attention':status==='interrupted'?'Task interrupted':status==='stopped'?'Task stopped':'Ready when you are';
    $('status-detail').textContent=run?(status==='waiting'?run.message:`${run.steps || 0} task steps`):'Your next task starts here.';
    $('stop-button').hidden=!running;$('stop-button').disabled=status==='stopping';
    $('new-task').hidden=!run || running;
    $('progress').setAttribute('aria-valuetext',running?run.message:status==='completed'?'Task complete':'Ready');
    if(running)$('progress').removeAttribute('aria-valuenow');else $('progress').setAttribute('aria-valuenow',status==='completed'?'100':'0');
    $('progress-fill').style.width=status==='completed'?'100%':running?'':'0%';
    const steps=(run?.events || []).slice(-3);const signature=JSON.stringify(steps);
    if($('task-steps').dataset.signature!==signature){
      $('task-steps').dataset.signature=signature;$('task-steps').replaceChildren();
      steps.forEach((event,index)=>{const li=document.createElement('li');li.textContent=event.label;li.className=running && index===steps.length-1?'current':'complete';$('task-steps').append(li);});
    }
    $('task-steps').hidden=!steps.length;
    $('task-result').hidden=!run?.result;$('task-result').textContent=run?.result || '';
    const update=run?.updates?.at(-1);$('last-update').hidden=!update;$('last-update').textContent=update?'Latest update: '+update:'';
    $('connection-dot').classList.toggle('connected',Boolean(app.connected));
    $('connect-button').setAttribute('aria-label',app.connected?'Flubber connected. Change connection':'Connect Flubber');
    $('connection-status').textContent=app.connected?(app.keyConfigured?'Companion connected · Browser actions are live':'Companion connected · Add your API key locally')
      :app.paired?'Companion offline · Start it to reconnect':'Connect Flubber to start browser tasks.';
    if(app.paired && !app.connected && app.connectionMessage){connectionError=app.connectionMessage;$('panel-error').textContent=connectionError;$('panel-error').hidden=false;}
    else if(connectionError){if($('panel-error').textContent===connectionError)$('panel-error').hidden=true;connectionError='';}
    if(run && running){$('page-title').textContent=run.site;}else context();
    composer();history(app.history);
  }
  function history(entries){
    const key=JSON.stringify(entries)+new Date().toDateString();if(key===historyKey)return;historyKey=key;
    const list=$('history-list');list.replaceChildren();
    if(!entries.length){
      const div=document.createElement('div');div.className='history-empty';
      const img=document.createElement('img');img.src='assets/mascot.png';img.alt='';
      const h=document.createElement('h2');h.textContent='A fresh start.';
      const p=document.createElement('p');p.textContent='Your tasks will appear here, ready to revisit.';
      div.append(img,h,p);list.append(div);return;
    }
    let previous='';
    entries.forEach(run=>{
      const date=new Date(run.startedAt),dateKey=date.toDateString();
      if(previous!==dateKey){previous=dateKey;const p=document.createElement('p');p.className='history-date';p.textContent=dateKey===new Date().toDateString()?'Today':date.toLocaleDateString(undefined,{month:'short',day:'numeric'});list.append(p);}
      const row=document.createElement('button');row.type='button';row.className='history-row';row.setAttribute('aria-label','Reuse task: '+run.command);
      const meta=document.createElement('span');meta.className='history-meta';const site=document.createElement('span');site.textContent=run.site || 'Browser tab';
      const time=document.createElement('span');time.textContent=date.toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});meta.append(site,time);
      const command=document.createElement('span');command.className='history-command';command.textContent=run.command;
      const result=document.createElement('span');result.className='history-result '+(run.status==='completed'?'':'stopped');
      result.textContent={completed:'Completed',stopped:'Stopped',failed:'Needs attention',interrupted:'Interrupted'}[run.status] || run.status;
      row.append(meta,command,result);
      if(run.result){const summary=document.createElement('span');summary.className='history-summary';summary.textContent=run.result;row.append(summary);}
      row.addEventListener('click',async()=>{
        try{
          if(active()){await request({type:'view',value:'task'});return;}
          busy=true;composer();const state=await request({type:'reuse',value:run.command});input.value=state.draft;
        }catch(e){error(e);}finally{busy=false;composer();input.focus();}
      });list.append(row);
    });
  }
  async function context(){
    if(!globalThis.chrome?.tabs)return;
    try{const [tab]=await chrome.tabs.query({active:true,currentWindow:true});if(!active())$('page-title').textContent=tab?.url?.startsWith('http')?new URL(tab.url).hostname:'This browser tab';}catch{}
  }

  // ---------- Tasks ----------
  async function submit(event){
    event?.preventDefault();if(!ready || busy || !input.value.trim())return;
    if(!app.paired){$('connection-dialog').showModal();return;}
    busy=true;composer();clearError();
    try{
      const text=input.value.trim();
      const state=await request(active()?{type:'update',text}:{type:'start',command:text,requestId:crypto.randomUUID(),windowId});
      input.value=state.draft;
    }catch(e){error(e);}finally{busy=false;composer();}
  }

  // ---------- Voice: push-to-talk over WebRTC to the OpenAI Realtime API ----------
  // Tap once to listen, tap again to send. The transcript starts a task, or corrects the running one.
  const voice={stage:'idle',pc:null,stream:null,channel:null,limit:null,finished:null};
  const STOP_WORDS=/^\s*(stop|cancel|stop it|stop the task|cancel the task|stop that)[\s.!]*$/i;
  function voiceStage(stage,caption){
    voice.stage=stage;$('mic-caption').textContent=caption;
    $('mic-button').setAttribute('aria-pressed',String(stage==='listening'));
    $('mic-button').setAttribute('aria-label',stage==='listening'?'Stop and send':'Start speaking');
    if(app)render(app);else composer();
  }
  function closeVoice(){
    clearTimeout(voice.limit);
    voice.stream?.getTracks().forEach(track=>track.stop());
    try{voice.channel?.close();}catch{}
    try{voice.pc?.close();}catch{}
    voice.pc=voice.stream=voice.channel=voice.finished=null;
    voiceStage('idle','Tap to talk');
  }
  async function microphone(){
    try{return await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});}
    catch(e){
      if(e?.name==='NotFoundError')throw new Error('No microphone was found. You can type the task instead.');
      // Side panels cannot show Chrome's permission prompt; ask once from a normal tab.
      await chrome.tabs.create({url:chrome.runtime.getURL('permission.html')});
      throw new Error('Allow the microphone in the tab that just opened, then tap the mic again.');
    }
  }
  async function startVoice(){
    if(!app?.paired){$('connection-dialog').showModal();return;}
    clearError();say('');voiceStage('connecting','Connecting…');
    try{
      voice.stream=await microphone();
      const {key}=await send({type:'voice'});
      const pc=voice.pc=new RTCPeerConnection();
      voice.stream.getTracks().forEach(track=>pc.addTrack(track,voice.stream));
      const channel=voice.channel=pc.createDataChannel('oai-events');
      let partial='';
      voice.finished=new Promise((resolve,reject)=>{
        channel.onmessage=message=>{
          let event;try{event=JSON.parse(message.data);}catch{return;}
          if(event.type==='conversation.item.input_audio_transcription.delta'){partial+=event.delta || '';say('“'+partial.trim()+'”');}
          else if(event.type==='conversation.item.input_audio_transcription.completed')resolve(event.transcript || partial);
          else if(event.type==='error'){
            if(event.error?.code==='input_audio_buffer_commit_empty')resolve('');
            else if(voice.stage==='transcribing')reject(new Error(event.error?.message || 'Voice transcription failed.'));
            else {closeVoice();error(new Error(event.error?.message || 'Voice session error.'));}
          }
        };
      });
      voice.finished.catch(()=>{});
      const opened=new Promise((resolve,reject)=>{channel.onopen=resolve;setTimeout(()=>reject(new Error('OpenAI voice did not connect. Try again.')),10000);});
      const offer=await pc.createOffer();await pc.setLocalDescription(offer);
      const response=await fetch(REALTIME_URL,{method:'POST',body:offer.sdp,headers:{Authorization:'Bearer '+key,'Content-Type':'application/sdp'}});
      if(!response.ok)throw new Error(`OpenAI voice connection failed (HTTP ${response.status}).`);
      await pc.setRemoteDescription({type:'answer',sdp:await response.text()});
      await opened;
      voiceStage('listening','Listening… tap to send');
      voice.limit=setTimeout(()=>finishVoice().catch(error),60000);
    }catch(e){closeVoice();error(e);}
  }
  async function finishVoice(){
    if(voice.stage!=='listening')return;
    voiceStage('transcribing','Getting that…');
    try{
      await sleep(350); // Let the last words reach OpenAI before committing the buffer.
      voice.channel.send(JSON.stringify({type:'input_audio_buffer.commit'}));
      voice.stream.getTracks().forEach(track=>{track.enabled=false;});
      const text=String(await Promise.race([voice.finished,sleep(15000).then(()=>{throw new Error('Voice transcription timed out. Try again.');})])).trim();
      closeVoice();
      if(!text){say('I didn’t catch that. Tap the mic and try again.');return;}
      say('“'+text+'”');
      if(active() && STOP_WORDS.test(text)){await request({type:'stop'});return;}
      input.value=text;composer();await submit();
    }catch(e){closeVoice();error(e);}
  }

  // ---------- Live progress: origin-checked WebSocket to the companion, polling as fallback ----------
  let socket=null,socketLive=false;
  async function connectLive(){
    if(socket || !app?.paired || document.hidden || !globalThis.chrome?.storage || typeof WebSocket!=='function')return;
    const code=(await chrome.storage.local.get(App.PAIR_KEY))[App.PAIR_KEY];
    if(!code || socket)return;
    const ws=socket=new WebSocket(LIVE_URL);
    ws.onopen=()=>ws.send(JSON.stringify({code}));
    ws.onmessage=message=>{
      socketLive=true;let data;try{data=JSON.parse(message.data);}catch{return;}
      request({type:'snapshot',data}).catch(error);
    };
    ws.onclose=()=>{if(socket===ws){socket=null;socketLive=false;}};
    ws.onerror=()=>{};
  }
  function dropLive(){if(socket){const ws=socket;socket=null;socketLive=false;ws.close();}}

  // ---------- Events ----------
  input.addEventListener('input',()=>{composer();request({type:'draft',value:input.value}).catch(error);});
  input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();submit();}});
  $('task-form').addEventListener('submit',submit);
  for(const name of ['task','history'])$(name+'-tab').addEventListener('click',()=>request({type:'view',value:name}).catch(error));
  document.querySelector('.brand').addEventListener('click',e=>{e.preventDefault();request({type:'view',value:'task'}).catch(error);});
  document.querySelector('.tabs').addEventListener('keydown',e=>{
    if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();
    const name=e.key==='Home'?'task':e.key==='End'?'history':app?.view==='task'?'history':'task';
    request({type:'view',value:name}).catch(error);$(name+'-tab').focus();
  });
  $('mic-button').addEventListener('click',()=>{(voice.stage==='listening'?finishVoice():startVoice()).catch(error);});
  $('stop-button').addEventListener('click',async()=>{clearError();try{await request({type:'stop'});}catch(e){error(e);}});
  $('new-task').addEventListener('click',async()=>{
    busy=true;composer();clearError();say('');try{const state=await request({type:'reset'});input.value=state.draft;}catch(e){error(e);}finally{busy=false;composer();input.focus();}
  });
  $('connect-button').addEventListener('click',()=>{$('pairing-error').hidden=true;$('connection-dialog').showModal();});
  $('close-connection').addEventListener('click',()=>$('connection-dialog').close());
  $('connection-form').addEventListener('submit',async e=>{
    e.preventDefault();$('connect-submit').disabled=true;$('pairing-error').hidden=true;
    try{await request({type:'pair',code:$('pairing-code').value});$('pairing-code').value='';$('connection-dialog').close();clearError();dropLive();connectLive().catch(()=>{});}
    catch(e){$('pairing-error').textContent=e.message;$('pairing-error').hidden=false;$('pairing-code').value='';}
    finally{$('connect-submit').disabled=false;}
  });
  $('close-panel').addEventListener('click',async()=>{
    try{closeVoice();await request({type:'draft',value:input.value});const w=await chrome.windows.getCurrent();await chrome.sidePanel.close({windowId:w.id});}catch(e){error(e);}
  });
  if(globalThis.chrome?.tabs?.onActivated){chrome.tabs.onActivated.addListener(context);chrome.tabs.onUpdated.addListener((id,change,tab)=>{if(tab.active&&change.url)context();});}
  // While the live socket is open the companion pushes every change; otherwise poll and try to reconnect.
  const poll=setInterval(()=>{
    if(!ready || document.hidden || socketLive)return;
    request({type:'get'}).then(()=>connectLive()).catch(error);
  },1200);
  window.addEventListener('pagehide',()=>{clearInterval(poll);dropLive();closeVoice();});
  if(globalThis.chrome?.windows)chrome.windows.getCurrent().then(w=>{windowId=w.id;}).catch(()=>{});
  request({type:'get'}).then(state=>{input.value=state.draft;ready=true;composer();connectLive().catch(()=>{});}).catch(error);
})();
