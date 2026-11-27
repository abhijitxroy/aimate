import {syntaxTree} from "@codemirror/language";
import {EditorSelection,Transaction} from "@codemirror/state";
import {isolateHistory} from "@codemirror/commands";

// A trailing space inside **word** would invalidate Markdown's closing marker.
// At the content boundary, place it after all closing wrappers instead.
export function exitInlineFormatOnSpace(view,from,to,text) {
  if(globalThis.AiMateFeatures?.inlineFormatBoundary===false || text!==" " ||
     from!==to || view.state.selection.ranges.length!==1 ||
     !view.state.selection.main.empty) return false;
  const source=view.state.doc.toString(),scopes=[],literal=[];
  syntaxTree(view.state).iterate({enter(node) {
    if(["InlineCode","FencedCode","CodeBlock"].includes(node.name))
      literal.push([node.from,node.to]);
    const length=node.name==="StrongEmphasis" ? 2 : node.name==="Emphasis" ? 1 : 0;
    if(length) scopes.push({contentEnd:node.to-length,end:node.to});
  }});
  const isLiteral=position=>literal.some(([start,end])=>position>=start && position<end);
  if(isLiteral(from)) return false;
  for(const match of source.matchAll(/\+\+([^\n]+?)\+\+/g))
    if(!isLiteral(match.index)) scopes.push({contentEnd:match.index+match[0].length-2,end:match.index+match[0].length});
  for(const match of source.matchAll(/\[colour:#[0-9a-fA-F]{6}\]([^\n]*?)\[\/colour\]/g))
    if(!isLiteral(match.index)) scopes.push({contentEnd:match.index+match[0].length-9,end:match.index+match[0].length});
  let end=from;
  // Consume inner-to-outer closings for combinations such as ***word***.
  for(let count=0;count<scopes.length;count++) {
    const next=scopes.find(scope=>scope.contentEnd===end && scope.end>end);
    if(!next) break;
    end=next.end;
  }
  if(end===from) return false;
  view.dispatch({changes:{from:end,to:end,insert:text},
    selection:EditorSelection.cursor(end+1),scrollIntoView:true,
    annotations:[Transaction.userEvent.of("input.type"),isolateHistory.of("full")]});
  return true;
}
