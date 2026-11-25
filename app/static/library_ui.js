let libraryItems=[],libraryEditId=null;
function resetLibraryEditor() {
  libraryEditId=null; $("#libraryForm").reset(); $("#saveLibrary").textContent="Save prompt";
}
function renderLibrary() {
  const list=$("#libraryItems"),query=$("#librarySearch").value.toLocaleLowerCase(); list.replaceChildren();
  for(const item of libraryItems.filter(item=>(item.title+" "+item.body).toLocaleLowerCase().includes(query))) {
    const card=element("article","knowledge-card");
    const text=element("div","knowledge-value"); renderDataValue(text,item.body);
    const actions=element("div","knowledge-actions");
    const insert=element("button","",item.kind==="prompt" ? "Insert" : "Use style"),copy=element("button","","Copy"),edit=element("button","","Edit"),remove=element("button","error","Delete");
    for(const button of [insert,copy,edit,remove]) button.type="button";
    insert.onclick=async()=>{
      if(item.kind!=="prompt") { await reloadStyles();$("#analysisStyle").value=item.id;$("#libraryDialog").close();$("#knowledgeDialog").close();$("#question").focus();return; }
      const field=$("#question"), room=field.maxLength-field.value.length;
      if(item.body.length>room) { $("#libraryError").textContent="The prompt will not fit. Shorten the current message first."; return; }
      field.setRangeText(item.body,field.selectionStart,field.selectionEnd,"end");
      $("#libraryDialog").close();$("#knowledgeDialog").close();field.focus();
    };
    copy.onclick=async()=>{try{await navigator.clipboard.writeText(item.body);copy.textContent="Copied";}catch{$("#libraryError").textContent="Select the prompt text to copy it."; }};
    edit.onclick=()=>{libraryEditId=item.id;$("#libraryTitle").value=item.title;$("#libraryBody").value=item.body;$("#libraryKind").value=item.kind;$("#saveLibrary").textContent="Save changes";$("#libraryTitle").focus();};
    remove.onclick=async()=>{try{await api(`/api/library/${item.id}`,{method:"DELETE"});if(libraryEditId===item.id)resetLibraryEditor();await loadLibrary();}catch(error){$("#libraryError").textContent=error.message;}};
    actions.append(insert,copy,edit,remove);card.append(element("h3","",item.title),element("small","hint",item.kind),text,actions);list.append(card);
  }
  if(!list.children.length) list.append(element("p","hint",query ? "No matching prompts." : "Save a phrase or prompt you often use."));
}
async function loadLibrary() { libraryItems=(await api("/api/library")).items; renderLibrary(); await reloadStyles(); }
$("#openLibrary").onclick=async()=>{
  $("#libraryError").textContent="";resetLibraryEditor();$("#libraryDialog").showModal();
  try{await loadLibrary();}catch(error){$("#libraryError").textContent=error.message;}
};
$("#newLibrary").onclick=resetLibraryEditor;
$("#librarySearch").oninput=renderLibrary;
$("#libraryForm").onsubmit=async event=>{
  event.preventDefault();$("#saveLibrary").disabled=true;
  try{await api(libraryEditId ? `/api/library/${libraryEditId}` : "/api/library",{
    method:libraryEditId ? "PATCH" : "POST",body:JSON.stringify({title:$("#libraryTitle").value,body:$("#libraryBody").value,kind:$("#libraryKind").value})});
    resetLibraryEditor();await loadLibrary();$("#libraryError").textContent="";
  }catch(error){$("#libraryError").textContent=error.message;}
  finally{$("#saveLibrary").disabled=false;}
};
let styleVersion=0,styleSession="";
async function reloadStyles() {
  const field=$("#analysisStyle");
  if(styleSession!==csrf) {
    styleSession=csrf;field.replaceChildren();
    libraryItems=[];libraryEditId=null;$("#libraryItems").replaceChildren();$("#libraryForm").reset();
    for(const [id,title] of [["auto","Style · Auto"],["plain","Plain"]]) {const option=element("option","",title);option.value=id;field.append(option);}
  }
  const version=++styleVersion,selected=field.value,sessionCsrf=csrf;
  try {
    const result=await api("/api/library/styles");
    if(version!==styleVersion || sessionCsrf!==csrf)return;
    field.replaceChildren();
    for(const [id,title] of [["auto","Style · Auto"],["plain","Plain"],...result.styles.map(item=>[item.id,item.title])]) {
      const option=element("option","",title);option.value=id;field.append(option);
    }
    field.value=[...field.options].some(option=>option.value===selected) ? selected : "auto";
  }catch{ /* sign-in/state refresh retries the account's styles */ }
}
document.addEventListener("aimate:state",()=>void reloadStyles());
void reloadStyles();
