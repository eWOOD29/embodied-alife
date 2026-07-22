const worldCanvas = document.getElementById('worldCanvas');
const worldCtx = worldCanvas.getContext('2d');
const localCanvas = document.getElementById('localCanvas');
const localCtx = localCanvas.getContext('2d');
let staticTiles = null;
let state = null;
let activeKnowledgeTab = 'perception';
let updateStatus = null;
let updatePolling = null;

const terrainColors = {
  meadow: '#496f46', forest: '#244b31', dense_forest: '#153524',
  shallow_water: '#34748d', deep_water: '#1d4b68', rock: '#666b68',
  cave: '#221d28', build_area: '#8f7840'
};

async function apiRequest(path, options={}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || 'request failed');
  return data;
}

function showToast(text) {
  const el = document.getElementById('toast');
  el.textContent = text;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2600);
}

function renderUpdateStatus() {
  if (!updateStatus) return;
  const current = document.getElementById('currentVersion');
  const summary = document.getElementById('updateSummary');
  const install = document.getElementById('installUpdate');
  const badge = document.getElementById('updateBadge');
  const releaseLink = document.getElementById('releaseLink');
  const notes = document.getElementById('updateNotes');
  current.textContent = `v${updateStatus.current_version}`;
  install.hidden = !updateStatus.update_available;
  install.disabled = updateStatus.installing || updateStatus.state === 'downloading';
  install.textContent = updateStatus.installing ? 'Installing…' : `Install v${updateStatus.latest_version || ''}`;
  badge.hidden = !updateStatus.update_available;
  badge.textContent = updateStatus.update_available ? `Update v${updateStatus.latest_version}` : 'Update available';
  releaseLink.hidden = !updateStatus.release_url;
  if (updateStatus.release_url) releaseLink.href = updateStatus.release_url;
  notes.hidden = !updateStatus.release_notes;
  notes.textContent = updateStatus.release_notes || '';
  if (!updateStatus.enabled) summary.textContent = 'Automatic update checks are disabled.';
  else if (updateStatus.error) summary.textContent = `Update check failed: ${updateStatus.error}`;
  else if (updateStatus.installing) summary.textContent = 'The verified update is being installed. This page will reconnect after restart.';
  else if (updateStatus.update_available) summary.textContent = `${updateStatus.release_name || 'A new release'} is available from ${updateStatus.repository}.`;
  else if (updateStatus.latest_version) summary.textContent = `You are current. Latest stable release: v${updateStatus.latest_version}.`;
  else summary.textContent = `Configured repository: ${updateStatus.repository || 'not configured'}.`;
}

async function refreshUpdateStatus(check=false) {
  try {
    updateStatus = await apiRequest(check ? '/api/update/check' : '/api/update/status', {method: check ? 'POST' : 'GET'});
    renderUpdateStatus();
  } catch (error) {
    showToast(error.message);
  }
}

async function installAvailableUpdate() {
  if (!updateStatus?.update_available) return;
  const version = updateStatus.latest_version;
  if (!confirm(`Install Embodied Artificial Life v${version}? The app will stop briefly and restart automatically.`)) return;
  const button = document.getElementById('installUpdate');
  button.disabled = true;
  button.textContent = 'Verifying and staging…';
  try {
    const result = await apiRequest('/api/update/install', {
      method: 'POST',
      headers: {'Content-Type':'application/json', 'X-Embodied-Alife-Update':'confirm'},
      body: JSON.stringify({version})
    });
    showToast(result.message || 'Update installation started');
    updateStatus.installing = true;
    renderUpdateStatus();
    waitForRestart(version);
  } catch (error) {
    button.disabled = false;
    showToast(error.message);
    await refreshUpdateStatus(false);
  }
}

function waitForRestart(version) {
  if (updatePolling) clearInterval(updatePolling);
  let attempts = 0;
  updatePolling = setInterval(async () => {
    attempts += 1;
    try {
      const health = await fetch('/health', {cache:'no-store'});
      if (health.ok) {
        const payload = await health.json();
        if (payload.version === version) {
          clearInterval(updatePolling);
          location.reload();
        }
      }
    } catch (_) {}
    if (attempts > 180) {
      clearInterval(updatePolling);
      showToast('The update is taking longer than expected. Check data/runtime/update-worker.log.');
    }
  }, 2000);
}

