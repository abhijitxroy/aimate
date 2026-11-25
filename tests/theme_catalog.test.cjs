const {test}=require("node:test"),assert=require("node:assert/strict");
const themes=require("../app/static/theme_catalog.js");
test("built-in extra palettes have readable text and status colours",()=>{
  for(const [name,colors] of Object.entries(themes.palettes))
    assert.equal(themes.validate({version:1,name,colors}).name,name);
});
test("theme import rejects code, extra tokens, malformed schema and poor contrast",()=>{
  const value={version:1,name:"Mine",colors:themes.palettes.life};
  assert.throws(()=>themes.validate({...value,css:"body{}"}));
  assert.throws(()=>themes.validate({...value,colors:{...value.colors,bg:"url(https://outside)"}}));
  assert.throws(()=>themes.validate({...value,colors:{...value.colors,text:value.colors.bg}}));
  assert.throws(()=>themes.validate({...value,version:2}));
  assert.equal(themes.validate(value).name,"Mine");
});
