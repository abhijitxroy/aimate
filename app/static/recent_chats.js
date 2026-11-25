/* Optional sidebar limits; no API calls, stored data changes or AI requests. */
((root) => {
  "use strict";
  const expanded=new Set(), counts=new Map(), limit=5;
  const enabled=()=>root.AiMateFeatures?.recentChats !== false;
  function page(threads,key="recents") {
    const sorted=[...threads].sort((a,b)=>
      Number(b.last_activity ?? b.created ?? 0)-Number(a.last_activity ?? a.created ?? 0));
    const count=counts.get(key) || 3;
    return {items:sorted.slice(0,count),more:sorted.length>count,expanded:count>3,total:sorted.length};
  }
  function step(key="recents",reset=false) {
    counts.set(key,reset ? 3 : (counts.get(key) || 3)+5);
  }
  function pageControl(node,key,selection,refresh) {
    if (selection.total<=3) return;
    const controls=root.document.createElement("div");
    controls.className="recent-page-controls";controls.setAttribute("role","group");
    controls.setAttribute("aria-label","Recent chat list size");
    for (const [available,reset,label] of [[selection.more,false,"Show more"],[selection.expanded,true,"Show less"]]) {
      const button=root.document.createElement("button");
      button.type="button";button.className="recent-chats-toggle";
      button.innerHTML=`<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${reset ? "m6 15 6-6 6 6" : "m6 9 6 6 6-6"}"/></svg>`;
      button.append(root.document.createTextNode(label));
      button.disabled=!available;
      button.dataset.recentPage=reset ? "less" : "more";button.dataset.recentPageKey=key;
      button.setAttribute("aria-label",reset ? "Show only three recent chats" : "Show five more recent chats");
      if (node.id) button.setAttribute("aria-controls",node.id);
      button.onclick=()=>{
        step(key,reset);refresh();
        const next=[...root.document.querySelectorAll("[data-recent-page-key]")]
          .find(item=>item.dataset.recentPageKey===key && !item.disabled);
        next?.focus({preventScroll:true});
      };
      controls.append(button);
    }
    node.append(controls);
  }
  function section(key="recents") {
    const node=root.document.createElement("details");
    node.className="recents-section";node.id="recentSection";
    let open=true;
    try {open=root.localStorage?.getItem("aimate."+key+".open") !== "false";} catch {}
    node.open=open;
    const heading=root.document.createElement("summary");
    heading.className="recent-heading";
    heading.innerHTML='<svg class="recents-chevron" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>';
    heading.append(root.document.createTextNode("Recents"));
    function remember() {
      heading.title=node.open ? "Collapse Recents" : "Expand Recents";
      heading.setAttribute("aria-expanded",String(node.open));
      if (!node.isConnected) return;
      try {root.localStorage?.setItem("aimate."+key+".open",String(node.open));} catch {}
    }
    node.append(heading);node.ontoggle=remember;remember();
    return node;
  }
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
  const api=Object.freeze({enabled,page,step,pageControl,section,view,control,toggle(key) {
    if (expanded.has(key)) expanded.delete(key); else expanded.add(key);
  }});
  if (typeof module !== "undefined" && module.exports) module.exports=api;
  else root.AiMateRecentChats=api;
})(typeof window === "undefined" ? globalThis : window);
