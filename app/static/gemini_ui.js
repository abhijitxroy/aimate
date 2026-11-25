/* Optional Vertex settings; secrets never leave this form except to AiMate. */
window.AiMateGeminiUI=(()=>{
  "use strict";
  let catalog=null,loading=null;
  const allowed=()=>window.AiMateFeatures?.geminiVertex!==false;
  async function refresh() {
    const form=document.querySelector("#settingsForm");
    if(!form) return;
    const chosen=form.elements["ai.provider"].value==="gemini";
    const panel=document.querySelector("#geminiSettings");
    panel.hidden=!chosen;
    document.querySelector("#settings-ai .model-selection").hidden=chosen;
    if(!chosen) return;
    document.querySelector("#apiCredentials").hidden=true;
    document.querySelector("#apiModelLabel").hidden=true;
    document.querySelector("#analysisModelLabel").hidden=true;
    document.querySelector("#removeAIKey").hidden=true;
    if(!form.elements["ai.gcp_location"].value) form.elements["ai.gcp_location"].value="global";
    const secret=form.elements["ai.gcp_credentials"];
    secret.placeholder=config.ai?.gcp_credentials_configured ? "Saved · leave blank to keep" : "Paste the replacement service-account JSON";
    if(!allowed()) {document.querySelector("#geminiHint").textContent="Gemini settings are disabled in this browser.";return;}
    try {
      if(!catalog) {
        loading ||= api("/api/gemini/models").finally(()=>{loading=null;});
        catalog=await loading;
      }
      if(form.elements["ai.provider"].value!=="gemini") return;
      const standard=document.querySelector("#geminiModel"),analysis=document.querySelector("#geminiAnalysisModel");
      const current=form.elements["ai.model"].value,reasoning=form.elements["ai.analysis_model"].value;
      standard.replaceChildren();analysis.replaceChildren(new Option("Use Standard only",""));
      for(const model of catalog.models) {
        standard.add(new Option(model.title,model.id));analysis.add(new Option(model.title,model.id));
      }
      if(current && !catalog.models.some(row=>row.id===current)) standard.add(new Option(current,current));
      if(reasoning && !catalog.models.some(row=>row.id===reasoning)) analysis.add(new Option(reasoning,reasoning));
      standard.value=current || catalog.models[0]?.id || "";
      analysis.value=reasoning || "";
      if(!current) form.elements["ai.model"].value=standard.value;
      document.querySelector("#geminiHint").textContent=catalog.enabled
        ? "Google Cloud · global · service-account JSON. Save & test checks live access."
        : "Gemini is disabled on this server.";
    } catch {
      document.querySelector("#geminiHint").textContent="Could not load Gemini models. Check the local server, then reopen settings.";
    }
  }
  function install() {
    const provider=document.querySelector('[name="ai.provider"]');
    if(!allowed()) {
      const option=provider?.querySelector('[value="gemini"]');
      if(option) {option.disabled=true;option.hidden=true;}
      return;
    }
    const form=document.querySelector("#settingsForm");
    for(const [id,name] of [["geminiModel","model"],["geminiAnalysisModel","analysis_model"]])
      document.querySelector("#"+id).onchange=event=>{
        form.elements["ai."+name].value=event.target.value;
        form.elements["ai."+name].dispatchEvent(new Event("change",{bubbles:true}));
      };
    const upload=document.querySelector("#geminiCredentialFile");
    form.elements["ai.gcp_credentials"].addEventListener("input",()=>{
      try {
        const data=JSON.parse(form.elements["ai.gcp_credentials"].value);
        if(data.type==="service_account" && typeof data.project_id==="string")
          form.elements["ai.gcp_project"].value=data.project_id;
      } catch { /* Leave incomplete pasted JSON for the server's safe validation. */ }
    });
    document.querySelector("#importGeminiCredentials").onclick=()=>upload.click();
    upload.onchange=async()=>{
      const file=upload.files?.[0];upload.value="";
      if(!file) return;
      const status=document.querySelector("#geminiHint");
      if(file.size>20000) {status.textContent="Credential JSON exceeds the 20 KB limit.";return;}
      try {
        const text=await file.text(),data=JSON.parse(text);
        if(data.type!=="service_account" || typeof data.private_key!=="string") throw Error();
        // Keep only in the password field until the user saves. Never preview.
        form.elements["ai.gcp_credentials"].value=text.replace(/\r?\n\s*/g,"");
        form.elements["ai.gcp_project"].value=data.project_id || "";
        form.elements["ai.gcp_credentials"].dispatchEvent(new Event("input",{bubbles:true}));
        status.textContent="JSON loaded. Save & test verifies credentials and model access.";
      } catch {status.textContent="Use a complete Google service-account JSON file.";}
    };
  }
  document.addEventListener("DOMContentLoaded",install);
  return Object.freeze({refresh});
})();
