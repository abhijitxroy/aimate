/* Independent review UI; existing feedback capture remains available when disabled. */
window.AiMateFeedbackReview=(()=>{
  let entries=[],canReview=false,next=0;
  const states=["new","investigating","planned","resolved","closed"];
  const assessments={unverified:"Not verified",helpful:"Helpful",confirmed_issue:"Confirmed issue",already_available:"Already available",needs_information:"Needs information"};
  const enabled=()=>window.AiMateFeatures?.feedbackReview!==false;
  function select(values,current,label) {
    const node=element("select","");node.setAttribute("aria-label",label);
    for(const [value,name] of Object.entries(values)) {
      const option=element("option","",name);option.value=value;option.selected=value===current;node.append(option);
    }
    return node;
  }
  function render() {
    const list=$("#feedbackReviews"),filter=$("#feedbackReviewFilter").value;
    const openIDs=new Set([...list.querySelectorAll("details[open]")].map(card=>card.dataset.feedbackId));list.replaceChildren();
    for(const entry of entries.filter(row=>filter==="all" || row.state===filter)) {
      const card=element("details","feedback-review-card"),summary=element("summary","");
      card.dataset.feedbackId=entry.id;card.open=openIDs.has(entry.id);
      summary.append(element("span",entry.rating==="positive" ? "success" : "warning",entry.rating==="positive" ? "Helpful" : "Needs work"),
        element("span","",entry.category.replaceAll("_"," ")),element("small","hint",entry.state));
      card.append(summary);
      const comment=element("div","message-body");renderAnswer(comment,entry.comment || "No comment supplied.");card.append(comment);
      if(entry.reply) {
        const reply=element("div","feedback-review-reply message-body");renderAnswer(reply,entry.reply);
        card.append(element("small","hint","Reviewer reply · "+(assessments[entry.assessment] || "Not verified")),reply);
      }
      if(canReview) {
        const form=element("form","feedback-review-form");
        const fields=element("div","fields two");
        const state=select(Object.fromEntries(states.map(value=>[value,value[0].toUpperCase()+value.slice(1)])),entry.state,"Feedback state");
        const assessment=select(assessments,entry.assessment,"Reviewer assessment");
        for(const [name,input] of [["State",state],["Assessment",assessment]]) {const label=element("label","",name);label.append(input);fields.append(label);}
        const reply=element("textarea","");reply.rows=3;reply.maxLength=2000;reply.value=entry.reply;reply.setAttribute("aria-label","Reviewer reply");reply.placeholder="Explain the fix, existing feature, or next step…";
        const evidence=element("textarea","");evidence.rows=2;evidence.maxLength=2000;evidence.value=entry.evidence;evidence.setAttribute("aria-label","Review evidence");evidence.placeholder="Evidence or task link · required for confirmed issues";
        const actions=element("div","knowledge-actions"),save=element("button","primary","Save review"),task=element("button","",entry.task ? "Open To-do" : "Add to To-do"),error=element("p","error");
        save.type="submit";task.type="button";task.disabled=!entry.task && entry.assessment!=="confirmed_issue";error.setAttribute("role","alert");
        form.onsubmit=async event=>{
          event.preventDefault();save.disabled=true;error.textContent="";
          try {await api(`/api/feedback/${entry.id}/review`,{method:"PATCH",body:JSON.stringify({state:state.value,assessment:assessment.value,reply:reply.value,evidence:evidence.value})});await open();}
          catch(e) {error.textContent=e.message;}
          finally {save.disabled=false;}
        };
        task.onclick=async()=>{
          if(entry.task) {$("#feedbackReviewsDialog").close();$("#settingsDialog").close();$("#openTodos").click();return;}
          task.disabled=true;
          try {await api(`/api/feedback/${entry.id}/task`,{method:"POST"});await open();}
          catch(e) {error.textContent=e.message;task.disabled=false;}
        };
        actions.append(save,task);form.append(fields,reply,evidence,actions,error);card.append(form);
      }
      list.append(card);
    }
    if(!list.children.length) list.append(element("p","hint","No feedback in this view."));
    $("#feedbackReviewMore").hidden=!next;
  }
  async function load(more=false) {
    const data=await api("/api/feedback/reviews?before="+(more ? next : 0));
    entries=more ? entries.concat(data.entries) : data.entries;next=data.next_before || 0;canReview=data.can_review;
    render();
  }
  async function open() {
    try {await load();$("#feedbackReviewsError").textContent="";if(!$("#feedbackReviewsDialog").open) $("#feedbackReviewsDialog").showModal();}
    catch(error) {$("#activity").textContent=error.message;$("#feedbackReviewsError").textContent=error.message;}
  }
  document.addEventListener("DOMContentLoaded",()=>{
    const original=$("#openFeedbackLog").onclick;
    $("#openFeedbackLog").onclick=()=>enabled() ? open() : original();
    $("#openMyFeedback").onclick=open;
    $("#feedbackReviewFilter").onchange=render;
    $("#feedbackReviewMore").onclick=async()=>{try {await load(true);} catch(error) {$("#feedbackReviewsError").textContent=error.message;}};
  });
  return Object.freeze({open,enabled});
})();
