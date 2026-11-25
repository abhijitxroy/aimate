/* Per-request local choice; cloud settings are never overwritten or auto-switched. */
window.AiMateLocalAI=(()=>{
  let selected=false,model="qwen3:4b",available=false,capable=false;
  const enabled=()=>window.AiMateFeatures?.localAI!==false;
  function render() {
    $("#localAIToggle").hidden=!enabled() || !capable;
    $("#localAIToggle").disabled=busy;
    $("#localAIToggle").setAttribute("aria-pressed",String(selected));
    $("#localAIToggle").textContent=selected ? "Local" : "Cloud";
    $("#localAIToggle").title=selected ? `Local model · ${model}. Cloud AI is off; connectors still need network/VPN.` : "Use cloud AI. Click to choose a local model instead.";
    $("#localAISettings").hidden=!enabled() || !capable;
  }
  async function check() {
    $("#localAIMessage").textContent="Checking Ollama…";
    try {
      const result=await api("/api/local-ai/status");
      available=result.available && result.models.length>0;
      const picker=$("#localAIModel");picker.replaceChildren();
      for(const name of result.models) picker.append(new Option(name,name));
      if(result.models.includes(model)) picker.value=model;
      else if(result.models.length) model=picker.value;
      $("#localAIMessage").textContent=result.message+
        (result.available && !result.models.length ? " No models installed. Run: ollama pull qwen3:4b" : "");
      $("#localAIMessage").className=available ? "hint success" : "hint warning";
      $("#useLocalAI").disabled=!available;
    } catch(error) {available=false;$("#localAIMessage").textContent=error.message;$("#useLocalAI").disabled=true;}
    return available;
  }
  async function activate() {
    if(!available && !await check()) return false;
    model=$("#localAIModel").value;selected=true;
    if($("#modelMode").value==="analysis") $("#modelMode").value="auto";
    render();renderModelSelection();return true;
  }
  function offer(message,retry) {
    if(!enabled() || !capable || message.root.querySelector(".local-ai-offer")) return;
    const row=element("div","source-recovery local-ai-offer");
    row.append(element("small","hint","Cloud AI is unavailable. Continue with a local model? Saved context may be stale; service reads still need network/VPN."));
    const button=element("button","","Continue with local AI");button.type="button";
    button.onclick=async()=>{
      button.disabled=true;
      try {
        if(await activate()) {row.remove();await retry();}
        else {row.append(element("p","warning",$("#localAIMessage").textContent));button.disabled=false;}
      } catch(error) {row.append(element("p","error",error.message));button.disabled=false;}
    };
    row.append(button);message.root.append(row);
  }
  document.addEventListener("DOMContentLoaded",()=>{
    $("#checkLocalAI").onclick=check;
    $("#useLocalAI").onclick=async()=>{await activate();};
    $("#useCloudAI").onclick=()=>{selected=false;render();renderModelSelection();};
    $("#localAIModel").onchange=()=>{model=$("#localAIModel").value;if(selected)renderModelSelection();};
    $("#localAIToggle").onclick=async()=>{
      if(selected) {selected=false;render();renderModelSelection();return;}
      if(!await activate()) {activeSettings="ai";openSettings();$("#localAISettings").open=true;}
    };
    render();
  });
  document.addEventListener("aimate:state",render);
  return Object.freeze({active:()=>selected && enabled() && capable,model:()=>model,offer,
    setEnabled(value){capable=value!==false;if(!capable)selected=false;render();}});
})();
