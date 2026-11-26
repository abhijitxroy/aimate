const {test}=require("node:test");
const assert=require("node:assert/strict");
const fs=require("node:fs");
const vm=require("node:vm");
const path=require("node:path");
const context=vm.createContext({window:{}});
vm.runInContext(fs.readFileSync(path.join(__dirname,"../app/static/composer_formats.js"),"utf8"),context);
const inspect=context.window.AiMateComposerFormats.inspect;
const {change:foreground}=require("../app/static/foreground_format.js");

function applyForeground(source,word,colour) {
  const start=source.indexOf(word),edit=foreground(source,start,start+word.length,colour);
  return source.slice(0,edit.from)+edit.value+source.slice(edit.to);
}
test("foreground replaces or resets nested colours without multiplying tags",()=>{
  const source="[colour:#79baff][colour:#eb0f46][colour:#eb0f46][colour:#eb0f46]text[/colour][/colour][/colour][/colour]";
  assert.equal(applyForeground(source,"text","#eb0f46"),"text");
  assert.equal(applyForeground(source,"text","#123456"),"[colour:#123456]text[/colour]");
  let value="text";
  for(let i=0;i<8;i++) {
    value=applyForeground(value,"text","#eb0f46");
    assert.equal(value,i%2===0 ? "[colour:#eb0f46]text[/colour]" : "text");
  }
});
test("foreground preserves unselected colour and other Markdown formats",()=>{
  assert.equal(applyForeground("[colour:#79baff]Hello world[/colour]","world","#eb0f46"),
    "[colour:#79baff]Hello [/colour][colour:#eb0f46]world[/colour]");
  assert.equal(applyForeground("[colour:#79baff]**Hello**[/colour]","Hello","#eb0f46"),
    "[colour:#eb0f46]**Hello**[/colour]");
  assert.equal(applyForeground("***++[colour:#79baff]Hello[/colour]++***","Hello","#eb0f46"),
    "***++[colour:#eb0f46]Hello[/colour]++***");
});
test("foreground across adjacent coloured runs uses one wrapper and validates CSS",()=>{
  const source="[colour:#79baff]One[/colour] [colour:#eb0f46]Two[/colour]";
  assert.equal(foreground(source,0,source.length,"#123456").value,"[colour:#123456]One Two[/colour]");
  assert.throws(()=>foreground("Hello",0,5,"red"),/six-digit/);
});

test("combined formats follow the selected text and clear outside it",()=>{
  const source="***++[colour:#ff7aaf]Hello[/colour]++*** plain";
  const start=source.indexOf("Hello"), end=start+5;
  const result=inspect(source,start,end);
  for(const key of ["bold","italic","underline","colour"]) assert.equal(result.states[key],true,key);
  assert.equal(result.ranges.colour.colour,"#ff7aaf");
  const plain=inspect(source,source.length);
  for(const key of ["bold","italic","underline","colour"]) assert.ok(!plain.states[key],key);
});

test("mixed selections do not claim a format applies to all text",()=>{
  const result=inspect("**First** plain",2,14);
  assert.ok(!result.states.bold);
  assert.ok(!inspect("- Item\nPlain",0,12).states.bullet);
  assert.equal(inspect("- First\n- Second\nPlain",0,17).states.bullet,true);
});

test("literal code suppresses misleading inline format indicators",()=>{
  for(const source of ["```text\n++[colour:#79baff]Literal[/colour]++\n```","`**Literal**`"]) {
    const start=source.indexOf("Literal"), result=inspect(source,start,start+7);
    assert.equal(result.states.code,true);
    for(const key of ["bold","underline","colour"]) assert.ok(!result.states[key]);
  }
  assert.ok(!inspect("\\**Literal**",4).states.bold);
  assert.ok(!inspect("\\++Literal++",4).states.underline);
});

test("block formats and callouts are indicated on their content line",()=>{
  for(const [source,key] of [["## Heading","heading"],["- Item","bullet"],["1. Item","numbered"],
    ["    Item","indent"],["> Quote","quote"],["| Item | Value |","table"],["---","rule"],
    ["> [!NOTE]\n> Item","note"],["> [!WARNING]\n> Item","warning"]]) {
    assert.equal(inspect(source,source.length).states[key],true,key);
  }
});

test("nested colours choose the closest scope and invalid CSS is not active",()=>{
  const source="[colour:#79baff][colour:#ff7aaf]Hello[/colour][/colour]";
  assert.equal(inspect(source,source.indexOf("Hello")).ranges.colour.colour,"#ff7aaf");
  assert.ok(!inspect("[colour:red]Hello[/colour]",15).states.colour);
});
