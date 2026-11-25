/* Optional message timestamps. Saved turn times remain authoritative. */
(() => {
  "use strict";
  const short=new Intl.DateTimeFormat(undefined,{hour:"2-digit",minute:"2-digit"});
  const full=new Intl.DateTimeFormat(undefined,{dateStyle:"medium",timeStyle:"long"});
  const enabled=()=>window.AiMateFeatures?.messageTime !== false;
  function update(message,seconds=message.created) {
    if (!enabled() || !Number.isFinite(Number(seconds)) || Number(seconds)<=0) return;
    const date=new Date(Number(seconds)*1000);
    if (!Number.isFinite(date.getTime())) return;
    message.created=Number(seconds);
    if (!message.meta) {
      message.meta=document.createElement("div");message.meta.className="message-meta";
      message.clock=document.createElement("time");message.clock.className="message-time";
      message.meta.append(message.clock);message.root.append(message.meta);
    }
    message.clock.dateTime=date.toISOString();
    message.clock.textContent=short.format(date);
    message.clock.title=full.format(date);
    message.clock.setAttribute("aria-label",full.format(date));
  }
  function placeModel(message,node) {
    update(message);
    if (enabled() && message.meta) message.meta.prepend(node);
    else message.root.append(node);
  }
  window.AiMateMessageTime=Object.freeze({update,placeModel});
})();
