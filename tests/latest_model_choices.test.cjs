const {test}=require("node:test");
const assert=require("node:assert/strict");
const {choose,describe,guidance,compactPicker}=require("../app/static/latest_model_choices.js");
const row=id=>({id,label:id,source:"AWS catalog"});
test("latest family choices remove legacy versions and route duplicates",()=>{
  const rows=[
    row("us.anthropic.claude-haiku-4-5"),row("us.anthropic.claude-haiku-5-5"),
    row("us.anthropic.claude-sonnet-5-5"),row("global.anthropic.claude-sonnet-5-5"),
    row("anthropic.claude-sonnet-5-5-v1:0"),row("us.anthropic.claude-opus-5"),
    row("global.anthropic.claude-opus-5-5"),row("us.anthropic.claude-opus-5-5"),
    row("us.anthropic.claude-fable-5-2"),row("other.vendor-model")];
  const before=JSON.stringify(rows),result=choose(rows);
  assert.deepEqual(result.map(m=>m.label),["Haiku 5.5","Sonnet 5.5","Opus 5.5","Fable 5.2"]);
  assert.equal(result[2].id,"us.anthropic.claude-opus-5-5");
  assert.equal(JSON.stringify(rows),before);
});
test("version comparison is numeric and date suffixes are not minor versions",()=>{
  assert.equal(describe("anthropic.claude-sonnet-4-20250514-v1:0").label,"Sonnet 4");
  assert.equal(describe("us.anthropic.claude-3-7-sonnet-20250219-v1:0").label,"Sonnet 3.7");
  const rows=["us.anthropic.claude-sonnet-5-9","us.anthropic.claude-sonnet-5-10"].map(row);
  assert.equal(choose(rows)[0].label,"Sonnet 5.10");
});
test("exact configured route is preserved at the latest version, never at an older version",()=>{
  const rows=["us.anthropic.claude-opus-5-5","global.anthropic.claude-opus-5-5",
    "us.anthropic.claude-opus-5"].map(row);
  assert.equal(choose(rows,{preferred:[rows[1].id]})[0].id,rows[1].id);
  assert.equal(choose(rows,{preferred:[rows[2].id]})[0].id,rows[0].id);
});
test("existing region/endpoint routes stay internal and only catalog IDs are returned",()=>{
  const rows=["anthropic.claude-opus-5-5","global.anthropic.claude-opus-5-5",
    "eu.anthropic.claude-opus-5-5"].map(row);
  assert.equal(choose(rows,{region:"eu-west-1"})[0].id,rows[2].id);
  assert.equal(choose(rows,{endpoint:"mantle"})[0].id,rows[0].id);
});
test("new named Claude families remain visible and disabled mode retains full source rows",()=>{
  const rows=["us.anthropic.claude-newfamily-6-1","us.anthropic.claude-newfamily-6-2"].map(row);
  assert.deepEqual(choose(rows).map(m=>m.label),["Newfamily 6.2"]);
  global.AiMateFeatures={latestModelChoices:false};
  try {assert.equal(choose(rows),rows);} finally {delete global.AiMateFeatures;}
});
function pickerFixture(value="auto") {
  const model="us.anthropic.claude-haiku-5-5",analysis_model="us.anthropic.claude-sonnet-5-5";
  const options=["auto","auto-quality","auto-economy","standard","analysis"].map(value=>({
    value,dataset:{},parentElement:{disabled:false},title:"Routing",textContent:value
  }));
  for(const family of ["haiku-5-5","sonnet-5-5","opus-5-5","fable-5-2"]) {
    const id="us.anthropic.claude-"+family;
    options.push({value:"manual:"+id,dataset:{manualModel:id},parentElement:{disabled:false},title:"Access checked when used."});
  }
  return {model,analysis_model,value,options,selectedOptions:[options.find(row=>row.value===value)],setAttribute(){}};
}
test("clean picker keeps Auto routing internally with one visible entry per model",()=>{
  const picker=pickerFixture();
  compactPicker(picker,picker,id=>describe(id).label);
  const visible=picker.options.filter(row=>!row.hidden);
  assert.deepEqual(visible.map(row=>row.textContent),["Haiku 5.5 · Fastest","Sonnet 5.5 · Balanced",
    "Opus 5.5 · High capability","Fable 5.2 · Premium"]);
  assert.equal(picker.value,"auto");
  assert.equal(visible[0].value,"auto");
  assert.equal(guidance("us.anthropic.claude-fable-5-2")[0],"Premium");
});
test("fixed Fable selection and saved Quality policy are preserved",()=>{
  for(const value of ["manual:us.anthropic.claude-fable-5-2","auto-quality"]) {
    const picker=pickerFixture(value);
    compactPicker(picker,picker,id=>describe(id).label);
    assert.equal(picker.value,value);
    assert.equal(picker.options.filter(row=>!row.hidden).length,4);
    assert.equal(picker.selectedOptions[0].hidden,false);
  }
});
test("clean picker degrades to configured models and can be disabled",()=>{
  const picker=pickerFixture();
  picker.options=picker.options.slice(0,5);
  compactPicker(picker,picker,id=>describe(id).label);
  assert.deepEqual(picker.options.filter(row=>!row.hidden).map(row=>row.value),["auto","analysis"]);
  global.AiMateFeatures={cleanModelPicker:false};
  try {
    compactPicker(picker,picker,id=>describe(id).label);
    assert.ok(picker.options.every(row=>row.hidden===false));
  } finally {delete global.AiMateFeatures;}
});
