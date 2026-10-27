'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const els = Object.fromEntries(['device-label','device-detail','connection-dot','demo-badge','frequency','start-capture','cancel-capture','capture-progress','progress-fill','capture-progress-text','notice','setup-guide','capture-count','library-empty','library-footnote','capture-list','new-draft','editor-heading','record-meta','dirty-indicator','capture-form','capture-name','capture-notes','capture-code','code-label','code-help','toggle-json','code-summary','validate-code','save-capture','save-feedback','test-times','test-code','test-result','test-result-title','test-result-detail','test-timing','footer-host','trial-count','trial-empty','trial-table-wrap','trial-list','history-warning'].map(id => [id,$(id)]));
  let csrf = '', selected = null, baseline = '', jsonMode = false, operation = null, busy = false, ready = false, pollTimer = null, stopped = false;
  let library = [], trials = [], handledOperations = new Set(), testContext = null, lastTest = null, currentCode = '', demo = false, mutationEpoch = 0, jsonOriginalCode = '', jsonOriginalText = '', ownCaptureId = null, pendingCapture = null;
  const terminal = op => op && ['done','error'].includes(op.phase);
  const running = () => operation && !terminal(operation);
  const pollingDelay = () => running() ? (operation.kind==='test' ? 150 : 1000) : 5000;
  const presetButtons = [...document.querySelectorAll('[data-times]')];
  const textToBase64 = text => { const bytes = new TextEncoder().encode(text); let binary = ''; for (let i=0;i<bytes.length;i+=8192) binary += String.fromCharCode(...bytes.subarray(i,i+8192)); return btoa(binary); };
  const base64ToText = code => new TextDecoder('utf-8',{fatal:true}).decode(Uint8Array.from(atob(code),c=>c.charCodeAt(0)));
  function codeValue() {
    const value = els['capture-code'].value.trim();
    if (!jsonMode || !value) return value;
    let parsed; try { parsed = JSON.parse(value); } catch { throw new Error('El JSON contiene un error. Revisa su sintaxis antes de continuar.'); }
    return value === jsonOriginalText.trim() ? jsonOriginalCode : textToBase64(value);
  }
  function fingerprint() {
    let code; try { code = codeValue(); } catch { code = 'invalid-json:' + els['capture-code'].value; }
    return JSON.stringify([els['capture-name'].value.trim(),els['capture-notes'].value.trim(),code]);
  }
  const dirty = () => fingerprint() !== baseline;
  function notice(message, type='info') { els.notice.textContent = message; els.notice.className = 'notice' + (type==='info'?'':' '+type); els.notice.hidden = !message; }
  function safeError(error) { notice(error instanceof Error ? error.message : 'No se pudo completar la operación.','error'); }
  async function request(path, body) {
    let response;
    try { response = await fetch(path,{method:body === undefined ? 'GET':'POST',credentials:'same-origin',headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':csrf},...(body===undefined?{}:{body:JSON.stringify(body)})}); }
    catch { throw new Error('No se pudo contactar con la aplicación local. Comprueba que el servidor siga abierto.'); }
    let data; try { data = await response.json(); } catch { throw new Error('El servidor local devolvió una respuesta que no se pudo leer.'); }
    if (!response.ok) { const message = typeof data.error === 'string' ? data.error : typeof data.message === 'string' ? data.message : 'No se pudo completar la operación. Revisa el código e inténtalo de nuevo.'; throw new Error(message); }
    return data;
  }
  function summaryText(summary) {
    if (!summary) return '';
    if (typeof summary === 'string') return summary;
    const labels = {frequency:'Frecuencia MHz',frequency_mhz:'Frecuencia MHz',num:'Señales',rf_type:'Tipo',type:'Tipo',mode:'Modo',length:'Caracteres',bytes:'Bytes',pulse_count:'Pulsos',pulses:'Pulsos',keys:'Campos',version:'Versión',times:'Repeticiones',valid:'Válido',format:'Formato',signal_length:'Longitud de señal',key_count:'Campos',encoding:'Formato',rfkey_count:'Claves RF',rfkeys:'Claves RF'};
    return Object.entries(summary).filter(([,v])=>v!==null&&v!==undefined&&['string','number','boolean'].includes(typeof v)).map(([k,v])=>(labels[k]||k.replaceAll('_',' '))+': '+(typeof v==='boolean'?(v?'sí':'no'):v)).join(' · ') || 'Código validado.';
  }
  function showSummary(summary) { const text = summaryText(summary); els['code-summary'].textContent = text; els['code-summary'].hidden = !text; }
  function dateLabel(value) { const date = new Date(value); return Number.isNaN(date.valueOf()) ? '' : date.toLocaleString('es-MX',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}); }
  function physicalLabel(value) {
    if (value === true || value === 'worked' || value?.worked === true) return 'Funcionamiento confirmado';
    if (value === false || value === 'failed' || value?.worked === false) return 'No funcionó físicamente';
    return 'Sin verificar físicamente';
  }
  function milliseconds(value) { return typeof value==='number' && Number.isFinite(value) && value>=0 ? value.toLocaleString('es-MX',{maximumFractionDigits:1})+' ms' : '—'; }
  function showTiming(timing) {
    els['test-timing'].replaceChildren(); els['test-timing'].hidden=!timing || typeof timing!=='object';
    if(!timing || typeof timing!=='object') return;
    for(const [key,label] of [['prepare','Preparación'],['arp','ARP'],['connect','Conexión'],['write','Envío'],['response','Respuesta / ACK'],['total','Total']]) {
      const item=document.createElement('div'), term=document.createElement('dt'), value=document.createElement('dd'); term.textContent=label; value.textContent=milliseconds(timing[key]); item.append(term,value); els['test-timing'].append(item);
    }
  }
  function outcomeLabel(value) {
    return ({ACKNOWLEDGED:'L20: orden recibida (ACK)',UNCERTAIN:'L20: respuesta incierta',SENT:'L20: orden enviada',DEVICE_REJECTED:'L20: orden rechazada',REJECTED:'L20: orden rechazada',NOT_SENT:'La orden no se envió',ERROR:'Prueba sin completar',FAILED:'Prueba sin completar',TIMEOUT:'L20: sin respuesta a tiempo'})[value] || 'Respuesta sin confirmar';
  }
  function renderTrials() {
    const items=trials.slice().sort((a,b)=>Date.parse(b.at)-Date.parse(a.at)).slice(0,50); els['trial-count'].textContent=items.length; els['trial-empty'].hidden=items.length>0; els['trial-table-wrap'].hidden=!items.length; els['trial-list'].replaceChildren();
    for(const trial of items) {
      const row=document.createElement('tr'), control=document.createElement('td'), times=document.createElement('td'), total=document.createElement('td'), result=document.createElement('td');
      const name=document.createElement('strong'), at=document.createElement('span'); name.textContent=trial.name || 'Borrador'; const date=new Date(trial.at); at.textContent=Number.isNaN(date.valueOf())?'':date.toLocaleString('es-MX',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',second:'2-digit'}); control.className='trial-control'; control.append(name,at);
      times.textContent=String(trial.times ?? '—'); times.className='trial-number'; total.textContent=milliseconds(trial.timing_ms?.total); total.className='trial-total';
      const physical=document.createElement('strong'), response=document.createElement('span'); physical.textContent=trial.physical_result==='worked'?'Funcionó físicamente':trial.physical_result==='failed'?'No funcionó físicamente':'Sin observación física'; physical.className='trial-physical'+(trial.physical_result==='worked'?' worked':trial.physical_result==='failed'?' failed':''); response.textContent=outcomeLabel(trial.outcome); response.className='trial-response'; result.append(physical,response);
      if(!demo && !trial.demo && trial.frame_write_attempted) {
        const actions=document.createElement('div'); actions.className='trial-actions';
        for(const [worked,label] of [[true,'Funcionó'],[false,'No funcionó']]) { const button=document.createElement('button'); button.type='button'; button.className='secondary small'; button.textContent=label; button.setAttribute('aria-label',label+': '+(trial.name || 'Borrador')); button.setAttribute('aria-pressed',String(trial.physical_result===(worked?'worked':'failed'))); button.disabled=busy || !!running(); button.addEventListener('click',()=>verifyTrial(trial.id,worked)); actions.append(button); }
        result.append(actions);
      } else { const hint=document.createElement('span'); hint.className='trial-observation-note'; hint.textContent=demo || trial.demo?'Demostración sin equipo':'Sin transmisión que observar'; result.append(hint); }
      row.append(control,times,total,result); els['trial-list'].append(row);
    }
  }
  function renderLibrary() {
    els['capture-count'].textContent = library.length;
    els['library-empty'].hidden = library.length>0;
    els['capture-list'].replaceChildren();
    for (const item of library) {
      const li = document.createElement('li'), button = document.createElement('button'), title = document.createElement('strong'), detail = document.createElement('span');
      button.type = 'button'; button.className = 'capture-item'+(selected?.id===item.id?' selected':''); button.setAttribute('aria-current',selected?.id===item.id?'true':'false');
      button.disabled = busy || !!running(); title.textContent = item.name; detail.textContent = physicalLabel(item.physical_result); button.append(title,detail); button.addEventListener('click',()=>selectRecord(item.id)); li.append(button); els['capture-list'].append(li);
    }
  }
  function updateForm() {
    const changed = dirty(), active = !!running(), capturing = active && operation.kind==='capture';
    els['dirty-indicator'].textContent = selected ? (changed?'Cambios sin guardar':'Guardada'):'Borrador';
    els['dirty-indicator'].classList.toggle('modified',changed);
    els['save-capture'].textContent = selected ? 'Guardar cambios':'Guardar captura';
    els['save-capture'].disabled = busy || active || !els['capture-code'].value.trim() || (!!selected&&!changed);
    els['validate-code'].disabled = busy || active || !els['capture-code'].value.trim();
    els['test-code'].disabled = busy || active || !ready || !els['capture-code'].value.trim();
    els['test-code'].textContent = active && operation.kind==='test' ? 'Transmitiendo…':'Probar código';
    els['start-capture'].disabled = busy || active || !ready;
    els['start-capture'].hidden = capturing;
    els['cancel-capture'].hidden = !capturing;
    els['cancel-capture'].disabled = busy;
    els.frequency.disabled = busy || active;
    els['new-draft'].disabled = busy || active;
    $('use-pending-capture').disabled = busy || active;
    els['test-times'].disabled = busy || active;
    for(const button of presetButtons) { button.disabled=busy || active; button.setAttribute('aria-pressed',String(Number(button.dataset.times)===Number(els['test-times'].value))); }
    for (const id of ['capture-name','capture-notes','capture-code','toggle-json']) els[id].disabled = busy || capturing;
    if (lastTest) els['test-result'].hidden = lastTest.code !== currentCode;
    else if(active && operation.kind==='test' && testContext?.operationId===operation.id) els['test-result'].hidden=testContext.code!==currentCode;
    for (const button of els['capture-list'].querySelectorAll('button')) button.disabled = busy || active;
    for (const button of els['trial-list'].querySelectorAll('button')) button.disabled = busy || active;
  }
  function replaceEditor(record=null, code='', summary=null) {
    selected = record; jsonMode = false; jsonOriginalCode=''; jsonOriginalText='';
    els['capture-name'].value = record?.name || ''; els['capture-notes'].value = record?.notes || ''; els['capture-code'].value = record?.code || code; currentCode = record?.code || code;
    els['code-label'].textContent='Código Base64'; els['toggle-json'].textContent='Ver JSON'; els['toggle-json'].setAttribute('aria-pressed','false');
    els['code-help'].textContent='Conserva el código completo. Puedes editarlo y validarlo antes de guardar.';
    els['editor-heading'].textContent=record?.name || 'Nueva captura';
    els['record-meta'].textContent=record ? `Revisión ${record.revision} · ${dateLabel(record.updated_at || record.created_at)}`:'Borrador sin guardar';
    els['save-feedback'].textContent=''; showSummary(record?.summary || summary); baseline=fingerprint();
    // A received capture is a new draft, and must be saved explicitly.
    if (!record && code) baseline=JSON.stringify(['','','']);
    renderLibrary(); updateForm();
  }
  function mayDiscard() { return !dirty() || window.confirm('Hay cambios sin guardar. ¿Quieres descartarlos y continuar?'); }
  async function guarded(action) { if (busy) return; busy=true; mutationEpoch++; updateForm(); try { await action(); } catch(error) { safeError(error); } finally { busy=false; updateForm(); } }
  async function selectRecord(id) {
    if (busy || running() || !mayDiscard()) return;
    await guarded(async()=> { const data=await request('/api/captures/'+encodeURIComponent(id)); replaceEditor(data.record); notice(''); });
  }
  function showTestResult(op) {
    const result=op.result || {}, outcome=String(result.outcome || (op.phase==='error'?'ERROR':'UNCERTAIN')).toUpperCase();
    const labels={ACKNOWLEDGED:'El L20 recibió la orden',UNCERTAIN:'Resultado incierto',SENT:'Orden enviada',ERROR:'La prueba no se completó',FAILED:'La prueba no se completó',REJECTED:'El L20 rechazó la orden',DEVICE_REJECTED:'El L20 rechazó la orden',NOT_SENT:'La orden no se envió',TIMEOUT:'No llegó confirmación del L20',CANCELLED:'Prueba cancelada',CANCELED:'Prueba cancelada'};
    const descriptions={ACKNOWLEDGED:'El dispositivo respondió a la transmisión.',UNCERTAIN:'No se pudo confirmar la respuesta del dispositivo. No se reenvió la orden automáticamente.',SENT:'Se envió la orden al dispositivo.',ERROR:'Revisa la conexión local y el código antes de iniciar otra prueba.',FAILED:'Revisa la conexión local y el código antes de iniciar otra prueba.',REJECTED:'Revisa el código antes de iniciar otra prueba.',NOT_SENT:'No se inició la transmisión.',TIMEOUT:'La orden podría haberse enviado. Comprueba el receptor antes de volver a probar.',CANCELLED:'La operación terminó sin una confirmación de transmisión.',CANCELED:'La operación terminó sin una confirmación de transmisión.'};
    els['test-result'].hidden=false; els['test-result'].className='test-result'+(outcome==='ACKNOWLEDGED'?'':['ERROR','FAILED','REJECTED','DEVICE_REJECTED','NOT_SENT'].includes(outcome)?' error':' uncertain');
    els['test-result-title'].textContent=labels[outcome] || 'Prueba terminada: resultado sin confirmar';
    const problems={DEMO:'Demostración: no se envió ninguna señal al equipo.',TIMEOUT:'Terminó el plazo sin una confirmación. La orden podría haberse enviado.',IO:'La comunicación con el L20 se interrumpió.',DEVICE_REJECTED:'El dispositivo rechazó la orden.',MAC_MISMATCH:'No se pudo confirmar que la dirección pertenece al L20.',ARP_UNAVAILABLE:'No se pudo comprobar la dirección del L20.'};
    els['test-result-detail'].textContent=(problems[result.problem] || (op.phase==='error'?op.message:'') || descriptions[outcome] || 'Comprueba físicamente el resultado antes de repetir la prueba.')+(result.times ? ` Repeticiones solicitadas: ${result.times}.`:'');
    showTiming(result.timing_ms);
    if(result.history_saved===false) notice('El ensayo terminó, pero no se guardó su historial.','error');
  }
  function operationChanged(op) {
    operation = op;
    const capturing=running()&&op.kind==='capture';
    els['capture-progress'].hidden=!capturing;
    if(capturing) {
      const remaining=Number(op.remaining);
      els['progress-fill'].style.width=Number.isFinite(remaining)?Math.max(0,Math.min(100,(30-remaining)/30*100))+'%':'0%';
      els['capture-progress-text'].textContent=op.message || (Number.isFinite(remaining)?`Escuchando · quedan ${Math.max(0,Math.ceil(remaining))} s. Pulsa el botón del control.`:'Escuchando. Pulsa el botón del control.');
    }
    if(op && !terminal(op) && op.kind==='test' && testContext?.operationId===op.id) {
      els['test-result-title'].textContent='Prueba en curso'; els['test-result-detail'].textContent=op.message || 'Enviando la orden al L20…'; els['test-result'].hidden=testContext.code!==currentCode;
    }
    if(op && terminal(op) && !handledOperations.has(op.id)) {
      handledOperations.add(op.id);
      if(op.kind==='capture') {
        if(op.phase==='done' && op.result?.code) {
          if(op.id===ownCaptureId) { receiveCapture(op.result); }
          else { pendingCapture=op.result; $('pending-capture').hidden=false; }
        }
        else notice(op.message || 'No se recibió una captura. Puedes iniciar una nueva escucha.',op.phase==='error'?'error':'info');
      } else if(op.kind==='test' && testContext?.operationId===op.id) {
        lastTest={operation:op,...testContext}; showTestResult(op);
      }
    }
    updateForm();
  }
  function receiveCapture(result) {
    replaceEditor(null,result.code,result.summary); pendingCapture=null; $('pending-capture').hidden=true;
    notice('Captura recibida. Dale un nombre y guárdala. Comprueba el botón al probarla.'+(result.learning_exit_sent===false?' No se pudo confirmar la salida del aprendizaje.':''),'success'); els['capture-name'].focus();
  }
  async function poll() {
    clearTimeout(pollTimer); if(stopped) return;
    if(busy) { pollTimer=setTimeout(poll,pollingDelay()); return; }
    const epoch=mutationEpoch, lightweight=!!running() && operation.kind==='test';
    try {
      const state=await request(lightweight?'/api/operation':'/api/state'); if(busy || epoch!==mutationEpoch) { pollTimer=setTimeout(poll,pollingDelay()); return; }
      if(!lightweight) {
        ready=!!state.device?.ready; library=Array.isArray(state.captures)?state.captures:[]; trials=Array.isArray(state.trials)?state.trials:[]; demo=!!state.demo; els['history-warning'].hidden=!state.history_error;
        const device=state.device || {};
        els['device-label'].textContent=demo?'Demostración sin equipo':ready?'Credencial lista':'Sin configurar';
        els['device-detail'].textContent=[device.host || 'Destino sin configurar','Tuya '+(device.version || '3.3')].join(' · '); els['setup-guide'].hidden=ready || demo;
        els['connection-dot'].className='status-dot'+(ready?' ready':''); els['demo-badge'].hidden=!state.demo;
        els['footer-host'].textContent=device.host || 'Sin configurar'; els['library-footnote'].textContent='Las capturas se guardan cifradas en este equipo.'+(state.unreadable_captures ? ` No se pudieron leer ${state.unreadable_captures} captura(s).`: ''); renderLibrary(); renderTrials();
      }
      operationChanged(state.operation || null);
      if(lightweight && !running()) { pollTimer=setTimeout(poll,0); return; }
    } catch(error) { ready=false; els['device-label'].textContent='Servidor local sin respuesta'; els['connection-dot'].className='status-dot error'; updateForm(); notice(error.message,'error'); }
    pollTimer=setTimeout(poll,pollingDelay());
  }
  function resumePoll() { clearTimeout(pollTimer); pollTimer=setTimeout(poll,150); }
  els['new-draft'].addEventListener('click',()=> { if(mayDiscard()) { replaceEditor(); notice(''); els['capture-name'].focus(); } });
  for(const id of ['capture-name','capture-notes','capture-code']) els[id].addEventListener('input',()=> { els['save-feedback'].textContent=''; if(id==='capture-code') { showSummary(null); try { currentCode=codeValue(); } catch { currentCode=''; } } updateForm(); });
  els['toggle-json'].addEventListener('click',()=> {
    try {
      if(jsonMode) { const code=codeValue(); els['capture-code'].value=code; jsonMode=false; }
      else { const value=els['capture-code'].value.trim(); if(!value) throw new Error('Primero captura o pega un código Base64.'); let parsed; try { parsed=JSON.parse(base64ToText(value)); } catch { throw new Error('Este código no contiene un JSON UTF-8 válido. Puedes conservarlo en Base64.'); } jsonOriginalCode=value; jsonOriginalText=JSON.stringify(parsed,null,2); els['capture-code'].value=jsonOriginalText; jsonMode=true; }
      els['code-label'].textContent=jsonMode?'Código JSON':'Código Base64'; els['toggle-json'].textContent=jsonMode?'Ver Base64':'Ver JSON'; els['toggle-json'].setAttribute('aria-pressed',String(jsonMode));
      els['code-help'].textContent=jsonMode?'Edita el JSON. Se convierte a Base64 al validar, guardar o probar.':'Conserva el código completo. Puedes editarlo y validarlo antes de guardar.';
      currentCode=codeValue(); updateForm();
    } catch(error) { safeError(error); }
  });
  els['validate-code'].addEventListener('click',()=>guarded(async()=> { const data=await request('/api/validate',{code:codeValue()}); showSummary(data.summary); notice('Código válido. La validación no transmite ninguna señal.','success'); }));
  els['capture-form'].addEventListener('submit',event=> { event.preventDefault(); guarded(async()=> {
    const name=els['capture-name'].value.trim(); if(!name) { els['capture-name'].focus(); throw new Error('Escribe un nombre para guardar la captura.'); }
    const body={name,notes:els['capture-notes'].value.trim(),code:codeValue()}; if(selected) { body.id=selected.id; body.revision=selected.revision; }
    const data=await request('/api/captures',body); const index=library.findIndex(r=>r.id===data.record.id); if(index<0) library.unshift(data.record); else library[index]=data.record;
    replaceEditor(data.record); els['save-feedback'].textContent='Guardada en este equipo'; notice('');
  }); });
  els['start-capture'].addEventListener('click',()=> { if(!mayDiscard()) return; guarded(async()=> { const data=await request('/api/capture/start',{frequency:els.frequency.value}); ownCaptureId=data.operation.id; pendingCapture=null; $('pending-capture').hidden=true; notice(''); operationChanged(data.operation); resumePoll(); }); });
  $('use-pending-capture').addEventListener('click',()=> { if(pendingCapture && !busy && !running() && mayDiscard()) receiveCapture(pendingCapture); });
  els['cancel-capture'].addEventListener('click',()=>guarded(async()=> { await request('/api/capture/cancel',{}); notice('Captura cancelada.'); resumePoll(); }));
  els['test-code'].addEventListener('click',()=>guarded(async()=> {
    const times=Number(els['test-times'].value); if(!Number.isInteger(times)||times<1||times>6) { els['test-times'].focus(); throw new Error('Elige entre 1 y 6 repeticiones.'); }
    const code=codeValue(); const data=await request('/api/test',{code,times,name:els['capture-name'].value.trim() || 'Borrador',request_id:crypto.randomUUID()});
    testContext={operationId:data.operation.id,code};
    els['test-result'].hidden=false; els['test-result'].className='test-result'; els['test-result-title'].textContent='Enviando la orden al L20…'; els['test-result-detail'].textContent='La prueba se ejecuta una vez, con las repeticiones indicadas.'; showTiming(null); lastTest=null;
    notice(''); operationChanged(data.operation); resumePoll();
  }));
  async function verifyTrial(operationId,worked) { await guarded(async()=> {
    const data=await request('/api/trial-result',{operation_id:operationId,worked});
    const index=trials.findIndex(trial=>trial.id===operationId); if(index>=0) trials[index]=data.trial; else trials.unshift(data.trial); renderTrials();
    notice(worked?'Registraste que el receptor funcionó físicamente en este ensayo.':'Registraste que el receptor no funcionó físicamente en este ensayo.','success');
  }); }
  for(const button of presetButtons) button.addEventListener('click',()=> { els['test-times'].value=button.dataset.times; updateForm(); });
  els['test-times'].addEventListener('input',updateForm);
  window.addEventListener('beforeunload',event=> { if(dirty()) { event.preventDefault(); event.returnValue=''; } });
  replaceEditor();
  request('/api/session').then(session=> { csrf=session.csrf; demo=!!session.demo; els['demo-badge'].hidden=!session.demo; return poll(); }).catch(error=> { safeError(error); els['device-label'].textContent='No se pudo iniciar la aplicación'; });
})();
