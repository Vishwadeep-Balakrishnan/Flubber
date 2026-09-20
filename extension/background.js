// Service worker: owns saved panel state and talks to the local companion over HTTP.
importScripts('state.js');
const App = globalThis.FlubberState;
const BASE = 'http://127.0.0.1:8765';
let queue = Promise.resolve();

async function api(path, code, method='GET', body, timeout=5000) {
  let response;
  try {
    response = await fetch(BASE + path, {
      method, cache:'no-store', credentials:'omit', referrerPolicy:'no-referrer',
      headers:{Authorization:'Bearer '+code, ...(body ? {'Content-Type':'application/json'} : {})},
      body:body ? JSON.stringify(body) : undefined,
      signal:AbortSignal.timeout(timeout)
    });
  } catch {
    throw new Error('The companion is offline. Start it on this computer, then reconnect.');
  }
  let data;
  try {data=await response.json();} catch {throw new Error('The local companion returned an invalid response.');}
  if(!response.ok)throw new Error(data.error || `Companion error ${response.status}.`);
  return data;
}

async function load() {
  const saved = await chrome.storage.local.get([App.KEY,App.PAIR_KEY]);
  const state = App.normalize(saved[App.KEY]);
  const code = saved[App.PAIR_KEY] || '';
  state.paired=Boolean(code);
  return {state,code};
}

async function save(state) {
  const existing = (await chrome.storage.local.get(App.KEY))[App.KEY];
  if(JSON.stringify(existing)!==JSON.stringify(state))await chrome.storage.local.set({[App.KEY]:state});
  return state;
}

// Apply a companion snapshot (from polling or the live WebSocket).
function applySnapshot(state, snapshot) {
  state=App.merge(state,snapshot);state.connected=true;state.connectionMessage='';
  if(state.current && state.current.id===state.dismissed && !App.ACTIVE.includes(state.current.status))state.current=null;
  return state;
}

// Mark the exact starting tab so the companion can find it even if two tabs share a URL.
async function marker(windowId) {
  const query={active:true,...(Number.isInteger(windowId)?{windowId}:{lastFocusedWindow:true})};
  const [tab]=await chrome.tabs.query(query);
  if(!tab?.id || !/^https?:\/\//i.test(tab.url || ''))throw new Error('Open a normal website and click Flubber’s toolbar icon on that page first.');
  const token=crypto.randomUUID();
  try {
    await chrome.scripting.executeScript({
      target:{tabId:tab.id},world:'MAIN',injectImmediately:true,
      func:value=>document.documentElement.setAttribute('data-flubber-tab',value),args:[token]
    });
  } catch {throw new Error('Click Flubber’s toolbar icon on this page once, then send the task again.');}
  return {url:tab.url,token};
}

async function handle(action) {
  let {state,code}=await load();
  const running=state.current && App.ACTIVE.includes(state.current.status);
  switch(action.type) {
    case 'pair': {
      const candidate=String(action.code || '').trim();
      if(candidate.startsWith('sk-'))throw new Error('Use the pairing code from the companion terminal, not your OpenAI API key.');
      if(candidate.length<32 || candidate.length>128)throw new Error('Paste the pairing code printed by the companion.');
      const health=await api('/v1/health',candidate);
      await chrome.storage.local.set({[App.PAIR_KEY]:candidate});
      code=candidate; state.paired=true;state.connected=true;state.keyConfigured=health.key_configured;
      state.connectionMessage=health.key_configured ? '' : 'Add your OpenAI key locally and restart the companion.';
      state=App.merge(state,await api('/v1/tasks',code));
      return save(state);
    }
    case 'draft': state.draft=String(action.value || '').slice(0,6000);return save(state);
    case 'view': state.view=action.value==='history'?'history':'task';return save(state);
    case 'reset':
      if(running)throw new Error('Stop the current task first.');
      state.dismissed=state.current?.id || state.dismissed || null;
      state.current=null;state.draft='';state.view='task';
      return save(state);
    case 'reuse':
      if(running)throw new Error('Stop the current task before reusing another.');
      state.dismissed=state.current?.id || state.dismissed || null;
      state.draft=String(action.value || '').slice(0,6000);state.current=null;state.view='task';
      return save(state);
    case 'start': {
      if(!code)throw new Error('Connect Flubber using the plug button at the top first.');
      const command=String(action.command || '').trim();
      if(!command)throw new Error('Type or say a task first.');
      const source=await marker(action.windowId);
      const run=await api('/v1/tasks',code,'POST',{command,source,request_id:action.requestId});
      state.current=run;state.draft='';state.view='task';state.connected=true;state.keyConfigured=true;state.dismissed=null;
      return save(state);
    }
    case 'update': {
      if(!running)throw new Error('This task has ended. Start a new task instead.');
      const text=String(action.text || '').trim();if(!text)throw new Error('Type your update first.');
      state.current=await api(`/v1/tasks/${encodeURIComponent(state.current.id)}/update`,code,'POST',{text});
      state.draft='';state.view='task';return save(state);
    }
    case 'stop':
      if(!running)return state;
      state.current=await api(`/v1/tasks/${encodeURIComponent(state.current.id)}/stop`,code,'POST',{});
      return save(state);
    case 'snapshot':
      if(!code || !action.data || typeof action.data!=='object')return state;
      return save(applySnapshot(state,action.data));
    case 'get':
      if(!code){state.connected=false;return state;}
      try {
        if(!state.connected || !state.keyConfigured){
          const health=await api('/v1/health',code);state.keyConfigured=health.key_configured;
        }
        state=applySnapshot(state,await api('/v1/tasks',code));
      } catch(error){state.connected=false;state.connectionMessage=error.message;}
      return save(state);
    default: throw new Error('Unknown Flubber request.');
  }
}

// A short-lived OpenAI Realtime key for one voice session. The real API key stays in the companion.
async function voiceKey() {
  const {code}=await load();
  if(!code)throw new Error('Connect Flubber using the plug button at the top first.');
  return (await api('/v1/voice',code,'POST',{},20000)).key;
}

chrome.runtime.onInstalled.addListener(()=>{
  chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(console.error);
  chrome.storage.local.setAccessLevel({accessLevel:'TRUSTED_CONTEXTS'}).catch(console.error);
});
chrome.runtime.onStartup.addListener(()=>chrome.sidePanel.setPanelBehavior({openPanelOnActionClick:true}).catch(console.error));
chrome.runtime.onMessage.addListener((message,sender,sendResponse)=>{
  if(sender.id!==chrome.runtime.id || message?.channel!=='flubber')return;
  const action=message.action || {};
  if(action.type==='voice'){
    voiceKey().then(key=>sendResponse({ok:true,key}),error=>sendResponse({ok:false,error:error.message}));
    return true;
  }
  const job=queue.then(()=>handle(action));queue=job.catch(()=>{});
  job.then(state=>sendResponse({ok:true,state}),error=>sendResponse({ok:false,error:error.message}));
  return true;
});
