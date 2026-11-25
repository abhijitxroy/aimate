/* Optional sidebar limits; no API calls, stored data changes or AI requests. */
((root) => {
  "use strict";
  const expanded=new Set(), limit=5;
  function view(threads,key,current) {
    if (root.AiMateFeatures?.recentChats === false)
      return {items:threads,more:false,expanded:false};
    const sorted=[...threads].sort((a,b)=>Number(Boolean(b.pinned))-Number(Boolean(a.pinned)) ||
      Number(b.last_activity ?? b.created ?? 0)-Number(a.last_activity ?? a.created ?? 0));
    const compact=sorted.filter((thread,index)=>index<limit || thread.pinned || thread.id===current);
    const open=expanded.has(key);
    return {items:open ? sorted : compact,more:compact.length<sorted.length,expanded:open};
  }
  function control(node,key,selection,refresh,label) {
    if (!selection.more) return;
    const button=root.document.createElement("button");
    button.type="button";button.className="recent-chats-toggle";button.dataset.recentList=key;
    button.textContent=selection.expanded ? "Show less" : "Show more";
    button.setAttribute("aria-expanded",String(selection.expanded));
    button.setAttribute("aria-label",button.textContent+" chats in "+label);
    button.onclick=()=>{
      if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
      refresh();
      [...root.document.querySelectorAll("[data-recent-list]")]
        .find(item=>item.dataset.recentList===key)?.focus({preventScroll:true});
    };
    node.append(button);
  }
  const api=Object.freeze({view,control,toggle(key) {
    if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
  }});
  if (typeof module !== "undefined" && module.exports) module.exports=api;
  else root.AiMateRecentChats=api;
})(typeof window === "undefined" ? globalThis : window);
