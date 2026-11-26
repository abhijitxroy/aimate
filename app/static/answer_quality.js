/* Optional compact assessments. DOM text only; never render assessment HTML. */
(() => {
  "use strict";
  const enabled=()=>window.AiMateFeatures?.answerQuality !== false;
  const words={high:"High",medium:"Medium",low:"Low",complete:"Complete",partial:"Partial",
    limited:"Limited",not_applicable:"Not applicable"};
  function update(message,quality) {
    if(message.qualityInfo) {message.qualityInfo.remove();message.qualityInfo=null;}
    if(!enabled() || !quality || quality.version!==1 ||
      !["analysis","review","design","note","search"].includes(quality.kind)) return;
    const node=document.createElement("details");node.className="quality-info model-info";
    const summary=document.createElement("summary");
    const assessed=quality.assessed===true && ["high","medium","low"].includes(quality.confidence);
    const label=!assessed ? "Not assessed" : quality.kind==="search" ? "Source confidence · "+words[quality.confidence]
      : "Confidence · "+words[quality.confidence];
    summary.textContent=label;
    summary.setAttribute("aria-label",label+". Show answer quality details");
    const rows=[];
    if(assessed) {
      rows.push(["Confidence",words[quality.confidence]+" · AI assessment"],["Basis",quality.basis]);
      if(quality.kind!=="search") {
        rows.push(["Coverage",words[quality.coverage] || "Not assessed"],
          ["Further investigation",quality.further_investigation ? "Needed" : "Not indicated by this assessment"],
          ["Missing",(quality.gaps || []).join("; ") || "None reported"]);
        if(quality.next_step) rows.push(["Next step",quality.next_step]);
      }
    } else rows.push(["Assessment","The model did not assess this answer."]);
    rows.push(["Accuracy","Not independently measured"]);
    if(Number.isInteger(quality.source_count)) rows.push(["Sources read",String(quality.source_count)]);
    if(quality.failed_reads>0) rows.push(["Failed reads",String(quality.failed_reads)+" · see activity for details"]);
    summary.title=rows.map(([key,value])=>key+": "+value).join("\n");
    const panel=document.createElement("div");panel.className="model-details quality-details";
    const list=document.createElement("dl");
    for(const [key,value] of rows) {
      const dt=document.createElement("dt"),dd=document.createElement("dd");
      dt.textContent=key;dd.textContent=String(value || "Not reported");list.append(dt,dd);
    }
    panel.append(list);node.append(summary,panel);
    node.dataset.confidence=assessed ? quality.confidence : "unknown";
    message.qualityInfo=node;
    if(message.meta) message.meta.insertBefore(node,message.clock || null);
    else message.root.append(node);
  }
  window.AiMateAnswerQuality=Object.freeze({update});
})();
