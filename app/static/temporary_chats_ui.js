/* Optional temporary-chat lifetime control; no transcript in browser storage. */
window.AiMateTemporaryChats=(()=>{
  "use strict";
  const page=crypto.randomUUID();
  let available=window.AiMateFeatures?.temporaryChats!==false, picker;
  function paint() {
    if(picker) {
      picker.hidden=!available || document.querySelector("#privateToggle").getAttribute("aria-pressed")!=="true";
      picker.disabled=Boolean(cid && privateChat) || busy;
    }
  }
  function options() {return available ? {lifetime:picker?.value || "session",page} : undefined;}
  function restore(chat) {
    if(picker) picker.value=chat.temporary==="day" ? "day" : "session";
    paint();
  }
  function setEnabled(value) {available=value && window.AiMateFeatures?.temporaryChats!==false;paint();}
  function install() {
    const toggle=document.querySelector("#privateToggle");
    if(!toggle || !available) return;
    picker=document.createElement("select");picker.id="temporaryLifetime";
    picker.setAttribute("aria-label","Temporary chat lifetime");
    picker.title="Session: ends when this tab closes or reloads. One day: up to 24 hours in memory. Sign-out, 12-hour login expiry or server restart ends either mode earlier.";
    picker.add(new Option("Lifetime · Session","session"));picker.add(new Option("Lifetime · Up to 1 day","day"));
    toggle.after(picker);
    new MutationObserver(paint).observe(toggle,{attributes:true,attributeFilter:["aria-pressed"]});
    window.addEventListener("pagehide",event=>{
      if(!available || event.persisted || !csrf) return;
      fetch("/api/conversations/temporary-close",{method:"POST",credentials:"same-origin",keepalive:true,
        headers:{"content-type":"application/json","x-csrf-token":csrf},body:JSON.stringify({page})}).catch(()=>{});
    });
    paint();
  }
  document.addEventListener("DOMContentLoaded",install);
  return Object.freeze({options,restore,setEnabled});
})();
