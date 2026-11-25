/* Small optional explanations; never change a field value or submit a form. */
(() => {
  "use strict";
  if (window.AiMateFeatures?.fieldHelp === false) return;
  let current;
  function close() {
    if (!current) return;
    document.getElementById(current.dataset.fieldHelp).hidden=true;
    current.setAttribute("aria-expanded","false");current=null;
  }
  document.addEventListener("click",event=>{
    const button=event.target.closest("[data-field-help]");
    if (button) {
      event.preventDefault();
      const open=button !== current;close();
      if (open) {
        current=button;document.getElementById(button.dataset.fieldHelp).hidden=false;
        button.setAttribute("aria-expanded","true");
      }
    } else if (current && !document.getElementById(current.dataset.fieldHelp).contains(event.target)) close();
  });
  document.addEventListener("keydown",event=>{
    if (event.key === "Escape" && current) {close();event.preventDefault();}
  });
  document.addEventListener("close",close,true);
})();
