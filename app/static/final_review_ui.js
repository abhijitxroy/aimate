/* Optional workspace-owned panel. Keys never enter the DOM. */
(() => {
  const host = document.querySelector("#settings-ai");
  if (!host) return;
  const section = document.createElement("details");
  section.id = "finalReviewSettings"; section.hidden = true;
  const summary = document.createElement("summary");
  summary.textContent = "Final PR review panel";
  const note = document.createElement("p"); note.className = "hint";
  const list = document.createElement("div"); list.className = "knowledge-cards";
  const leadLabel = document.createElement("label"); leadLabel.textContent = "Lead model";
  const lead = document.createElement("select"); lead.id = "finalReviewLead"; leadLabel.append(lead);
  function input(label, id, placeholder = "") {
    const wrapper = document.createElement("label"); wrapper.textContent = label;
    const field = document.createElement("input"); field.id = id; field.maxLength = 200; field.placeholder = placeholder;
    wrapper.append(field); return {wrapper, field};
  }
  const {wrapper:nameLabel,field:name} = input("Profile name","finalReviewName","e.g. Organization · Opus");
  name.maxLength = 80;
  const modelLabel=document.createElement("label");modelLabel.textContent="Model";
  const model=document.createElement("select");model.id="finalReviewModel";modelLabel.append(model);
  const scopeLabel = document.createElement("label"); scopeLabel.textContent = "Allowed data";
  const scope = document.createElement("select"); scope.id = "finalReviewScope";
  for (const [value,title] of [["organization","Organization · Intel"],["non-intel","Non-Intel only"]]) {
    const option=document.createElement("option");option.value=value;option.textContent=title;scope.append(option);
  }
  scopeLabel.append(scope);
  const status=document.createElement("p");status.id="finalReviewStatus";status.className="hint";status.setAttribute("role","status");
  function button(text, handler) {
    const node=document.createElement("button");node.type="button";node.textContent=text;
    node.onclick=async()=>{
      node.disabled=true;status.textContent="";
      try {await handler();} catch(error) {status.textContent=error.message;}
      finally {node.disabled=false;}
    };
    return node;
  }
  const buttons=document.createElement("div");buttons.className="knowledge-actions";
  buttons.append(button("Save current connection as profile",async()=>{
    if(dirtyConnections.has("ai")) throw new Error("Save the AI connection first; profiles use saved credentials.");
    await api("/api/settings/final-review/profiles",{method:"POST",body:JSON.stringify({
      name:name.value,scope:scope.value,model:model.value})});
    name.value="";await refresh();
  }),button("Save panel",async()=>{
    const reviewers=[...list.querySelectorAll("input:checked")].map(node=>node.value);
    await api("/api/settings/final-review",{method:"PUT",body:JSON.stringify({reviewers,lead:lead.value})});
    status.textContent="Saved for your workspace. Final PR review will reuse this panel until you change it.";
  }));
  section.append(summary,note,list,leadLabel,nameLabel,modelLabel,scopeLabel,buttons,status);host.append(section);
  // This nested panel owns its inputs; they are not unsaved AI connection edits.
  for(const type of ["input","change"])section.addEventListener(type,event=>event.stopPropagation());
  let generation=0,session="",modelProvider="";
  async function refresh() {
    const request=++generation,expected=csrf,data=await api("/api/settings/final-review");
    if(request!==generation || expected!==csrf)return;
    section.hidden=false;note.textContent=data.notice;list.replaceChildren();lead.replaceChildren();
    const selected=data.selection?.reviewers || [];
    for(const profile of data.profiles) {
      const row=document.createElement("div");row.className="knowledge-card";
      const label=document.createElement("label");label.className="check";
      const check=document.createElement("input");check.type="checkbox";check.value=profile.id;
      check.disabled=!profile.ready;check.checked=selected.includes(profile.id);
      label.append(check,document.createTextNode(`${profile.name} · ${shortModelName(profile.model)}`));
      const info=document.createElement("small");info.className=profile.ready ? "hint success" : "hint";
      info.textContent=`${profile.scope==="organization" ? "Organization" : "Non-Intel"} · ${profile.ready ? "Access checked" : "Not checked"}`;
      if(profile.checked)info.title="Last checked: "+new Date(profile.checked*1000).toLocaleString();
      if(profile.message)info.title=profile.message;
      const actions=document.createElement("div");actions.className="knowledge-actions";
      actions.append(button("Check access",async()=>{
        await api(`/api/settings/final-review/profiles/${profile.id}/test`,{method:"POST"});
        await refresh();status.textContent="The model answered. Access checked.";
      }),button("Remove profile",async()=>{
        await api(`/api/settings/final-review/profiles/${profile.id}`,{method:"DELETE"});await refresh();
      }));
      row.append(label,info,actions);list.append(row);
      if(profile.ready) {
        const option=document.createElement("option");option.value=profile.id;option.textContent=profile.name;lead.append(option);
      }
    }
    const suggested=data.profiles.find(profile=>profile.ready && profile.suggested_lead)?.id;
    if(data.selection?.lead || suggested)lead.value=data.selection?.lead || suggested;
    const previous=modelProvider===config.ai?.provider ? model.value : config.ai?.model;
    modelProvider=config.ai?.provider;model.replaceChildren();
    const configured=[config.ai?.model,config.ai?.analysis_model].filter(Boolean);
    const available=[...(data.models || []),...(config.ai?.provider==="bedrock" ? bedrockCatalog : [])];
    const catalog=config.ai?.provider==="bedrock" ? window.AiMateLatestModels?.choose(available,{
      region:config.ai.region,endpoint:config.ai.bedrock_endpoint,preferred:configured}) || available : available;
    const identities=new Set();
    for(const id of new Set([...configured,...catalog.map(row=>row.id)])) {
      const identity=id.replace(/^(us|global)\./,"");
      if(identities.has(identity))continue;identities.add(identity);
      const option=document.createElement("option");option.value=id;option.textContent=shortModelName(id);option.title=id;
      model.append(option);
    }
    if([...model.options].some(option=>option.value===previous))model.value=previous;
  }
  section.addEventListener("toggle",()=>{if(section.open)void refresh().catch(error=>{status.textContent=error.message;});});
  document.addEventListener("aimate:state",()=>{
    if(session!==csrf) {
      session=csrf;generation++;list.replaceChildren();lead.replaceChildren();name.value="";model.value="";
      status.textContent="";section.open=false;section.hidden=true;
    }
    if(!demo && !pagesPreview)void refresh().catch(()=>{section.hidden=true;});
  });
  queueMicrotask(()=>{
    if(!demo && !pagesPreview && config.ai && !document.querySelector("#workspace").hidden)
      void refresh().catch(()=>{section.hidden=true;});
  });
  window.AiMateFinalReview=Object.freeze({render(message,data){
    if(!data || !Array.isArray(data.reviewers) || message.root.querySelector(".final-review-reports"))return;
    const details=document.createElement("details");details.className="final-review-reports";
    const title=document.createElement("summary");title.textContent=`Independent reviewers · ${data.reviewers.length}`;
    details.append(title);
    if(data.comparison && Array.isArray(data.comparison.entries)) {
      const audit=document.createElement("details");
      const heading=document.createElement("summary");heading.textContent="Lead comparison · finding provenance";
      const body=document.createElement("div");body.className="message-body";
      const note=document.createElement("p");note.className="hint";note.textContent=data.comparison.note;
      const table=document.createElement("table"),head=document.createElement("thead"),labels=document.createElement("tr");
      for(const text of ["Finding","Independent assessments","Lead comparison"]) {
        const cell=document.createElement("th");cell.textContent=text;labels.append(cell);
      }
      head.append(labels);table.append(head);
      const rows=document.createElement("tbody");
      const statuses={retained:"Same cited claim retained",location_only:"Same location; claims may differ",
        omitted:"Not retained; not disproven",unresolved:"Unresolved; lead incomplete",lead_only:"Added by lead"};
      for(const entry of data.comparison.entries) {
        const row=document.createElement("tr");row.dataset.comparisonStatus=entry.status;
        const values=[`${entry.path}:${entry.line} — ${entry.claim}`,
          (entry.reviewers || []).map(value=>`${value.name} · ${value.severity}`).join("; ") || "None",
          (statuses[entry.status] || "Unresolved")+
            (entry.lead_severity ? ` · ${entry.lead_severity}` : "")+
            (entry.severity_disagreement ? " · Severity differs" : "")];
        for(const value of values) {const cell=document.createElement("td");cell.textContent=value;row.append(cell);}
        rows.append(row);
      }
      table.append(rows);body.append(note,table);
      for(const reviewer of data.comparison.incomplete_reviewers || []) {
        const gap=document.createElement("p");gap.className="hint";
        gap.textContent=`${reviewer.name}: no completed independent report.`;body.append(gap);
      }
      audit.append(heading,body);details.append(audit);
    }
    for(const result of data.reviewers) {
      const child=document.createElement("details");
      const heading=document.createElement("summary");heading.textContent=`${result.name} · ${shortModelName(result.model)}`;
      const body=document.createElement("div");
      const summaryText=document.createElement("p");summaryText.textContent=result.report?.summary || result.error || "Incomplete";
      body.append(summaryText);
      for(const finding of result.report?.findings || []) {
        const entry=document.createElement("p");
        entry.textContent=`${finding.severity} · ${finding.path}:${finding.line} — ${finding.claim} ${finding.scenario}`;
        body.append(entry);
      }
      for(const gap of result.report?.gaps || []) {
        const entry=document.createElement("p");entry.className="hint";entry.textContent=gap;body.append(entry);
      }
      child.append(heading,body);details.append(child);
    }
    message.body.after(details);
  }});
})();
