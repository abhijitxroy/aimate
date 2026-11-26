/* Per-request local choice; cloud settings are never overwritten or auto-switched. */
window.AiMateLocalAI=(()=>{
  let selected=false,model="qwen3:4b",available=false,capable=false,pending=null,checkVersion=0;
  let controls=false,stopping=false;
  const enabled=()=>window.AiMateFeatures?.localAI!==false;
  const supported=()=>enabled() && capable;
  const provider=()=>$("#settingsForm").elements["ai.provider"];
  const connectionSelected=()=>supported() && provider().value==="local";
  const controlSupported=()=>supported() && controls;
  function refreshStop(run=chatRuns.get(cid)) {
    const button=$("#stopLocalAI");if(!button)return;
    button.hidden=!controlSupported() || !(run?.local || selected);
    button.disabled=stopping || Boolean(run && !run.local);
    $("#unloadLocalAI").hidden=!controlSupported();
    $("#unloadLocalAI").disabled=stopping;
  }
  async function stop(run,unload) {
    if(stopping || !controlSupported())return;
    stopping=true;refreshStop(run);
    const status=$("#localStopStatus");status.hidden=false;status.textContent=unload ? "Stopping & unloading…" : "Stopping local request…";
    try {
      const result=await api("/api/local-ai/stop",{method:"POST",body:JSON.stringify({
        ...(run?.local ? {conversation:run.cid,request_id:run.requestId} : {}),
        model:run?.localModel || model,unload})});
      status.textContent=result.message;status.className="hint success";
      $("#localAIMessage").textContent=result.message;
    } catch(error) {status.textContent=error.message;status.className="hint warning";}
    finally {if(run?.local)run.controller.abort();stopping=false;refreshStop();}
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
      $("#useCloudAI").disabled=false;$("#useLocalAI").disabled=!available || busy;
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
      selected=false;
      if(provider().value==="local") {provider().value=config.ai?.provider || "chatgpt";void updateProvider();}
      if($("#offlineAIDialog").open) $("#offlineAIDialog").close();
    }
    $("#localAIToggle").hidden=!supported();
    $("#localAIToggle").disabled=busy;
    $("#localAIToggle").setAttribute("aria-pressed",String(selected));
    $("#localAIToggle").textContent=selected ? "Local" : "Cloud";
    $("#localAIToggle").title=selected ? `Local model · ${model}. Cloud AI is off; connectors still need network/VPN.` : "Use cloud AI. Click to choose a local model instead.";
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
    finally {if(version===checkVersion) $("#checkLocalAI").disabled=false;}
    return available;
  }
  async function activate(stillWanted=()=>true) {
    if(!supported() || !await check()) return false;
    if(!stillWanted() || !supported()) return false;
    model=$("#localAIModel").value;selected=true;
    if($("#modelMode").value==="analysis") $("#modelMode").value="auto";
    render();renderModelSelection();return true;
  }
  async function request(reason) {
    if(!supported() || pending) return false;
    const dialog=$("#offlineAIDialog");
    $("#offlineAIReason").textContent=reason;
    $("#offlineAIStatus").textContent="Checking installed local models…";
    $("#continueOfflineAI").disabled=true;
    const answer=new Promise(resolve=>{pending=resolve;});
    dialog.showModal();
    const ready=await check();
    if(dialog.open && supported()) {
      $("#offlineAIStatus").textContent=ready ? `${model} is available. Switch only if you choose Continue.` : $("#localAIMessage").textContent;
      $("#offlineAIStatus").className=ready ? "hint success" : "hint warning";
      $("#continueOfflineAI").disabled=!ready;
    }
    return answer;
  }
  function offer(message,retry) {
    if(!enabled() || !capable || message.root.querySelector(".local-ai-offer")) return;
    const row=element("div","source-recovery local-ai-offer");
    row.append(element("small","hint","Cloud AI is unavailable. Continue with a local model? Saved context may be stale; service reads still need network/VPN."));
    const button=element("button","","Continue with local AI");button.type="button";
    const choose=async()=>{
      button.disabled=true;
      try {
        if(await request("Cloud AI is unavailable. Your cloud settings are still saved.")) {row.remove();await retry();}
        else button.disabled=false;
      } catch(error) {row.append(element("p","error",error.message));button.disabled=false;}
    };
    button.onclick=choose;
    row.append(button);message.root.append(row);
    if(message.root.isConnected) void choose();
  }
  document.addEventListener("DOMContentLoaded",()=>{
    const group=document.createElement("optgroup");group.label="This laptop";
    group.append(new Option("Local LLM · offline","local"));provider().append(group);
    $("#checkLocalAI").onclick=check;
    $("#stopLocalAI").onclick=()=>void stop(chatRuns.get(cid),true);
    $("#unloadLocalAI").onclick=()=>void stop(chatRuns.get(cid),true);
    $("#useLocalAI").onclick=async()=>{
      if(await activate()) $("#settingsStatus").textContent="Local AI selected for this session. Cloud settings kept.";
    };
    $("#useCloudAI").onclick=()=>{
      selected=false;provider().value=config.ai?.provider || "chatgpt";
      void updateProvider();render();renderModelSelection();
    };
    provider().addEventListener("change",()=>{
      if(connectionSelected()) {refreshConnection();void check();}
      else if(selected) {selected=false;render();renderModelSelection();}
    });
    $("#localAIModel").onchange=()=>{model=$("#localAIModel").value;if(selected)renderModelSelection();};
    $("#localAIToggle").onclick=async()=>{
      if(selected) {selected=false;render();renderModelSelection();return;}
      if(!await activate()) {activeSettings="ai";openSettings();provider().value="local";void updateProvider();}
    };
    $("#continueOfflineAI").onclick=async()=>{
      $("#continueOfflineAI").disabled=true;
      const waiter=pending;
      if(await activate(()=>pending===waiter && $("#offlineAIDialog").open)) {
        const resolve=pending;pending=null;$("#offlineAIDialog").close();resolve?.(true);
      } else {
        $("#offlineAIStatus").textContent=$("#localAIMessage").textContent;
        $("#offlineAIStatus").className="hint warning";
      }
    };
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
    setEnabled(value){capable=value!==false;if(!capable)selected=false;render();}});
})();
