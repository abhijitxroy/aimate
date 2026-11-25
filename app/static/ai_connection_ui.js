/* Optional presentation only. Authentication, secrets and checks stay in core. */
(() => {
  "use strict";
  if(window.AiMateFeatures?.aiConnectionLayout===false) return;
  const panel=document.querySelector("#settings-ai");
  const provider=document.querySelector('[name="ai.provider"]');
  const account=document.querySelector("#chatgptConnection");
  if(!panel || !provider || !account) return;
  panel.classList.add("ai-connection-layout");
  const selected=provider.value;
  const groups=[
    ["Personal",["chatgpt","anthropic"]],
    ["Intel / Bedrock",["bedrock","bedrock-openai","opencode"]]
  ];
  const names={
    chatgpt:"Personal ChatGPT",anthropic:"Claude · API key",
    bedrock:"Claude · Bedrock", "bedrock-openai":"ChatGPT / Codex · Bedrock",
    opencode:"OpenCode · Bedrock"
  };
  for(const [label,values] of groups) {
    const group=document.createElement("optgroup");group.label=label;
    for(const value of values) {
      const option=[...provider.options].find(item=>item.value===value);
      if(option) {option.textContent=names[value];group.append(option);}
    }
    provider.append(group);
  }
  provider.value=selected;
  const identity=document.createElement("p");identity.className="ai-connection-context hint";
  provider.closest(".fields").after(identity);
  const explain=()=>{
    identity.textContent=provider.value==="chatgpt" ? "Personal · your ChatGPT account and plan." :
      provider.value==="anthropic" ? "Personal · your Anthropic API key." :
      "Intel / Bedrock · your organization’s key and model access.";
  };
  provider.addEventListener("change",explain);explain();
  window.AiMateConnectionLayout=Object.freeze({refresh:explain});
  const row=account.querySelector(".test-row");
  if(row) row.classList.add("ai-account-row");
  const billing=account.querySelector('a[href="https://chatgpt.com/settings/usage"]');
  if(billing) {
    const detail=document.createElement("details"),summary=document.createElement("summary");
    detail.className="ai-plan-details";summary.textContent="Plan & usage";
    billing.closest("p").before(detail);detail.append(summary,billing.closest("p"));
  }
  const status=account.querySelector("#chatgptStatus");
  const update=()=>{
    const text=status?.textContent || "";
    if(status) status.classList.toggle("success",/verified/i.test(text) && !/not verified/i.test(text));
  };
  if(status) new MutationObserver(update).observe(status,{childList:true,characterData:true,subtree:true});
  update();
})();
