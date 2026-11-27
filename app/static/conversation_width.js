/* Optional browser appearance preference. No model, chat or settings mutation. */
window.AiMateConversationWidth = (() => {
  "use strict";
  const key="aimate.chat-width";
  const enabled=()=>window.AiMateFeatures?.conversationWidth!==false;
  function apply(value,{save=true}={}) {
    const view=enabled() && value==="wide" ? "wide" : "current";
    document.documentElement.dataset.chatWidth=view;
    const panel=document.querySelector("#conversationWidthOptions");
    if(panel) {
      panel.hidden=!enabled();
      panel.querySelectorAll("[data-chat-width-choice]").forEach(button=>{
        button.setAttribute("aria-pressed",String(button.dataset.chatWidthChoice===view));
      });
    }
    if(save && enabled()) try { localStorage.setItem(key,view); } catch {}
    window.dispatchEvent(new CustomEvent("aimate-chat-width",{detail:view}));
    return view;
  }
  function init() {
    const dialog=document.querySelector("#appearanceDialog");
    if(!dialog || !enabled()) return;
    const panel=document.createElement("fieldset");
    panel.id="conversationWidthOptions";
    panel.className="chat-width-options";
    const legend=document.createElement("legend");
    legend.textContent="Conversation width";
    panel.append(legend);
    for(const [value,label,hint] of [["current","Current","Comfortable reading"],
      ["wide","Wide","More room for tables and code"]]) {
      const button=document.createElement("button");
      button.type="button";
      button.dataset.chatWidthChoice=value;
      button.setAttribute("aria-label",label+" conversation width");
      const name=document.createElement("strong"),description=document.createElement("small");
      name.textContent=label;description.textContent=hint;
      button.append(name,description);
      button.onclick=()=>apply(value);
      panel.append(button);
    }
    dialog.insertBefore(panel,dialog.querySelector(".theme-options"));
    apply(document.documentElement.dataset.chatWidth,{save:false});
  }
  let saved="current";
  try { saved=localStorage.getItem(key) || saved; } catch {}
  apply(saved,{save:false});
  if(document.readyState==="loading") document.addEventListener("DOMContentLoaded",init,{once:true});
  else init();
  return Object.freeze({apply});
})();
