import {EditorState,EditorSelection,Compartment,Transaction} from "@codemirror/state";
import {EditorView,Decoration,ViewPlugin,keymap,placeholder} from "@codemirror/view";
import {markdown} from "@codemirror/lang-markdown";
import {syntaxTree} from "@codemirror/language";
import {defaultKeymap,history,historyKeymap,insertNewlineAndIndent,isolateHistory} from "@codemirror/commands";
import {StyleModule} from "style-mod";

// Preserve style-src 'self': trusted editor styles use CSSOM, not inline <style>.
const originalMount=StyleModule.mount, styleRoots=new WeakMap();
StyleModule.mount=(root,modules,nonce)=>{
  if(root.nodeType===9 && root.adoptedStyleSheets && root.defaultView?.CSSStyleSheet) {
    let proxy=styleRoots.get(root);
    if(!proxy) {
      proxy={ownerDocument:root,get adoptedStyleSheets(){return root.adoptedStyleSheets;},
        set adoptedStyleSheets(value){root.adoptedStyleSheets=value;}};
      styleRoots.set(root,proxy);
    }
    return originalMount(proxy,modules,nonce);
  }
  return originalMount(root,modules,nonce);
};

function decorations(view) {
  const doc=view.state.doc, ranges=[], code=[];
  function inline(from,to,prefix,suffix,attributes,tagName="span") {
    if(to-from<=prefix+suffix) return;
    ranges.push(Decoration.mark({tagName,attributes}).range(from+prefix,to-suffix));
    if(prefix) ranges.push(Decoration.replace({}).range(from,from+prefix));
    if(suffix) ranges.push(Decoration.replace({}).range(to-suffix,to));
  }
  syntaxTree(view.state).iterate({enter(node) {
    if(["InlineCode","FencedCode","CodeBlock"].includes(node.name)) code.push([node.from,node.to]);
    if(node.name==="StrongEmphasis") inline(node.from,node.to,2,2,{class:"cm-inline-bold"},"strong");
    else if(node.name==="Emphasis") inline(node.from,node.to,1,1,{class:"cm-inline-italic"},"em");
    else if(node.name==="InlineCode") ranges.push(Decoration.mark({class:"cm-inline-code"}).range(node.from,node.to));
  }});
  const text=doc.toString();
  const literal=position=>code.some(([start,end])=>position>=start && position<end);
  for(const match of text.matchAll(/\+\+([^\n]+?)\+\+/g))
    if(!literal(match.index)) inline(match.index,match.index+match[0].length,2,2,{class:"cm-inline-underline"},"u");
  for(const match of text.matchAll(/\[colour:(#[0-9a-fA-F]{6})\]([^\n]*?)\[\/colour\]/g)) {
    if(literal(match.index)) continue;
    const prefix=match[0].indexOf("]")+1;
    inline(match.index,match.index+match[0].length,prefix,9,
      {class:"cm-inline-colour","data-rich-colour":match[1]});
  }
  return Decoration.set(ranges,true);
}
const appearance=ViewPlugin.fromClass(class {
  constructor(view) {this.decorations=decorations(view);}
  update(update) {
    if(update.docChanged || update.viewportChanged || syntaxTree(update.startState)!==syntaxTree(update.state))
      this.decorations=decorations(update.view);
  }
},{decorations:value=>value.decorations});

export function attach(source) {
  const host=document.createElement("div");host.className="rich-composer";
  source.id="questionSource";source.hidden=true;source.required=false;source.after(host);
  const wrapping=new Compartment(), limit=source.maxLength || 30000;
  let field, view, wrap="soft", required=true;
  const paint=()=>host.querySelectorAll("[data-rich-colour]").forEach(node=>{
    if(/^#[0-9a-fA-F]{6}$/.test(node.dataset.richColour)) node.style.color=node.dataset.richColour;
  });
  const extensions=[
    markdown({addKeymap:false}),history(),
    keymap.of([{key:"Shift-Enter",run:insertNewlineAndIndent},
      ...defaultKeymap.filter(binding=>!["Enter","Mod-Enter","Mod-b","Mod-i","Mod-u"].includes(binding.key)),
      ...historyKeymap.filter(binding=>binding.key!=="Mod-u")]),
    wrapping.of(EditorView.lineWrapping),appearance,placeholder(source.placeholder),
    EditorView.domEventHandlers({
      paste:event=>{
        event.preventDefault();
        const files=[...(event.clipboardData?.files || [])];
        const text=event.clipboardData?.getData("text/plain") || "";
        // Main app handles files and large-paste attachment conversion on bubbling.
        if(!files.length && text.length<=4000 && text) field.setRangeText(text,field.selectionStart,field.selectionEnd,"end");
        return true;
      },
      drop:event=>{
        const files=[...(event.dataTransfer?.files || [])];
        if(!files.length) return false;
        event.preventDefault();return true;
      }
    }),
    EditorView.contentAttributes.of({id:"question","aria-label":source.getAttribute("aria-label") || "Your question",
      "aria-multiline":"true","spellcheck":"true"}),
    EditorState.transactionFilter.of(transaction=>{
      if(transaction.newDoc.length<=limit) return transaction;
      const activity=document.querySelector("#activity");
      if(activity) activity.textContent="Message is too long. Attach the text as a file.";
      return [];
    }),
    EditorView.updateListener.of(update=>{
      if(!field) return;
      paint();
      if(update.docChanged) {
        source.value=update.state.doc.toString();
        field.dispatchEvent(new Event("input",{bubbles:true}));
      }
      if(update.selectionSet) field.dispatchEvent(new Event("select",{bubbles:true}));
    }),
    EditorView.theme({
      "&":{fontFamily:"inherit",fontSize:"14px",color:"var(--text)",backgroundColor:"transparent"},
      "&.cm-focused":{outline:"none"},
      ".cm-content":{fontFamily:"inherit",minHeight:"48px",padding:"8px 0"},
      ".cm-line":{padding:"0"},
      ".cm-scroller":{fontFamily:"inherit",lineHeight:"1.6",minHeight:"48px",maxHeight:"min(240px,24vh)",overflow:"auto"},
      ".cm-placeholder":{color:"var(--muted)",opacity:".7"},
      ".cm-cursor":{borderLeftColor:"var(--text)"},
      ".cm-inline-bold":{fontWeight:"700"},
      ".cm-inline-italic":{fontStyle:"italic"},
      ".cm-inline-underline":{textDecoration:"underline"},
      ".cm-inline-code":{fontFamily:"Consolas,monospace",color:"var(--accent)"},
      ".cm-selectionBackground":{backgroundColor:"#79baff40 !important"}
    })
  ];
  view=new EditorView({state:EditorState.create({doc:source.value,extensions}),parent:host});
  field=view.contentDOM;
  const select=(start,end=start)=>{
    end=Math.max(0,Math.min(view.state.doc.length,end));
    start=Math.max(0,Math.min(end,start));
    view.dispatch({selection:EditorSelection.single(start,end)});
  };
  Object.defineProperties(field,{
    value:{get:()=>view.state.doc.toString(),set:value=>{
      const text=String(value ?? "").slice(0,limit);
      view.setState(EditorState.create({doc:text,selection:EditorSelection.cursor(text.length),extensions}));source.value=text;
      paint();
      queueMicrotask(()=>field.dispatchEvent(new Event("input",{bubbles:true})));
    }},
    maxLength:{get:()=>limit},
    selectionStart:{get:()=>view.state.selection.main.from,set:value=>select(value,view.state.selection.main.to)},
    selectionEnd:{get:()=>view.state.selection.main.to,set:value=>select(view.state.selection.main.from,value)},
    required:{get:()=>required,set:value=>{required=Boolean(value);field.setAttribute("aria-required",String(required));}},
    wrap:{get:()=>wrap,set:value=>{
      wrap=value==="off" ? "off" : "soft";
      view.dispatch({effects:wrapping.reconfigure(wrap==="off" ? [] : EditorView.lineWrapping)});
    }},
    scrollTop:{get:()=>view.scrollDOM.scrollTop,set:value=>{view.scrollDOM.scrollTop=value;}},
    scrollHeight:{get:()=>view.scrollDOM.scrollHeight},
    clientHeight:{get:()=>view.scrollDOM.clientHeight}
  });
  field.setSelectionRange=select;
  field.setRangeText=(text,start=field.selectionStart,end=field.selectionEnd,mode="preserve")=>{
    const inserted=String(text), stop=start+inserted.length, delta=inserted.length-(end-start);
    const map=position=>position<=start ? position : position>=end ? position+delta : stop;
    const selection=mode==="end" ? EditorSelection.single(stop) : mode==="start" ? EditorSelection.single(start) :
      mode==="select" ? EditorSelection.single(start,stop) :
      EditorSelection.single(map(field.selectionStart),map(field.selectionEnd));
    view.dispatch({changes:{from:start,to:end,insert:inserted},selection,
      annotations:[Transaction.userEvent.of("input.format"),isolateHistory.of("full")]});
  };
  return {field,host,view,reveal:()=>view.dispatch({effects:EditorView.scrollIntoView(field.selectionEnd,{y:"nearest"})})};
}
