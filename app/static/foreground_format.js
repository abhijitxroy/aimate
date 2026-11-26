/* Replace/toggle foreground colour without nesting portable colour tags. */
(function(root) {
  "use strict";
  function change(text,start,end,colour) {
    if(!/^#[0-9a-f]{6}$/i.test(colour)) throw new Error("Choose a six-digit foreground colour.");
    colour=colour.toLowerCase();
    const code=[];
    for(const match of text.matchAll(/(```[^\n]*\n)[\s\S]*?(?:\n```[ \t]*(?=\n|$)|$)|(`+)[^\n]*?\2/g))
      code.push([match.index,match.index+match[0].length]);
    const literal=position=>code.some(([from,to])=>position>=from && position<to);
    const scopes=[],stack=[];
    for(const match of text.matchAll(/\[colour:(#[0-9a-f]{6})\]|\[\/colour\]/gi)) {
      let escapes=0;for(let i=match.index-1;i>=0 && text[i]==="\\";i--) escapes++;
      if(literal(match.index) || escapes%2) continue;
      if(match[1]) stack.push({from:match.index,openEnd:match.index+match[0].length,colour:match[1].toLowerCase()});
      else if(stack.length) scopes.push({...stack.pop(),closeStart:match.index,to:match.index+match[0].length});
    }
    const containing=scopes.filter(s=>(start>=s.openEnd && end<=s.closeStart) || (start===s.from && end===s.to));
    const outer=containing.sort((a,b)=>(b.to-b.from)-(a.to-a.from))[0];
    if(!outer) {
      let chosen=text.slice(start,end) || "text";
      const marks=scopes.filter(s=>s.from>=start && s.to<=end).flatMap(s=>[
        [s.from-start,s.openEnd-start],[s.closeStart-start,s.to-start]]);
      for(const [from,to] of marks.sort((a,b)=>b[0]-a[0])) chosen=chosen.slice(0,from)+chosen.slice(to);
      const prefix="[colour:"+colour+"]";
      return {from:start,to:end,value:prefix+chosen+"[/colour]",start:start+prefix.length,end:start+prefix.length+chosen.length};
    }
    if(start===end || (start===outer.from && end===outer.to)) {start=outer.openEnd;end=outer.closeStart;}
    const before=text.slice(outer.openEnd,start),after=text.slice(end,outer.closeStart);
    if(before===after && /^[*_+]+$/.test(before)) {start=outer.openEnd;end=outer.closeStart;}
    const marks=[];
    for(const scope of scopes.filter(s=>s.from>=outer.from && s.to<=outer.to))
      marks.push({from:scope.from,to:scope.openEnd,colour:scope.colour},{from:scope.closeStart,to:scope.to,close:true});
    marks.sort((a,b)=>a.from-b.from);
    const active=[],pieces=[];let position=outer.from;
    function add(from,to) {
      for(const [a,b] of [[from,Math.min(to,start)],[Math.max(from,start),Math.min(to,end)],[Math.max(from,end),to]])
        if(b>a) pieces.push({text:text.slice(a,b),colour:active.at(-1) || null,selected:a>=start && b<=end});
    }
    for(const mark of marks) {
      add(position,mark.from);
      if(mark.close) active.pop();else active.push(mark.colour);
      position=mark.to;
    }
    add(position,outer.to);
    const selected=pieces.filter(p=>p.selected),reset=selected.length && selected.every(p=>p.colour===colour);
    for(const piece of selected) piece.colour=reset ? null : colour;
    const runs=[];
    for(const piece of pieces) {
      const previous=runs.at(-1);
      if(previous && previous.colour===piece.colour) previous.pieces.push(piece);
      else runs.push({colour:piece.colour,pieces:[piece]});
    }
    let value="",selectedStart=null,selectedEnd=null;
    for(const run of runs) {
      if(run.colour) value+="[colour:"+run.colour+"]";
      for(const piece of run.pieces) {
        if(piece.selected && selectedStart===null) selectedStart=value.length;
        value+=piece.text;if(piece.selected) selectedEnd=value.length;
      }
      if(run.colour) value+="[/colour]";
    }
    return {from:outer.from,to:outer.to,value,start:outer.from+(selectedStart ?? 0),end:outer.from+(selectedEnd ?? value.length)};
  }
  if(typeof module==="object" && module.exports) module.exports={change};
  root.AiMateForeground=Object.freeze({change});
})(globalThis);
