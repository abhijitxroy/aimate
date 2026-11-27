const {test}=require("node:test");
const assert=require("node:assert/strict");
const {choose,describe}=require("../app/static/latest_model_choices.js");
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
