const vm=require('node:vm'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const base=path.resolve(__dirname,'..');
function worker(){
 const data={},hooks={},scripts=[];
 const remote={online:true,code:'a'.repeat(43),key:true,current:null,history:[],calls:[]};
 async function fetch(url,options={}){
  if(!remote.online)throw Error('offline');
  const endpoint=new URL(url).pathname;remote.calls.push({endpoint,options});
  const response=(body,status=200)=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json'}});
  if(options.headers.Authorization!=='Bearer '+remote.code)return response({error:'Pairing code rejected.'},401);
  if(endpoint==='/v1/health')return response({ok:true,key_configured:remote.key,model:'gpt-6-luna'});
  if(endpoint==='/v1/tasks' && options.method==='GET')return response({current:remote.current,history:remote.history});
  if(endpoint==='/v1/tasks' && options.method==='POST'){
   const body=JSON.parse(options.body);
   if(!remote.key)return response({error:'Add your OpenAI API key locally.'},503);
   if(remote.current && ['queued','running','waiting','connecting','stopping'].includes(remote.current.status))return response({error:'Task already running'},409);
   remote.current={id:crypto.randomUUID(),request_id:body.request_id,command:body.command,site:'example.test',status:'running',message:'Working on the page',startedAt:Date.now(),steps:0,events:[],updates:[],result:''};
   return response(remote.current,202);
  }
  if(endpoint==='/v1/voice' && options.method==='POST')return response({key:'ek_test_ephemeral',model:'gpt-live-transcribe'});
  if(endpoint.endsWith('/update')){remote.current.updates.push(JSON.parse(options.body).text);remote.current.message='Applying your update';return response(remote.current,202);}
  if(endpoint.endsWith('/stop')){remote.current.status='stopped';remote.current.result='Task stopped';remote.history=[structuredClone(remote.current)];return response(remote.current,202);}
  return response({error:'Unknown route'},404);
 }
 const chrome={runtime:{id:'a'.repeat(32),onInstalled:{addListener:fn=>hooks.install=fn},onStartup:{addListener:fn=>hooks.startup=fn},onMessage:{addListener:fn=>hooks.message=fn}},
  sidePanel:{setPanelBehavior:async x=>{hooks.behavior=x;}},
  storage:{local:{get:async keys=>Object.fromEntries((Array.isArray(keys)?keys:[keys]).map(k=>[k,structuredClone(data[k])])),set:async values=>Object.assign(data,structuredClone(values)),setAccessLevel:async()=>{}}},
  tabs:{query:async()=>[{id:7,url:'https://example.test/account',active:true}]},
  scripting:{executeScript:async value=>{scripts.push(value);return [{}];}}};
 const sandbox={chrome,crypto,fetch,AbortSignal,console,URL,Response};vm.createContext(sandbox);
 sandbox.importScripts=name=>vm.runInContext(fs.readFileSync(path.join(base,name),'utf8'),sandbox);
 vm.runInContext(fs.readFileSync(path.join(base,'background.js'),'utf8'),sandbox);
 const send=action=>new Promise(resolve=>hooks.message({channel:'flubber',action},{id:chrome.runtime.id},result=>resolve(structuredClone(result))));
 return {remote,data,hooks,scripts,send,chrome};
}
module.exports={worker};
