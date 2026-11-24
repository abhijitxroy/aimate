/* Usage controls kept separate from conversation streaming. */
let usageReport = null;
const tokenTotal = row => row.input_tokens + row.output_tokens + row.cache_read_input_tokens + row.cache_creation_input_tokens;
const usd = value => new Intl.NumberFormat(undefined,{style:"currency",currency:"USD",maximumFractionDigits:4}).format(value);
const numberLabel = value => value.toLocaleString();
async function loadUsage() {
  try {
    $("#usageError").textContent = "";
    usageReport = await api(`/api/usage?days=${$("#usageDays").value}&offset=${-new Date().getTimezoneOffset()}`);
    const totals = usageReport.totals, summary = $("#usageSummary"); summary.replaceChildren();
    const cards = [["Reported tokens",numberLabel(tokenTotal(totals))],["Usage entries",numberLabel(totals.requests)],
      ["Estimated cost", totals.requests && !totals.unpriced_requests ? usd(totals.estimated_usd) : totals.requests > totals.unpriced_requests ? usd(totals.estimated_usd) + " + unpriced" : "Rates not set"]];
    for (const [label,value] of cards) {
      const card = element("div"); card.append(element("small","",label),element("strong","",value)); summary.append(card);
    }
    const table = element("table"), head = element("tr");
    for (const label of ["Model","Entries","Input","Output","Cached / written","Est. USD"]) head.append(element("th","",label));
    table.append(head);
    for (const row of usageReport.models) {
      const tr = element("tr");
      for (const value of [row.model,numberLabel(row.requests),numberLabel(row.input_tokens),numberLabel(row.output_tokens),
        numberLabel(row.cache_read_input_tokens) + " / " + numberLabel(row.cache_creation_input_tokens),
        row.unpriced_requests ? "Unpriced" + (row.requests > row.unpriced_requests ? " + " + usd(row.estimated_usd) : "") : usd(row.estimated_usd)]) tr.append(element("td","",value));
      tr.onclick = () => { $("#rateModel").value = row.model; setRateFields(); }; table.append(tr);
    }
    $("#usageModels").replaceChildren(table);
    if (!usageReport.models.length) $("#usageModels").append(element("p","hint","No reported usage in this period."));
    const options = $("#usageModelOptions"); options.replaceChildren();
    for (const model of new Set([...usageReport.models.map(r=>r.model),config.ai?.model,config.ai?.analysis_model].filter(Boolean))) {
      const option = element("option"); option.value=model; options.append(option);
    }
    $("#usageCoverage").textContent = usageReport.coverage + " Days use your device timezone.";
    const monthly = usageReport.monthly, billing = $("#usageBilling");
    billing.replaceChildren(element("h3","",`${monthly.month} · UTC`),
      element("p", monthly.exceeded ? "error" : "hint",
        `${usd(monthly.estimated_usd)} estimated${monthly.budget.monthly_usd ? " / " + usd(monthly.budget.monthly_usd) + " budget" : ""}${monthly.exceeded ? " · Budget reached" : ""}`));
    for (const row of usageReport.calls) billing.append(element("p","hint",`${row.origin} · ${row.status}: ${row.count}`));
    for (const row of usageReport.bill_comparisons) billing.append(element("p","hint",`${row.month} · ${row.model}: billed ${usd(row.amount)}, estimated ${usd(row.estimated_usd)}, difference ${usd(row.difference_usd)}`));
    $("#usageBudget").value = monthly.budget.monthly_usd;
    $("#usageBudgetMode").value = monthly.budget.mode;
    $("#invoiceMonth").value ||= monthly.month;
    renderUsageChart();
  } catch (error) { $("#usageError").textContent = error.message; }
}
function renderUsageChart() {
  if (!usageReport) return;
  const chart = $("#usageChart"); chart.replaceChildren();
  const cost = $("#usageMetric").value === "cost";
  if (cost && usageReport.totals.unpriced_requests === usageReport.totals.requests) {
    chart.append(element("p","hint","Add model rates to show cost estimates.")); return;
  }
  const rows = [];
  for (let i=usageReport.days-1;i>=0;i--) {
    const date = new Date(); date.setDate(date.getDate()-i);
    const key = `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;
    rows.push(usageReport.daily.find(r=>r.date===key) || {date:key,input_tokens:0,output_tokens:0,
      cache_read_input_tokens:0,cache_creation_input_tokens:0,estimated_usd:0,unpriced_requests:0});
  }
  const maximum = Math.max(1e-8,...rows.map(r=>cost ? r.estimated_usd : tokenTotal(r)));
  for (const row of rows) {
    const column = element("div","usage-column"), bar = element("i");
    const value = cost ? row.estimated_usd : tokenTotal(row);
    bar.style.height = Math.max(1,value/maximum*130)+"px";
    column.title = row.date + ": " + (cost ? usd(value) + (row.unpriced_requests ? " · includes unpriced requests" : "") : numberLabel(value)+" tokens");
    column.append(bar,element("small","",row.date.slice(5))); chart.append(column);
  }
  if (!rows.length) chart.append(element("p","hint","Your activity will appear here."));
}
function setRateFields() {
  const rate = usageReport?.rates.find(r=>r.model===$("#rateModel").value);
  for (const [id,key] of [["rateInput","input"],["rateOutput","output"],["rateRead","cache_read"],["rateWrite","cache_write"]]) $("#"+id).value=rate ? rate[key] : "";
}
$("#openUsage").onclick = () => { $("#usageDialog").showModal(); void loadUsage(); };
$("#usageDays").onchange = loadUsage;
$("#usageMetric").onchange = renderUsageChart;
$("#rateModel").oninput = setRateFields;
$("#usageBudgetForm").onsubmit = async event => {
  event.preventDefault();
  try { await api("/api/usage/budget",{method:"POST",body:JSON.stringify({monthly_usd:Number($("#usageBudget").value),mode:$("#usageBudgetMode").value})}); await loadUsage(); }
  catch(error) { $("#usageError").textContent=error.message; }
};
$("#usageInvoiceForm").onsubmit = async event => {
  event.preventDefault();
  try { await api("/api/usage/invoice",{method:"POST",body:JSON.stringify({month:$("#invoiceMonth").value,model:$("#invoiceModel").value,amount:Number($("#invoiceAmount").value)})}); await loadUsage(); }
  catch(error) { $("#usageError").textContent=error.message; }
};
$("#usageRateForm").onsubmit = async event => {
  event.preventDefault();
  try {
    await api("/api/usage/rates",{method:"POST",body:JSON.stringify({model:$("#rateModel").value,
      input:Number($("#rateInput").value),output:Number($("#rateOutput").value),
      cache_read:Number($("#rateRead").value),cache_write:Number($("#rateWrite").value)})});
    await loadUsage();
  } catch (error) { $("#usageError").textContent=error.message; }
};
$("#exportUsage").onclick = () => {
  if (!usageReport) return;
  const csv = [["Day","Input tokens","Output tokens","Cache read tokens","Cache write tokens","Usage entries","Estimated USD","Unpriced entries"],
    ...usageReport.daily.map(r=>[r.date,r.input_tokens,r.output_tokens,r.cache_read_input_tokens,r.cache_creation_input_tokens,r.requests,r.estimated_usd,r.unpriced_requests])];
  downloadFile(csv.map(row=>row.join(",")).join("\r\n"),"AiMate-usage.csv","text/csv;charset=utf-8");
  const modelCsv = [["Model","Input tokens","Output tokens","Cache read tokens","Cache write tokens","Usage entries","Estimated USD","Unpriced entries"],
    ...usageReport.models.map(r=>[r.model,r.input_tokens,r.output_tokens,r.cache_read_input_tokens,r.cache_creation_input_tokens,r.requests,r.estimated_usd,r.unpriced_requests])];
  const cell = value => '"' + String(value).replace(/^[=+@-]/,"'$&").replaceAll('"','""') + '"';
  downloadFile(modelCsv.map(row=>row.map(cell).join(",")).join("\r\n"),"AiMate-usage-models.csv","text/csv;charset=utf-8");
};
