/* Optional, local-only message navigation. Uses the existing Favorites permission gate. */
(() => {
function installMessageNavigation() {
  "use strict";
  const box=document.querySelector("#messages"), main=box.closest("main");
  const enabled=()=>window.AiMateFeatures?.messageNavigation!==false;
  if (!enabled()) return;
  if (main.querySelector(".message-rail")) return;
  const rail=document.createElement("nav");rail.className="message-rail";rail.hidden=true;
  rail.setAttribute("aria-label","Message navigation");
  const preview=document.createElement("section");preview.className="message-rail-preview";preview.hidden=true;
  preview.setAttribute("aria-label","Message preview");
  const heading=document.createElement("div"), title=document.createElement("strong");
  const pin=document.createElement("button");pin.type="button";pin.className="message-rail-bookmark";
  pin.innerHTML='<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 3h12v18l-6-4-6 4Z"/></svg>';
  heading.append(title,pin);
  const text=document.createElement("p");preview.append(heading,text);main.append(rail,preview);
  let roots=[], markers=[], active=null, frame=0, timer=0;
  const valid=root=>root?.isConnected && root.parentElement===box;
  function close() {clearTimeout(timer);active=null;preview.hidden=true;}
  function updatePreview() {
    if (!valid(active)) {close();return;}
    title.textContent=active.classList.contains("user") ? "You" : "AiMate";
    const content=active.querySelector(".body")?.innerText?.trim() || "No content yet";
    text.textContent=content.length>440 ? content.slice(0,437)+"…" : content;
    const favorite=active.querySelector("[data-message-favorite]");
    const pinned=favorite?.dataset.pinned==="true";
    pin.disabled=!favorite || favorite.disabled;
    pin.setAttribute("aria-pressed",String(pinned));
    pin.setAttribute("aria-label",pinned ? "Unpin message" : "Pin message");
    pin.title=pinned ? "Unpin message" : "Pin message";
  }
  function show(root,marker) {
    if (!valid(root) || !enabled()) return;
    clearTimeout(timer);active=root;preview.hidden=false;updatePreview();
    const mark=marker.getBoundingClientRect(), region=main.getBoundingClientRect();
    const width=Math.min(300,Math.max(180,region.width-45));
    preview.style.width=width+"px";
    preview.style.left=Math.max(6,Math.min(mark.right+10,innerWidth-width-10))+"px";
    preview.style.top=Math.max(8,Math.min(mark.top-14,innerHeight-preview.offsetHeight-12))+"px";
  }
  function leave() {clearTimeout(timer);timer=setTimeout(close,140);}
  pin.onclick=()=>{
    if (!valid(active)) {close();return;}
    active.querySelector("[data-message-favorite]")?.click();
  };
  preview.onpointerenter=()=>clearTimeout(timer);preview.onpointerleave=leave;
  function schedule() {if (!frame) frame=requestAnimationFrame(refresh);}
  function refresh() {
    frame=0;
    if (!enabled()) {rail.hidden=true;close();return;}
    const next=[...box.children].filter(node=>node.matches("article.message"));
    if (next.length!==roots.length || next.some((node,index)=>node!==roots[index])) {
      close();roots=next;rail.replaceChildren();markers=[];
      roots.forEach((root,index)=>{
        const marker=document.createElement("button");marker.type="button";
        marker.setAttribute("aria-label",`${root.classList.contains("user") ? "Your message" : "AiMate reply"} ${index+1}`);
        marker.dataset.messageMarker=String(index);
        marker.onpointerenter=()=>show(root,marker);marker.onpointerleave=leave;
        marker.onfocus=()=>show(root,marker);
        marker.onclick=()=>{
          if (!valid(root)) return;
          box.scrollTo({top:box.scrollTop+root.getBoundingClientRect().top-box.getBoundingClientRect().top-12,
            behavior:matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth"});
          close();
        };
        marker.onkeydown=event=>{
          if (!["ArrowUp","ArrowDown","Home","End"].includes(event.key)) return;
          event.preventDefault();
          const target=event.key==="Home" ? 0 : event.key==="End" ? markers.length-1 :
            Math.max(0,Math.min(markers.length-1,index+(event.key==="ArrowUp" ? -1 : 1)));
          markers[target]?.focus();
        };
        rail.append(marker);markers.push(marker);
      });
    }
    const bounds=box.getBoundingClientRect(), parent=main.getBoundingClientRect();
    rail.style.top=(bounds.top-parent.top+12)+"px";
    // Keep short chats compact; dense histories compress into the available gutter.
    rail.style.height=Math.min(roots.length*10,Math.max(0,bounds.height-24))+"px";
    rail.hidden=roots.length<2 || bounds.height<80;
    let nearest=0, distance=Infinity;
    roots.forEach((root,index)=>{
      const delta=Math.abs(root.getBoundingClientRect().top-bounds.top-12);
      if (delta<distance) {distance=delta;nearest=index;}
      const pinned=root.querySelector("[data-message-favorite]")?.dataset.pinned==="true";
      markers[index].classList.toggle("pinned",pinned);
    });
    markers.forEach((marker,index)=>marker.setAttribute("aria-current",String(index===nearest)));
    if (active) updatePreview();
  }
  new MutationObserver(schedule).observe(box,{childList:true,subtree:true,characterData:true,
    attributes:true,attributeFilter:["data-pinned","disabled"]});
  new ResizeObserver(schedule).observe(box);
  box.addEventListener("scroll",schedule,{passive:true});
  document.addEventListener("pointerdown",event=>{
    if (!rail.contains(event.target) && !preview.contains(event.target)) close();
  });
  document.addEventListener("keydown",event=>{if (event.key==="Escape") close();});
  schedule();
}
if (document.readyState==="loading") document.addEventListener("DOMContentLoaded",installMessageNavigation);
else installMessageNavigation();
})();