function renderLlmSummary(configuration) {
  const status = configuration.status || {};
  const badge = document.getElementById('llmState');
  const summary = document.getElementById('llmSettingsSummary');
  badge.textContent = status.mode || (configuration.enabled ? 'configured' : 'disabled');
  badge.className = `pill ${status.mode === 'llm' && status.available ? 'ok' : status.last_error ? 'warning' : ''}`;
  if (!configuration.enabled) summary.textContent = 'Local LLM disabled; deterministic fallback brain is active.';
  else if (status.mode === 'llm' && status.available) summary.textContent = `Connected to ${status.model} at ${status.base_url}. Changes apply immediately.`;
  else if (status.last_error) summary.textContent = status.last_error;
  else summary.textContent = 'Choose a loaded model, then save and apply.';
  if (state && status) {
    state.model_status = status;
    document.getElementById('modelStatus').textContent = fmt(status);
  }
}

function fillLlmForm(configuration) {
  document.getElementById('llmEnabled').checked = configuration.enabled;
  document.getElementById('llmBaseUrl').value = configuration.base_url || 'http://127.0.0.1:1234/v1';
  document.getElementById('llmModel').value = configuration.model || '';
  document.getElementById('llmTemperature').value = configuration.temperature;
  document.getElementById('llmMaxTokens').value = configuration.max_tokens;
  document.getElementById('llmTimeout').value = configuration.timeout_seconds;
  document.getElementById('llmContext').value = configuration.context_length;
  document.getElementById('llmApiKey').value = '';
  document.getElementById('llmApiKey').placeholder = configuration.api_key_configured ? 'Configured; leave blank to preserve' : 'LM Studio does not require one by default';
  renderLlmSummary(configuration);
}

async function loadLlmSettings() {
  try {
    const configuration = await apiRequest('/api/llm/settings');
    fillLlmForm(configuration);
    await discoverModels(false);
  } catch (error) {
    document.getElementById('llmSettingsSummary').textContent = error.message;
  }
}

async function discoverModels(showMessage=true) {
  const button = document.getElementById('discoverModels');
  button.disabled = true;
  try {
    const apiKey = document.getElementById('llmApiKey').value.trim();
    const payload = {
      base_url: document.getElementById('llmBaseUrl').value.trim(),
      api_key: apiKey || null
    };
    const result = await apiRequest('/api/llm/models', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const datalist = document.getElementById('llmModelOptions');
    datalist.replaceChildren(...result.models.map(model => new Option(model, model)));
    const modelInput = document.getElementById('llmModel');
    if (!modelInput.value && result.models.length === 1) modelInput.value = result.models[0];
    document.getElementById('llmSettingsSummary').textContent = result.models.length
      ? `Found ${result.models.length} loaded model${result.models.length === 1 ? '' : 's'}.`
      : 'LM Studio responded, but no loaded models were returned.';
    if (showMessage) showToast(`Found ${result.models.length} loaded model${result.models.length === 1 ? '' : 's'}`);
  } catch (error) {
    document.getElementById('llmSettingsSummary').textContent = error.message;
    if (showMessage) showToast(error.message);
  } finally {
    button.disabled = false;
  }
}

async function saveLlmSettings() {
  const button = document.getElementById('saveLlmSettings');
  button.disabled = true;
  button.textContent = 'Applying…';
  try {
    const apiKey = document.getElementById('llmApiKey').value.trim();
    const payload = {
      enabled: document.getElementById('llmEnabled').checked,
      base_url: document.getElementById('llmBaseUrl').value.trim(),
      model: document.getElementById('llmModel').value.trim(),
      api_key: apiKey || null,
      temperature: Number(document.getElementById('llmTemperature').value),
      max_tokens: Number(document.getElementById('llmMaxTokens').value),
      timeout_seconds: Number(document.getElementById('llmTimeout').value),
      context_length: Number(document.getElementById('llmContext').value)
    };
    const configuration = await apiRequest('/api/llm/settings', {
      method: 'PUT',
      headers: {'Content-Type':'application/json', 'X-Embodied-Alife-Settings':'confirm'},
      body: JSON.stringify(payload)
    });
    fillLlmForm(configuration);
    showToast(configuration.status?.mode === 'llm' ? 'Local LLM connected' : 'LLM settings saved');
  } catch (error) {
    showToast(error.message);
    document.getElementById('llmSettingsSummary').textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = 'Save and apply';
  }
}

async function control(payload) {
  const data = await apiRequest('/api/control', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify(payload)
  });
  showToast(JSON.stringify(data));
  return data;
}

