/* Selected knowledge import. Does not run AI, scan whole repos or fetch images. */
document.addEventListener("DOMContentLoaded",()=>{
  const section=document.createElement("details");
  section.id="knowledgeIndexSection";section.hidden=true;
  section.innerHTML='<summary>Knowledge index</summary><p class="hint">Selected committed Markdown only. Past notes need current-source verification.</p><form id="knowledgeIndexForm"><label>Connected source<select id="knowledgeIndexSource"></select></label><label>Markdown paths · one per line<textarea id="knowledgeIndexPaths" rows="3" placeholder="docs/05-knowledge/runbooks/triage-a-failed-ci-build.md"></textarea></label><button type="submit">Index selected documents</button></form><p id="knowledgeIndexStatus" class="hint" role="status"></p><div id="knowledgeIndexEntries"></div>';
  document.querySelector("#localEvidenceDialog").append(section);
  const status=section.querySelector("#knowledgeIndexStatus");
  const picker=section.querySelector("#knowledgeIndexSource");
  const form=section.querySelector("form");
  let version=0;
  async function refresh() {
    const current=++version;
    if(!access.knowledge_index)return;
    try {
      const sources=(await api("/api/local-evidence")).sources;
      if(current!==version || !access.knowledge_index)return;
      picker.replaceChildren(...sources.map(row=>new Option(row.name,row.name)));
      if(sources.some(row=>row.name==="nexus"))picker.value="nexus";
      const records=await api("/api/knowledge-index");
      if(current!==version || !access.knowledge_index)return;
      const list=section.querySelector("#knowledgeIndexEntries");list.replaceChildren();
      for(const row of records.entries) {
        const item=document.createElement("details"),title=document.createElement("summary");
        title.textContent=row.title+" · "+row.status;
        const meta=document.createElement("small");meta.className="hint";meta.textContent=row.alias+" / "+row.path+" · "+row.commit.slice(0,8);
        const preview=document.createElement("pre");preview.style.whiteSpace="pre-wrap";preview.style.overflowWrap="anywhere";
        const read=document.createElement("button");read.type="button";read.textContent="Read document";
        read.onclick=async()=>{
          read.disabled=true;
          try {
            let start=0,text="",latest;
            do {
              latest=await api("/api/knowledge-index/"+encodeURIComponent(row.id)+"?start="+start);
              text+=latest.data.text;start=latest.data.next_start;
            } while(start!==null);
            preview.textContent=text;
            meta.textContent=row.alias+" / "+row.path+" · "+row.commit.slice(0,8)+
              (latest.data.source_changed ? " · newer commit available; reindex" : " · pinned committed reference");
          } catch(error) {preview.textContent=error.message;}
          finally {read.disabled=false;}
        };
        item.append(title,meta,read,preview);list.append(item);
      }
      if(!records.entries.length)list.textContent="No documents indexed.";
    } catch(error) {status.textContent=error.message;status.className="hint warning";}
  }
  form.onsubmit=async event=>{
    event.preventDefault();const button=form.querySelector("button");button.disabled=true;
    status.textContent="Indexing selected documents…";status.className="hint";
    try {
      const paths=section.querySelector("#knowledgeIndexPaths").value.split("\n").map(value=>value.trim()).filter(Boolean);
      const result=await api("/api/knowledge-index",{method:"POST",body:JSON.stringify({source:picker.value,paths})});
      status.textContent=result.message+" · "+result.indexed+" documents";status.className="hint success";
      await refresh();
    } catch(error) {status.textContent=error.message;status.className="hint warning";}
    finally {button.disabled=false;}
  };
  document.addEventListener("aimate:state",()=>{section.hidden=!access.knowledge_index;});
  section.addEventListener("toggle",()=>{if(section.open)void refresh();});
});
