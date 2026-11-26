/* Optional clipboard cleanup; attachments and code keep their original bytes. */
(function(root) {
  "use strict";
  function clean(text) {
    const normal=text.replace(/\r\n?/g,"\n");
    if(/^\s*[\[{]/.test(normal) || /^(?: {4}|\t)\S/m.test(normal)) return text; // Structured data and indented code are evidence.
    const result=[];let fence=null;
    for(const line of normal.split("\n")) {
      const marker=line.match(/^\s{0,3}(`{3,}|~{3,})/);
      if(marker) {
        if(!fence) fence={character:marker[1][0],length:marker[1].length};
        else if(marker[1][0]===fence.character && marker[1].length>=fence.length) fence=null;
        result.push(line);continue;
      }
      if(fence || /^( {4}|\t)\S/.test(line)) {result.push(line);continue;}
      if(/^\s*[-+*]\s*$/.test(line)) continue;
      if(!line.trim() && (!result.length || !result.at(-1).trim())) continue;
      if(/^\s*(?:[-+*]|\d+[.)])\s+\S/.test(line) && result.length>1 &&
        !result.at(-1).trim() && /^\s*(?:[-+*]|\d+[.)])\s+\S/.test(result.at(-2))) result.pop();
      result.push(line);
    }
    if(!fence) while(result.length && !result.at(-1).trim()) result.pop();
    return result.join("\n");
  }
  if(typeof module==="object" && module.exports) module.exports={clean};
  root.AiMatePasteCleanup=Object.freeze({clean});
  if(typeof document==="undefined") return;
  document.addEventListener("paste",event=>{
    if(root.AiMateFeatures?.pasteCleanup===false || document.querySelector("#workspace")?.hidden ||
       document.querySelector("dialog[open]") || event.clipboardData?.files.length) return;
    const field=document.querySelector("#question");
    if(!field || !(event.target===field || field.contains(event.target) || root.chatInputAvailable?.(event.target))) return;
    const text=event.clipboardData?.getData("text/plain");
    // Large clipboard evidence follows the existing lossless attachment path.
    if(!text || text.length>4000) return;
    const value=clean(text);
    if(value===text || typeof root.insertQuestion!=="function") return;
    event.preventDefault();event.stopPropagation();
    root.insertQuestion(value);
  },true);
})(globalThis);
