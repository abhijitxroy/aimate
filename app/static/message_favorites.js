window.AiMateMessageFavorites=(()=>{
  const enabled=()=>window.AiMateFeatures?.messageFavorites!==false;
  function update(message,role,pinned) {
    const button=message.root.querySelector("[data-message-favorite]") || message.favoriteButton;
    if(!button) return;
    button.dataset.pinned=String(Boolean(pinned));button.setAttribute("aria-pressed",String(Boolean(pinned)));
    button.disabled=Boolean(pinned) && window.AiMateRecordLocks?.isLocked("favorites")!==false;
    button.title=(pinned ? "Unpin" : "Pin")+" message";
    button.setAttribute("aria-label",(pinned ? "Unpin" : "Pin")+(role==="user" ? " your message" : " AiMate reply"));
  }
  function install(message,role,heading) {
    if(!enabled()) return;
    const button=element("button","message-action message-favorite");
    button.type="button";button.dataset.messageFavorite=role;
    button.innerHTML='<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m12 3 2.8 5.8 6.4.9-4.6 4.5 1.1 6.3-5.7-3-5.7 3 1.1-6.3-4.6-4.5 6.4-.9Z"/></svg>';
    message.favoriteButton=button;heading.append(button);update(message,role,false);
    button.onclick=async()=>{
      if(privateChat || !message.turnId || chatRuns.get(message.conversationId)) {$("#activity").textContent="Pin a saved, completed message. Private chats do not save favorites.";return;}
      button.disabled=true;
      try {
        const pinned=button.dataset.pinned!=="true";
        if(!pinned && window.AiMateRecordLocks?.isLocked("favorites")!==false)throw new Error("Unlock Favorites to remove a pin.");
        await api(`/api/conversations/${message.conversationId}/favorites/${message.turnId}/${role}`,{method:"POST",body:JSON.stringify(pinned ? {pinned} : {pinned,confirm_unpin:true})});
        update(message,role,pinned);$("#activity").textContent=pinned ? "Message pinned to Favorites." : "Message unpinned.";
      } catch(error) {$("#activity").textContent=error.message;}
      finally {update(message,role,button.dataset.pinned==="true");}
    };
  }
  return Object.freeze({enabled,install,update});
})();
document.addEventListener("DOMContentLoaded",()=>{
  $("#openFavorites").onclick=async()=>{
    try {
      window.AiMateRecordLocks?.lock("favorites");
      const list=$("#favoriteMessages");list.replaceChildren();
      async function load(before=0) {
      const result=await api("/api/favorites?before_turn="+before);
      for(const entry of result.entries) {
        const card=element("article","knowledge-card"),body=element("div","message-body"),actions=element("div","knowledge-actions");
        renderAnswer(body,entry.text);
        const open=element("button","","Open chat"),copy=element("button","","Copy"),remove=element("button","","Unpin");
        for(const button of [open,copy,remove]) button.type="button";
        remove.dataset.favoriteRemove="";remove.disabled=window.AiMateRecordLocks?.isLocked("favorites")!==false;
        open.onclick=async()=>{
          $("#favoritesDialog").close();await openConversation(entry.conversation);
          const message=[...$("#messages").children].find(node=>node.dataset.turnId===String(entry.turn) && node.classList.contains(entry.role));
          message?.scrollIntoView({block:"center"});message?.classList.add("history-match");
        };
        copy.onclick=async()=>{try {await copyFormatted(entry.text);} catch(error) {$("#favoritesError").textContent=error.message;}};
        remove.onclick=async()=>{
          try {
            if(window.AiMateRecordLocks?.isLocked("favorites")!==false)throw new Error("Unlock Favorites to remove a pin.");
            await api(`/api/conversations/${entry.conversation}/favorites/${entry.turn}/${entry.role}`,{method:"POST",body:'{"pinned":false,"confirm_unpin":true}'});
            card.remove();
            const visible=[...$("#messages").children].find(node=>node.dataset.turnId===String(entry.turn) && node.classList.contains(entry.role));
            if(visible) window.AiMateMessageFavorites.update({root:visible},entry.role,false);
          } catch(error) {$("#favoritesError").textContent=error.message;}
        };
        actions.append(open,copy,remove);card.append(element("h3","",entry.title),element("small","hint",entry.role==="user" ? "You" : "AiMate"),body,actions);list.append(card);
      }
      if(result.next_before_turn) {
        const more=element("button","","Show more");more.type="button";more.onclick=async()=>{
          more.disabled=true;
          try {more.remove();await load(result.next_before_turn);}
          catch(error) {$("#favoritesError").textContent=error.message;list.append(more);more.disabled=false;}
        };list.append(more);
      }
      }
      await load();
      if(!list.children.length) list.append(element("p","hint","Pin a saved message with its star icon."));
      $("#favoritesError").textContent="";$("#favoritesDialog").showModal();
    } catch(error) {$("#activity").textContent=error.message;}
  };
});
document.addEventListener("aimate:record-lock",event=>{
  if(event.detail!=="favorites")return;
  const locked=window.AiMateRecordLocks?.isLocked("favorites")!==false;
  for(const button of document.querySelectorAll('[data-message-favorite][data-pinned="true"],[data-favorite-remove]'))button.disabled=locked;
});
