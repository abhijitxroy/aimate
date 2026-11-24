function renderGitHubGuidance(message, guidance) {
  if (!guidance) return;
  const row=element("div","source-recovery");
  row.append(element("small","hint",guidance.message));
  const button=element("button","",guidance.action==="validate_repository" && access.configure ? "Validate & review repository" : "Check GitHub connection");
  button.type="button";
  button.onclick=async()=>{
    if (guidance.action!=="validate_repository" || !access.configure) {
      activeSettings="github"; openSettings(); return;
    }
    button.disabled=true;
    try {
      const card=await api(`/api/conversations/${message.conversationId}/repository-proposal`,{
        method:"POST",body:JSON.stringify({repo:guidance.repo})});
      drawAction(card,message.root);
      button.textContent="Access verified · confirm below";
    } catch(error) { button.disabled=false; row.append(element("p","error",error.message)); }
  };
  row.append(button); message.root.append(row);
}
