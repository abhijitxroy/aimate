/* Per-request local choice; cloud settings are never overwritten or auto-switched. */
window.AiMateLocalAI=(()=>{
  let selected=false,model="qwen3:4b",available=false,capable=false,pending=null,checkVersion=0;
  let controls=false,stopping=false,enableVersion=0;
  const enabled=()=>window.AiMateFeatures?.localAI!==false;
  const supported=()=>enabled() && capable;
  const provider=()=>$("#settingsForm").elements["ai.provider"];
  const connectionSelected=()=>supported() && provider().value==="local";
  const controlSupported=()=>supported() && controls;
  function refreshStop() {
    $("#useCloudAI").disabled=stopping;
    $("#useLocalAI").disabled=stopping || selected || !available || busy;
    $("#localAIState").textContent=selected ? "On · local AI for this session" : "Off · saved cloud connection in use";
    $("#localAIState").className=selected ? "hint warning" : "hint";
  }
  async function stop(run,unload) {
    if(stopping || !controlSupported())return;
    stopping=true;refreshStop(run);
    const status=$("#localAIMessage");status.textContent=unload ? "Stopping & unloading…" : "Stopping local request…";
    try {
      const operation=api("/api/local-ai/stop",{method:"POST",body:JSON.stringify({
        ...(run?.local ? {conversation:run.cid,request_id:run.requestId} : {}),
        model:run?.localModel || model,unload})});
      if(run?.local)run.controller.abort();
      const result=await operation;
      status.textContent=result.message;status.className="hint success";
      $("#localAIMessage").textContent=result.message;
    } catch(error) {status.textContent=error.message;status.className="hint warning";}
    finally {if(run?.local)run.controller.abort();stopping=false;refreshStop();}
  }
  async function disable() {
    if(stopping)return;
    const runs=chatRuns.list().filter(run=>run.local);
    const models=[...new Set([model,...runs.map(run=>run.localModel)])];
    selected=false;enableVersion++;stopping=true;
    render();renderModelSelection();
    const status=$("#localAIMessage");status.textContent="Stopping local AI…";
    try {
      if(!controlSupported()) {
        for(const run of runs)run.controller.abort();
        throw new Error("Local AI is disabled. Explicit memory release is unavailable; Ollama unloads idle models automatically.");
      }
      const cancels=runs.map(run=>{
        const operation=api("/api/local-ai/stop",{method:"POST",body:JSON.stringify({
          conversation:run.cid,request_id:run.requestId,unload:false})});
        run.controller.abort();return operation;
      });
      const results=await Promise.allSettled(cancels);
      const failed=results.find(result=>result.status==="rejected");
      if(failed)throw failed.reason;
      for(const name of models)await api("/api/local-ai/stop",{method:"POST",
        body:JSON.stringify({model:name,unload:true})});
      status.textContent="Local AI off. Model memory released.";status.className="hint success";
    } catch(error) {status.textContent="Local AI off. "+error.message;status.className="hint warning";}
    finally {stopping=false;render();}
  }
  function refreshConnection() {
    const local=connectionSelected();
    $("#localAISettings").hidden=!local;
    $("#settings-ai").classList.toggle("local-connection",local);
    if(local) {
      for(const id of ["apiModelLabel","chatgptModelLabel","chatgptConnection","apiCredentials",
        "geminiSettings","bedrockSetup","bedrockModelChoices","removeAIKey"]) $("#"+id).hidden=true;
      $("#settings-ai .model-selection").hidden=true;
      $("#testAIButton").hidden=true;$("#localAISettings").open=true;
      $("#localAIModel").disabled=false;$("#checkLocalAI").disabled=false;
      refreshStop();
    } else {
      $("#testAIButton").hidden=false;
      if(provider().value!=="gemini") $("#settings-ai .model-selection").hidden=false;
    }
  }
  function restorePicker() {if(selected && supported()) provider().value="local";}
  function render() {
    const option=provider().querySelector('[value="local"]');
    if(option) {
      option.hidden=!supported();option.disabled=!supported();
      option.parentElement.hidden=!supported();
    }
    if(!supported()) {
      selected=false;enableVersion++;
      if(provider().value==="local") {provider().value=config.ai?.provider || "chatgpt";void updateProvider();}
      if($("#offlineAIDialog").open) $("#offlineAIDialog").close();
    }
    refreshConnection();
    refreshStop();
  }
  async function check() {
    if(!supported()) return false;
    const version=++checkVersion;
    $("#localAIMessage").textContent="Checking Ollama…";
    $("#checkLocalAI").disabled=true;
    try {
      const result=await api("/api/local-ai/status");
      if(version!==checkVersion || !supported()) return false;
      available=result.available && result.models.length>0;
      const picker=$("#localAIModel");picker.replaceChildren();
      for(const name of result.models) picker.append(new Option(name,name));
      if(result.models.includes(model)) picker.value=model;
      else if(result.models.length) model=picker.value;
      $("#localAIMessage").textContent=result.message+
        (result.available && !result.models.length ? " No models installed. Run: ollama pull qwen3:4b" : "");
      $("#localAIMessage").className=available ? "hint success" : "hint warning";
      $("#useLocalAI").disabled=!available;
    } catch(error) {available=false;$("#localAIMessage").textContent="Cannot reach local AI. Check that AiMate and Ollama are running. "+error.message;$("#useLocalAI").disabled=true;}
    finally {if(version===checkVersion) {$("#checkLocalAI").disabled=false;refreshStop();}}
    return available;
  }
  async function activate(stillWanted=()=>true) {
    const version=++enableVersion;
    if(!supported() || !await check()) return false;
    if(!stillWanted() || !supported() || stopping || version!==enableVersion) return false;
    model=$("#localAIModel").value;selected=true;
    if($("#modelMode").value==="analysis") $("#modelMode").value="auto";
    render();renderModelSelection();return true;
  }
  async function request(reason) {
    if(!supported() || pending) return false;
    const dialog=$("#offlineAIDialog");
    $("#offlineAIReason").textContent=reason;
    $("#offlineAIStatus").textContent="Checking installed local models…";
    const answer=new Promise(resolve=>{pending=resolve;});
    dialog.showModal();
    const ready=await check();
    if(dialog.open && supported()) {
      $("#offlineAIStatus").textContent=ready ? `${model} is installed. Local AI stays off until enabled in Connections.` : $("#localAIMessage").textContent;
      $("#offlineAIStatus").className=ready ? "hint success" : "hint warning";
    }
    return answer;
  }
  function offer(message,retry) {
    if(!enabled() || !capable || message.root.querySelector(".local-ai-offer")) return;
    const row=element("div","source-recovery local-ai-offer");
    row.append(element("small","hint","Cloud AI is unavailable. Local AI stays off until enabled in Connections."));
    const button=element("button","","Open AI connections");button.type="button";
    button.onclick=()=>{activeSettings="ai";openSettings();provider().value="local";void updateProvider();void check();};
    row.append(button);message.root.append(row);
  }
  document.addEventListener("DOMContentLoaded",()=>{
    const group=document.createElement("optgroup");group.label="This laptop";
    group.append(new Option("Local LLM · offline","local"));provider().append(group);
    $("#checkLocalAI").onclick=check;
    $("#useLocalAI").onclick=async()=>{
      if(await activate()) $("#settingsStatus").textContent="Local AI selected for this session. Cloud settings kept.";
    };
    $("#useCloudAI").onclick=disable;
    provider().addEventListener("change",()=>{
      if(connectionSelected()) {refreshConnection();void check();}
      else if(selected) {void disable();}
    });
    $("#localAIModel").onchange=()=>{model=$("#localAIModel").value;if(selected)renderModelSelection();};
    $("#offlineAIDialog").addEventListener("close",()=>{const resolve=pending;pending=null;resolve?.(false);});
    for(const id of ["closeOfflineAI","cancelOfflineAI"]) $("#"+id).onclick=()=>$("#offlineAIDialog").close();
    $("#offlineAIConnections").onclick=()=>{
      $("#offlineAIDialog").close();activeSettings="ai";openSettings();provider().value="local";void updateProvider();void check();
    };
    render();
  });
  document.addEventListener("aimate:state",render);
  return Object.freeze({active:()=>selected && supported(),model:()=>model,offer,request,check,activate,
    supported,connectionSelected,refreshConnection,restorePicker,refreshStop,stop,controlSupported,
    setControls(value){controls=value===true;refreshStop();},
    setEnabled(value){capable=value!==false;if(!capable){selected=false;enableVersion++;}render();}});
})();