document.querySelectorAll('[data-action]').forEach(btn => btn.addEventListener('click', () => control({action:btn.dataset.action}).catch(e=>showToast(e.message))));
document.querySelectorAll('[data-speed]').forEach(btn => btn.addEventListener('click', () => control({action:'speed', speed:Number(btn.dataset.speed)}).catch(e=>showToast(e.message))));
document.getElementById('saveSnapshot').onclick = () => { const name = prompt('Snapshot name', `day-${state?.world.day || 1}-${Math.floor(state?.world.sim_time || 0)}`); if(name) control({action:'save', name}).catch(e=>showToast(e.message)); };
document.getElementById('loadSnapshot').onclick = () => { const name = prompt('Snapshot name to load'); if(name) control({action:'load', name}).then(()=>location.reload()).catch(e=>showToast(e.message)); };
document.getElementById('resetSeed').onclick = () => { const raw = prompt('New integer seed (blank = random)'); if(raw !== null && confirm('Reset the experiment? Current unsaved state will be replaced.')) control({action:'reset', seed:raw.trim()===''?null:Number(raw)}).then(()=>location.reload()).catch(e=>showToast(e.message)); };
document.getElementById('checkUpdate').onclick = () => refreshUpdateStatus(true);
document.getElementById('installUpdate').onclick = installAvailableUpdate;
document.getElementById('updateBadge').onclick = () => document.querySelector('.update-panel').scrollIntoView({behavior:'smooth'});
document.getElementById('discoverModels').onclick = () => discoverModels(true);
document.getElementById('saveLlmSettings').onclick = saveLlmSettings;

document.querySelectorAll('.tab').forEach(btn => btn.onclick = () => {
  document.querySelectorAll('.tab').forEach(x => x.classList.remove('active'));
  btn.classList.add('active');
  activeKnowledgeTab = btn.dataset.tab;
  renderKnowledge();
});

