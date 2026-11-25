/* Optional editable Markdown styling. Plain textarea remains the fallback. */
(() => {
  "use strict";
  if(window.AiMateFeatures?.richComposer===false || window.AiMateFeatures?.composerFormatting===false ||
     !window.AiMateRichComposerCore) return;
  const source=document.querySelector("#question");
  if(!source || source.tagName!=="TEXTAREA") return;
  try {
    const editor=window.AiMateRichComposerCore.attach(source);
    window.AiMateRichComposer=Object.freeze({enabled:true,fit:()=>{},reveal:editor.reveal});
  } catch {
    document.querySelector(".rich-composer")?.remove();
    source.id="question";source.hidden=false;source.required=true;
  }
})();
