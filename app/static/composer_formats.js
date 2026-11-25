/* Selection-aware format indicators; pure source inspection, no HTML rendering. */
(() => {
  "use strict";
  function inspect(text, start, end = start) {
    start=Math.max(0, Math.min(start, text.length));
    end=Math.max(start, Math.min(end, text.length));
    const states={}, ranges={};
    function add(kind, from, to, prefix, suffix, extra={}) {
      let escapes=0;
      for (let i=from-1;i >= 0 && text[i] === "\\";i--) escapes++;
      if (escapes % 2) return;
      const inside=start >= from+prefix && end <= to-suffix;
      const whole=end > start && start === from && end === to;
      if (!(inside || whole)) return;
      const previous=ranges[kind];
      if (!previous || to-from < previous.to-previous.from) {
        ranges[kind]={from,to,prefix,suffix,...extra};states[kind]=true;
      }
    }
    for (const match of text.matchAll(/^(```[^\n]*\n)([\s\S]*?)(\n```[ \t]*(?=\n|$)|$)/gm)) {
      add("code",match.index,match.index+match[0].length,match[1].length,match[3].length);
    }
    // Inside code, markup is literal rather than an enabled text format.
    if (states.code) return {states,ranges};
    for (const match of text.matchAll(/(`+)([^\n]*?)\1/g)) {
      add("code",match.index,match.index+match[0].length,match[1].length,match[1].length);
    }
    if (states.code) return {states,ranges};
    for (const [pattern, kind, prefix] of [
      [/\*\*\*[^*\n]+\*\*\*/g,"bold",2],
      [/\*\*\*[^*\n]+\*\*\*/g,"italic",1],
      [/\*\*[\s\S]+?\*\*/g,"bold",2],
      [/__[\s\S]+?__/g,"bold",2],
      [/(?<!\*)\*(?!\*)([^*\n]+)\*(?!\*)/g,"italic",1],
      [/(?<![\w_])_([^_\n]+)_(?![\w_])/g,"italic",1],
      [/\+\+([^\n]+?)\+\+/g,"underline",2],
    ]) {
      for (const match of text.matchAll(pattern)) {
        add(kind,match.index,match.index+match[0].length,prefix,prefix);
      }
    }
    const colours=[];
    for (const match of text.matchAll(/\[colour:(#[0-9a-fA-F]{6})\]|\[\/colour\]/g)) {
      if (match[1]) colours.push({from:match.index,prefix:match[0].length,colour:match[1].toLowerCase()});
      else if (colours.length) {
        const open=colours.pop(), to=match.index+match[0].length;
        if (to-open.from <= 4000) add("colour",open.from,to,open.prefix,match[0].length,{colour:open.colour});
      }
    }
    const rows=text.split("\n"), rowIndex=text.slice(0,start).split("\n").length-1;
    const boundary=end > start && text[end-1] === "\n" ? end-1 : end;
    const lastRow=text.slice(0,boundary).split("\n").length-1;
    const selectedRows=rows.slice(rowIndex,lastRow+1);
    const all=pattern => selectedRows.every(row => pattern.test(row));
    states.heading=all(/^#{1,6}\s/);
    states.bullet=all(/^\s*[-+*]\s/);
    states.numbered=all(/^\s*\d+[.)]\s/);
    states.indent=all(/^(?: {4}|\t)/);
    states.rule=all(/^\s*(?:---|\*\*\*|___)\s*$/);
    states.table=all(/^\s*\|.*\|\s*$/);
    if (all(/^\s*>/)) {
      let first=rowIndex;
      while (first > 0 && /^\s*>/.test(rows[first-1])) first--;
      const block=rows.slice(first,rowIndex+1).join("\n");
      states.note=/^>\s*\[!NOTE\]/.test(block);
      states.warning=/^>\s*\[!WARNING\]/.test(block);
      states.quote=!states.note && !states.warning;
    }
    return {states,ranges};
  }
  window.AiMateComposerFormats=Object.freeze({inspect});
})();