function drawWorld() {
  if (!state || !staticTiles) return;
  const size = state.world.size, cell = worldCanvas.width / size;
  worldCtx.clearRect(0,0,worldCanvas.width,worldCanvas.height);
  for(let y=0;y<size;y++) for(let x=0;x<size;x++) { worldCtx.fillStyle=terrainColors[staticTiles[y][x]]||'#333'; worldCtx.fillRect(x*cell,y*cell,Math.ceil(cell),Math.ceil(cell)); }
  state.world.resources.forEach(r => { if(r.quantity<=0) return; worldCtx.fillStyle = r.kind.includes('berry')?'#d24f86':r.kind==='stone'?'#d2d2cd':'#b58a4d'; worldCtx.fillRect((r.x+.2)*cell,(r.y+.2)*cell,Math.max(1,cell*.55),Math.max(1,cell*.55)); });
  state.world.shelters.forEach(s => { worldCtx.fillStyle='#f0c46c'; worldCtx.fillRect((s.x-.35)*cell,(s.y-.35)*cell,cell*1.7,cell*1.7); });
  state.world.npcs.forEach(n => { worldCtx.beginPath(); worldCtx.fillStyle=n.dangerous?'#e35f5f':'#ded6a8'; worldCtx.arc((n.x+.5)*cell,(n.y+.5)*cell,Math.max(2,cell*.7),0,Math.PI*2); worldCtx.fill(); });
  const a=state.agent; worldCtx.beginPath(); worldCtx.fillStyle='#7be7ff'; worldCtx.arc((a.x+.5)*cell,(a.y+.5)*cell,Math.max(3,cell*.95),0,Math.PI*2); worldCtx.fill();
  worldCtx.strokeStyle='#d9fbff'; worldCtx.lineWidth=2; const v=facingVector(a.facing); worldCtx.beginPath(); worldCtx.moveTo((a.x+.5)*cell,(a.y+.5)*cell); worldCtx.lineTo((a.x+.5+v[0]*2)*cell,(a.y+.5+v[1]*2)*cell); worldCtx.stroke();
}
function facingVector(f) { return {north:[0,-1],northeast:[1,-1],east:[1,0],southeast:[1,1],south:[0,1],southwest:[-1,1],west:[-1,0],northwest:[-1,-1]}[f]||[0,-1]; }
function drawLocal() {
  if(!state) return; const p=state.agent_perception; const tiles=p.local_tiles; const radius=10, cell=localCanvas.width/(radius*2+1);
  localCtx.fillStyle='#080d0b'; localCtx.fillRect(0,0,localCanvas.width,localCanvas.height);
  tiles.forEach(t=>{localCtx.fillStyle=terrainColors[t.terrain]||'#333'; localCtx.fillRect((t.x+radius)*cell,(t.y+radius)*cell,Math.ceil(cell),Math.ceil(cell));});
  p.visible_objects.forEach(o=>{ const tile=findObjectTile(o.id); if(!tile)return; localCtx.fillStyle=o.appears_edible?'#d24f86':'#c6a26f'; localCtx.fillRect((tile.x+radius+.25)*cell,(tile.y+radius+.25)*cell,cell*.5,cell*.5); });
  p.visible_entities.forEach(e=>{ const n=state.world.npcs.find(x=>x.id===e.id); if(!n)return; const dx=n.x-state.agent.x,dy=n.y-state.agent.y; localCtx.beginPath();localCtx.fillStyle=e.danger_signs?'#e35f5f':'#ded6a8';localCtx.arc((dx+radius+.5)*cell,(dy+radius+.5)*cell,cell*.35,0,Math.PI*2);localCtx.fill();});
  localCtx.beginPath();localCtx.fillStyle='#7be7ff';localCtx.arc((radius+.5)*cell,(radius+.5)*cell,cell*.42,0,Math.PI*2);localCtx.fill();
}
function findObjectTile(id){ const r=state.world.resources.find(x=>x.id===id); return r?{x:r.x-state.agent.x,y:r.y-state.agent.y}:null; }
function fmt(v){return JSON.stringify(v??null,null,2)}
function driveCard(label,value,invert=false,suffix=''){ const pct=Math.max(0,Math.min(100,Number(value))); const display=invert?100-pct:pct; return `<div class="drive"><header><span>${label}</span><b>${Number(value).toFixed(1)}${suffix}</b></header><div class="meter"><i style="width:${display}%"></i></div></div>`; }
function renderKnowledge(){ if(!state)return; let value; if(activeKnowledgeTab==='truth')value=state.world.truth; else if(activeKnowledgeTab==='beliefs')value=state.agent_beliefs; else value={body:state.agent_perception.body, visible_objects:state.agent_perception.visible_objects, visible_entities:state.agent_perception.visible_entities, terrain_summary:state.agent_perception.terrain_summary, previously_explored:state.agent_perception.previously_explored, known_locations:state.agent_perception.known_locations}; document.getElementById('knowledge').textContent=fmt(value); }
function render() {
  if(!state)return; drawWorld();drawLocal(); const a=state.agent,w=state.world;
  document.getElementById('clock').textContent=`Day ${w.day} · ${w.hour.toFixed(1)}h · t=${w.sim_time.toFixed(1)}s`;
  document.getElementById('seed').textContent=`Seed ${w.seed}`; document.getElementById('weather').textContent=`${w.weather} · ${w.ambient_temperature_c.toFixed(1)}°C`;
  document.getElementById('perceptionRadius').textContent=`${state.agent_perception.local_tiles.length} visible tiles`;
  document.getElementById('drives').innerHTML=driveCard('Health',a.health)+driveCard('Energy',a.energy)+driveCard('Hunger',a.hunger,true)+driveCard('Hydration',a.hydration)+driveCard('Sleep pressure',a.sleep_pressure,true)+driveCard('Body temp',a.body_temperature_c,false,'°C')+driveCard('Pain',a.pain,true);
  const inv=Object.entries(a.inventory); document.getElementById('inventory').innerHTML=inv.length?inv.map(([k,v])=>`<span class="chip">${k} × ${v}</span>`).join(''):'<span class="muted">empty</span>';
  document.getElementById('currentAction').textContent=fmt(a.current_action); document.getElementById('intention').textContent=a.current_intention; document.getElementById('activePlan').textContent=a.active_plan.length?a.active_plan.join(' → '):'No explicit multi-step plan.';
  document.getElementById('decision').textContent=fmt(state.last_decision);document.getElementById('result').textContent=fmt(state.last_action_result);document.getElementById('modelStatus').textContent=fmt(state.model_status);
  renderKnowledge();
  document.getElementById('retrievedMemories').innerHTML=(a.retrieved_memories||[]).map(m=>`<div class="memory"><b>${m.title}</b><br>${m.content}</div>`).join('')||'<p class="muted">none retrieved</p>';
  document.getElementById('memoryWrites').innerHTML=state.memory_writes.slice(-8).reverse().map(m=>`<div class="memory"><b>${m.title}</b><br>${m.category} · ${m.path}</div>`).join('')||'<p class="muted">none yet</p>';
  document.getElementById('timeline').innerHTML=state.events.slice().reverse().map(e=>`<div class="event"><span class="time">${e.sim_time.toFixed(1)}</span><span class="kind">${e.kind}</span><span>${escapeHtml(e.message)}</span></div>`).join('');
  const counts={};w.resources.forEach(r=>counts[r.kind]=(counts[r.kind]||0)+r.quantity);document.getElementById('resourceSummary').innerHTML='<h3>Resources</h3>'+Object.entries(counts).map(([k,v])=>`<span class="chip">${k}: ${v}</span>`).join(' ');
  document.getElementById('npcSummary').innerHTML='<h3>NPCs</h3>'+w.npcs.map(n=>`<span class="chip">${n.id} (${n.state}) @ ${n.x.toFixed(0)},${n.y.toFixed(0)}</span>`).join(' ');
  document.getElementById('snapshotList').innerHTML=state.snapshots.map(s=>`<div class="memory"><b>${s.name}</b><br>seed ${s.seed} · t=${Number(s.sim_time).toFixed(1)}</div>`).join('')||'<p class="muted">none</p>';
  document.querySelectorAll('[data-speed]').forEach(b=>b.classList.toggle('active',Number(b.dataset.speed)===state.speed));
}
function escapeHtml(text){ const d=document.createElement('div');d.textContent=text;return d.innerHTML; }

async function initialize(){
  refreshUpdateStatus(false);
  setInterval(()=>refreshUpdateStatus(false), 60000);
  loadLlmSettings();
  const response=await fetch('/api/world');
  const initial=await response.json();
  staticTiles=initial.world.tiles;
  delete initial.world.tiles;
  state=initial;
  render();
  connect();
}
function connect(){ const protocol=location.protocol==='https:'?'wss':'ws'; const ws=new WebSocket(`${protocol}://${location.host}/ws`); const badge=document.getElementById('connection'); ws.onopen=()=>{badge.textContent='live';badge.className='pill ok';}; ws.onmessage=e=>{state=JSON.parse(e.data);render();}; ws.onclose=()=>{badge.textContent='reconnecting';badge.className='pill warning';setTimeout(connect,1500);}; ws.onerror=()=>{badge.textContent='socket error';badge.className='pill error';}; }
initialize().catch(e=>{document.getElementById('connection').textContent=e.message;document.getElementById('connection').className='pill error';});
