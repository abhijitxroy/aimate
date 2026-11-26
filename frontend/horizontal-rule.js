import {EditorSelection,Transaction} from "@codemirror/state";
import {Decoration} from "@codemirror/view";
import {syntaxTree} from "@codemirror/language";
import {isolateHistory} from "@codemirror/commands";

const enabled=()=>globalThis.AiMateFeatures?.horizontalRule!==false;

export function insertHorizontalRule(view) {
  if(!enabled()) return false;
  const {doc,selection}=view.state, range=selection.main;
  if(!range.empty || selection.ranges.length!==1) return false;
  const line=doc.lineAt(range.head);
  if(range.head!==line.to || !/^\s{0,3}---\s*$/.test(line.text)) return false;
  let literal=false;
  syntaxTree(view.state).iterate({enter(node) {
    if(["FencedCode","CodeBlock"].includes(node.name) && node.from<=line.from && node.to>=line.to) literal=true;
  }});
  if(literal) return false;
  // A blank line before the rule prevents Markdown's Setext-heading ambiguity.
  const prefix=line.number>1 && doc.line(line.number-1).text.trim() ? "\n" : "";
  const insert=prefix+"---"+(line.to===doc.length ? "\n\n" : "\n");
  view.dispatch({changes:{from:line.from,to:line.to,insert},
    selection:EditorSelection.cursor(line.from+insert.length),scrollIntoView:true,
    annotations:[Transaction.userEvent.of("input.horizontal-rule"),isolateHistory.of("full")]});
  return true;
}

export function decorateHorizontalRule(view,node,ranges) {
  if(!enabled() || node.name!=="HorizontalRule") return;
  const line=view.state.doc.lineAt(node.from);
  // Show typed dashes until Shift+Enter terminates the line.
  if(line.to===view.state.doc.length || !/^\s{0,3}---\s*$/.test(line.text)) return;
  ranges.push(Decoration.line({attributes:{class:"cm-horizontal-rule",role:"separator",
    "aria-label":"Horizontal rule"}}).range(line.from));
  ranges.push(Decoration.replace({}).range(node.from,node.to));
}
