const {test}=require("node:test");
const assert=require("node:assert/strict");
const recent=require("../app/static/recent_chats.js");
const chats=Array.from({length:9},(_,i)=>({id:String(i),created:i}));
test("recent chat limits preserve pins/current chat and do not mutate source",()=>{
  const source=chats.map(chat=>({...chat}));
  source[0].pinned=true;
  source[1].last_activity=100;
  const before=JSON.stringify(source),view=recent.view(source,"root","2");
  assert.deepEqual(view.items.map(chat=>chat.id),["0","1","8","7","6","2"]);
  assert.equal(view.more,true);
  assert.equal(JSON.stringify(source),before);
  recent.toggle("root");
  assert.equal(recent.view(source,"root","2").items.length,9);
  recent.toggle("root");
  assert.equal(recent.view(source,"root","2").expanded,false);
});
test("folder/archive expansion is independent and disabling restores all chats",()=>{
  recent.toggle("folder-a");
  assert.equal(recent.view(chats,"folder-a",null).items.length,9);
  assert.equal(recent.view(chats,"folder-b",null).items.length,5);
  assert.equal(recent.view(chats,"archive-a",null).items.length,5);
  globalThis.AiMateFeatures={recentChats:false};
  try {
    assert.equal(recent.view(chats,"folder-b",null).items.length,9);
    assert.equal(recent.view(chats,"folder-b",null).more,false);
  } finally { delete globalThis.AiMateFeatures; }
});
