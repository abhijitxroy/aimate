/* Accidental-edit guard, independent for each personal-record dialog. */
(() => {
  "use strict";
  const locked = {diary:true,todos:true,favorites:true};
  const controls = new Map();
  function set(kind,value) {
    if (!(kind in locked)) throw new Error("Unknown record section");
    locked[kind] = value;
    const button = controls.get(kind);
    if (button) {
      const title = (value ? "Unlock" : "Lock") + ({diary:" My Diary",todos:" To-do",favorites:" Favorites"}[kind]) + " editing and deletion";
      button.title = title; button.setAttribute("aria-label",title);
      button.setAttribute("aria-pressed",String(!value));
      button.dataset.locked = String(value);
      button.querySelector(".record-lock-shackle").setAttribute("d",value ? "M7 11V7a5 5 0 0 1 10 0v4" : "M7 11V7a5 5 0 0 1 9-3");
    }
    document.dispatchEvent(new CustomEvent("aimate:record-lock",{detail:kind}));
  }
  window.AiMateRecordLocks = {isLocked:kind => locked[kind] !== false, lock:kind => set(kind,true)};
  document.addEventListener("DOMContentLoaded",() => {
    for (const [kind,id] of [["diary","knowledgeDialog"],["todos","todoDialog"],["favorites","favoritesDialog"]]) {
      const header = document.querySelector("#"+id+" .dialog-head");
      const group = document.createElement("div"); group.className = "record-head-actions";
      const button = document.createElement("button"); button.type = "button";
      button.className = "record-lock"; button.id = kind+"EditLock";
      // Fixed local SVG, matching text colour and icon size.
      button.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path class="record-lock-shackle" d="M7 11V7a5 5 0 0 1 10 0v4"/><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M12 15v2"/></svg>';
      button.onclick = () => { if (access.manage_records) set(kind,!locked[kind]); };
      controls.set(kind,button); group.append(button,header.querySelector(".close")); header.append(group);
      set(kind,true);
    }
  });
  document.addEventListener("aimate:state",() => {
    for (const button of controls.values()) button.disabled = !access.manage_records;
  });
})();
