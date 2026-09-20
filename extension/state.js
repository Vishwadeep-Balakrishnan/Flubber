(() => {
  'use strict';
  const KEY = 'flubber.app.v2';
  const PAIR_KEY = 'flubber.pairing.v1';
  const ACTIVE = ['queued','connecting','running','waiting','stopping'];
  const initial = () => ({draft:'',view:'task',current:null,history:[],paired:false,connected:false,keyConfigured:false,connectionMessage:''});
  function validRun(run) {
    return run && typeof run.id === 'string' && typeof run.command === 'string'
      && typeof run.status === 'string' && Number.isFinite(run.startedAt);
  }
  function normalize(raw) {
    const state = {...initial(), ...(raw && typeof raw === 'object' ? raw : {})};
    state.draft = typeof state.draft === 'string' ? state.draft.slice(0,6000) : '';
    state.view = state.view === 'history' ? 'history' : 'task';
    state.current = validRun(state.current) ? state.current : null;
    state.history = (Array.isArray(state.history) ? state.history : []).filter(validRun).slice(0,100);
    return state;
  }
  function merge(state, snapshot) {
    state = normalize(state);
    state.current = validRun(snapshot.current) ? snapshot.current : null;
    const merged = new Map();
    for (const run of [...(snapshot.history || []), ...state.history]) {
      if (validRun(run) && !merged.has(run.id)) merged.set(run.id,run);
    }
    state.history = [...merged.values()].sort((a,b)=>b.startedAt-a.startedAt).slice(0,100);
    return state;
  }
  const api = {KEY,PAIR_KEY,ACTIVE,initial,normalize,merge};
  globalThis.FlubberState = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})();
