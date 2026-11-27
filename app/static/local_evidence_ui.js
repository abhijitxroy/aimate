/* Desktop-owner folder connections; reads remain behind server-side scope checks. */
document.addEventListener("DOMContentLoaded",()=>{
  let sources=[];
  const open=document.createElement("button");
  open.id="openLocalEvidence";open.type="button";open.textContent="Local evidence";open.hidden=true;
  document.querySelector("#openMaintenance")?.after(open);
  const dialog=document.querySelector("#localEvidenceDialog");
  const syncAccess=()=>{open.hidden=!access.local_evidence;};
  document.addEventListener("aimate:state",syncAccess);
  syncAccess();
  function render() {
    const list=document.querySelector("#localEvidenceSources");list.replaceChildren();
    for(const source of sources) {
      const card=document.createElement("div");card.className="knowledge-card";
      const name=document.createElement("strong"),path=document.createElement("p"),remove=document.createElement("button");
      name.textContent=source.name;path.textContent=source.path;path.className="hint";path.style.overflowWrap="anywhere";
      remove.textContent="Disconnect";remove.type="button";
      remove.onclick=async()=>{
        try {
          const result=await api("/api/local-evidence",{method:"PUT",body:JSON.stringify({sources:sources.filter(item=>item.name!==source.name)})});
          sources=result.sources;render();document.querySelector("#localEvidenceStatus").textContent="Folder disconnected.";
        } catch(error) {document.querySelector("#localEvidenceError").textContent=error.message;}
      };
      card.append(name,path,remove);list.append(card);
    }
    if(!sources.length) list.textContent="No local folders connected.";
  }
  open.onclick=async()=>{
    document.querySelector("#localEvidenceError").textContent="";
    try {
      sources=(await api("/api/local-evidence")).sources;render();dialog.showModal();
    } catch(error) {document.querySelector("#settingsStatus").textContent=error.message;}
  };
  document.querySelector("#localEvidenceForm").onsubmit=async event=>{
    event.preventDefault();
    try {
      const candidate={name:document.querySelector("#localEvidenceName").value.trim(),
        path:document.querySelector("#localEvidencePath").value.trim()};
      const result=await api("/api/local-evidence",{method:"PUT",body:JSON.stringify({sources:[...sources.filter(item=>item.name!==candidate.name),candidate]})});
      sources=result.sources;render();event.target.reset();
      document.querySelector("#localEvidenceError").textContent="";
      document.querySelector("#localEvidenceStatus").textContent=result.message;
    } catch(error) {document.querySelector("#localEvidenceError").textContent=error.message;}
  };
});
