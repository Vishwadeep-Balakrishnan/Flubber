const test=require('node:test'),assert=require('node:assert/strict');
const {worker}=require('./worker.cjs');
test('toolbar setup and local draft do not require a companion',async()=>{
 const w=worker();await w.hooks.install();assert.equal(w.hooks.behavior.openPanelOnActionClick,true);
 assert.equal((await w.send({type:'get'})).state.paired,false);
 await w.send({type:'draft',value:'A draft'});assert.equal((await w.send({type:'get'})).state.draft,'A draft');
});
test('rejects an OpenAI key in the pairing dialog without saving it',async()=>{
 const w=worker();const r=await w.send({type:'pair',code:'sk-not-a-real-key-'.repeat(3)});
 assert.equal(r.ok,false);assert.match(r.error,/not your OpenAI/);
 assert.equal(w.remote.calls.length,0);assert.equal(Object.keys(w.data).length,0);
});
test('pairs, marks the exact tab, and starts a real task request',async()=>{
 const w=worker();assert.equal((await w.send({type:'pair',code:w.remote.code})).ok,true);
 const r=await w.send({type:'start',command:'Find my invoice',requestId:'one',windowId:55});
 assert.equal(r.state.current.status,'running');assert.equal(w.scripts[0].target.tabId,7);
 const call=w.remote.calls.find(x=>x.options.method==='POST');
 const body=JSON.parse(call.options.body);assert.equal(body.source.url,'https://example.test/account');assert.match(body.source.token,/^[a-f0-9-]{36}$/);
});
test('typed updates retain the task identity and Stop comes from the companion',async()=>{
 const w=worker();await w.send({type:'pair',code:w.remote.code});
 const before=await w.send({type:'start',command:'Fill the form',requestId:'one'});
 const updated=await w.send({type:'update',text:'Use Weekly instead'});
 assert.equal(updated.state.current.id,before.state.current.id);assert.equal(updated.state.draft,'');
 assert.equal(updated.state.current.updates[0],'Use Weekly instead');
 assert.equal((await w.send({type:'stop'})).state.current.status,'stopped');
});
test('does not pretend to stop when the companion is unreachable',async()=>{
 const w=worker();await w.send({type:'pair',code:w.remote.code});await w.send({type:'start',command:'Do a task',requestId:'one'});
 w.remote.online=false;assert.equal((await w.send({type:'stop'})).ok,false);
 const snapshot=await w.send({type:'get'});assert.equal(snapshot.state.connected,false);assert.equal(snapshot.state.current.status,'running');
});
test('completed task is recorded and reset remains dismissed across polling',async()=>{
 const w=worker();await w.send({type:'pair',code:w.remote.code});await w.send({type:'start',command:'A task',requestId:'one'});
 w.remote.current.status='completed';w.remote.current.result='Saved on the page';w.remote.history=[structuredClone(w.remote.current)];
 assert.equal((await w.send({type:'get'})).state.history.length,1);
 await w.send({type:'reset'});assert.equal((await w.send({type:'get'})).state.current,null);
 const reuse=await w.send({type:'reuse',value:'Again'});assert.equal(reuse.state.draft,'Again');assert.equal(reuse.state.current,null);
});
test('rejects start before pairing and recovers after a companion restart',async()=>{
 const w=worker();assert.equal((await w.send({type:'start',command:'No pair',requestId:'one'})).ok,false);
 await w.send({type:'pair',code:w.remote.code});w.remote.online=false;await w.send({type:'get'});
 w.remote.online=true;assert.equal((await w.send({type:'get'})).state.connected,true);
});
test('voice returns only a short-lived key and requires pairing',async()=>{
 const w=worker();assert.equal((await w.send({type:'voice'})).ok,false);
 await w.send({type:'pair',code:w.remote.code});
 const r=await w.send({type:'voice'});assert.equal(r.ok,true);assert.equal(r.key,'ek_test_ephemeral');
});
test('live snapshots pushed over the WebSocket update saved state',async()=>{
 const w=worker();await w.send({type:'pair',code:w.remote.code});await w.send({type:'start',command:'Fill it',requestId:'one'});
 const pushed={...w.remote.current,status:'running',message:'Entering text',steps:2,events:[{label:'Entering text',at:Date.now()}]};
 const r=await w.send({type:'snapshot',data:{current:pushed,history:[]}});
 assert.equal(r.state.current.message,'Entering text');assert.equal(r.state.connected,true);
 assert.equal((await w.send({type:'snapshot',data:null})).state.current.steps,2);
});
