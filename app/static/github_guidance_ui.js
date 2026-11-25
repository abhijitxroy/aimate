function renderGitHubGuidance(message, guidance) {
  if (!guidance) return;
  const panel=guidance.read_verified ? message.root : evidencePanel(message);
  if ([...panel.querySelectorAll(".source-recovery")].some(row=>
    row.dataset.repository===guidance.repo.toLowerCase() && row.dataset.recovery===guidance.action)) return;
  const row=element("div","source-recovery");
  row.dataset.repository=guidance.repo.toLowerCase();
  row.dataset.recovery=guidance.action;
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
      row.dataset.proposal=card.id;
      drawAction(card,message.root);
      button.textContent="Access verified · confirm below";
      finishRepositoryGuidance(actionStates.get(card.id) || card,message.root);
    } catch(error) { button.disabled=false; row.append(element("p","error",error.message)); }
  };
  row.append(button); panel.append(row);
}

function finishRepositoryGuidance(action, root) {
  if (!root || action.service!=="settings" || action.operation!=="update_github_repositories" ||
      !["completed","cancelled","expired","superseded"].includes(action.status)) return;
  const repo=action.preview?.repository?.toLowerCase();
  for (const row of root.querySelectorAll(".source-recovery")) {
    if (row.dataset.proposal===action.id ||
        action.status==="completed" && row.dataset.repository===repo &&
        row.dataset.recovery==="validate_repository") row.remove();
  }
}
