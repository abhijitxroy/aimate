(() => {
  let current=null;
  const host=document.createElement("div");
  host.className="import-progress";host.hidden=true;
  host.innerHTML='<div class="import-progress-track" role="progressbar" aria-label="Attachment import"><span></span></div><div class="import-progress-caption"><small aria-live="polite"></small><button type="button">Cancel</button></div>';
  document.querySelector(".composer-wrap").prepend(host);
  const bar=host.querySelector('[role="progressbar"]'),label=host.querySelector("small"),cancel=host.querySelector("button");
  function changed() {window.dispatchEvent(new Event("aimate-import-state"));}
  cancel.onclick=()=>current?.abort();
  function stage(operation,name,loaded,total) {
    if(current!==operation || operation.signal.aborted) return;
    host.hidden=false;label.textContent=name;
    const known=Number.isFinite(total) && total>0;
    host.classList.toggle("indeterminate",!known);
    if(known) {
      const percent=Math.max(0,Math.min(100,Math.round(loaded/total*100)));
      bar.setAttribute("aria-valuemin","0");bar.setAttribute("aria-valuemax","100");bar.setAttribute("aria-valuenow",String(percent));
      host.querySelector("span").style.width=percent+"%";
    } else {bar.removeAttribute("aria-valuenow");host.querySelector("span").style.width="35%";}
    bar.setAttribute("aria-valuetext",name);
  }
  window.AiMateImportProgress=Object.freeze({
    busy:()=>Boolean(current),
    begin() {
      const operation=new AbortController();
      if(window.AiMateFeatures?.importProgress===false) return operation;
      current=operation;cancel.hidden=false;host.hidden=false;changed();
      stage(operation,"Reading attachment…");
      return operation;
    },
    stage,
    finish(operation) {
      if(current!==operation) return;
      current=null;host.hidden=true;changed();
    }
  });
})();
