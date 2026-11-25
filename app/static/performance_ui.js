/* Optional measured performance view; never sends prompts or invokes a model. */
window.AiMatePerformance=(()=>{
  const enabled=()=>window.AiMateFeatures?.performanceDashboard!==false;
  let serverEnabled=true,report=null;
  const number=value=>value==null ? "—" : Number(value).toLocaleString(undefined,{maximumFractionDigits:2});
  function render(data,selected) {
    report=data;
    const options=$("#performanceBaseline");options.replaceChildren(new Option("Current sample", ""));
    for(const row of data.baselines) options.append(new Option(row.label+" · "+new Date(row.created*1000).toLocaleString(),row.id));
    options.value=data.baselines.some(row=>row.id===selected) ? selected : "";
    $("#removePerformanceBaseline").disabled=!options.value;
    const stats=$("#performanceStats");stats.replaceChildren();
    const current=data.current,tokens=current.reported_tokens_24h,resource=current.resources;
    for(const [label,value] of [
      ["Requests",number(current.requests)],["Typical · p50",number(current.p50_ms)+" ms"],
      ["Slow · p95",number(current.p95_ms)+" ms"],
      ["Reported tokens · 24h",number(tokens.input_tokens+tokens.output_tokens)],
      ["Process CPU · since start",number(resource.cpu_seconds)+" s"],
      ["Memory · "+resource.memory_kind,number(resource.memory_mb)+" MB"]
    ]) {
      const card=element("div","performance-stat");
      card.append(element("small","hint",label),element("strong","",value));stats.append(card);
    }
    const table=$("#performanceRows");table.replaceChildren();
    for(const row of data.comparison.length ? data.comparison : current.sections) {
      const tr=element("tr","");
      const change=row.p95_change_percent==null ? "—" : (row.p95_change_percent>0 ? "+" : "")+number(row.p95_change_percent)+"%";
      for(const value of [row.section,number(row.requests),number(row.p50_ms),number(row.p95_ms),
        number(row.requests_per_minute),number(row.errors)+"/"+number(row.incomplete),change]) tr.append(element("td","",value));
      table.append(tr);
    }
    $("#performanceEmpty").hidden=!!current.sections.length;
    $("#performanceNotice").textContent=data.notice;
    $("#performanceSample").textContent="Measured "+new Date(current.created*1000).toLocaleString()+
      " · "+number(tokens.reported_calls)+" reported model calls in 24h";
    const baseline=data.baseline_snapshot;
    $("#performanceBaselineSummary").hidden=!baseline;
    if(baseline) {
      const oldTokens=baseline.reported_tokens_24h,old=baseline.resources;
      $("#performanceBaselineSummary").textContent="Baseline · "+new Date(baseline.created*1000).toLocaleString()+
        " · "+number(oldTokens.input_tokens+oldTokens.output_tokens)+" reported tokens"+
        " · "+number(old.cpu_seconds)+" CPU seconds · "+number(old.memory_mb)+" MB ("+old.memory_kind+")";
    }
  }
  async function load() {
    $("#performanceError").textContent="";
    const chosen=$("#performanceBaseline").value;
    render(await api("/api/performance?baseline="+encodeURIComponent(chosen)),chosen);
  }
  async function attempt(action) {
    try {await action();} catch(error) {$("#performanceError").textContent=error.message;}
  }
  async function open() {
    if(!enabled() || !serverEnabled) return;
    $("#performanceDialog").showModal();await attempt(load);
  }
  function stateUpdate() {
    $("#openPerformance").hidden=!enabled() || !serverEnabled || !["admin","developer"].includes(access.role);
    if($("#openPerformance").hidden && $("#performanceDialog").open) $("#performanceDialog").close();
  }
  document.addEventListener("DOMContentLoaded",()=>{
    $("#openPerformance").onclick=open;
    $("#refreshPerformance").onclick=()=>attempt(load);
    $("#performanceBaseline").onchange=()=>attempt(load);
    $("#performanceBaselineForm").onsubmit=event=>{
      event.preventDefault();
      attempt(async()=>{
        const label=$("#performanceBaselineLabel").value.trim();
        const saved=await api("/api/performance/baselines",{method:"POST",body:JSON.stringify({label})});
        $("#performanceBaselineLabel").value="";
        render(await api("/api/performance?baseline="+encodeURIComponent(saved.id)),saved.id);
      });
    };
    $("#removePerformanceBaseline").onclick=()=>attempt(async()=>{
      if(!report || !$("#performanceBaseline").value) return;
      if(!confirm("Remove this measured baseline? Saved chats and records are unaffected.")) return;
      await api("/api/performance/baselines/"+encodeURIComponent($("#performanceBaseline").value),{method:"DELETE"});
      $("#performanceBaseline").value="";await load();
    });
    stateUpdate();
  });
  document.addEventListener("aimate:state",stateUpdate);
  return Object.freeze({open,enabled,setEnabled(value){serverEnabled=value!==false;}});
})();
