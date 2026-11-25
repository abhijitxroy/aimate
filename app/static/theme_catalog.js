(function(root) {
  const names=["life","brown-gold","custom"];
  const keys=["bg","panel","text","muted","accent","line","danger","success","warning"];
  const palettes={
    life:{bg:"#17152b",panel:"#25223b",text:"#f5f1ff",muted:"#c6bddc",accent:"#b5a4ff",line:"#615977",danger:"#ffb5cc",success:"#8ee5bb",warning:"#ffd888"},
    "brown-gold":{bg:"#241a14",panel:"#36281d",text:"#fff1dc",muted:"#d9c3a2",accent:"#f2c76e",line:"#715a3e",danger:"#ffb6ae",success:"#a8deb1",warning:"#f2c76e"}
  };
  function luminance(hex) {
    const channels=hex.slice(1).match(/../g).map(v=>parseInt(v,16)/255).map(v=>v<=.04045 ? v/12.92 : ((v+.055)/1.055)**2.4);
    return channels[0]*.2126+channels[1]*.7152+channels[2]*.0722;
  }
  function contrast(a,b) {
    const x=luminance(a),y=luminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05);
  }
  function validate(value) {
    if(!value || Array.isArray(value) || Object.keys(value).sort().join(",")!=="colors,name,version" || value.version!==1 ||
       typeof value.name!=="string" || !value.name.trim() || value.name.length>40 ||
       !value.colors || Array.isArray(value.colors) || Object.keys(value.colors).sort().join(",")!==[...keys].sort().join(","))
      throw new Error("Use a version 1 theme with a name and the nine required colour tokens.");
    const colors={};
    for(const key of keys) {
      if(typeof value.colors[key]!=="string" || !/^#[0-9a-f]{6}$/i.test(value.colors[key])) throw new Error("Theme colours must be six-digit hex values.");
      colors[key]=value.colors[key];
    }
    if(luminance(colors.bg)>.12 || luminance(colors.panel)>.12)
      throw new Error("Imported themes currently need dark surfaces to preserve readable syntax colours. Use Beige for a light theme.");
    for(const background of ["bg","panel"]) for(const foreground of ["text","muted","accent","danger","success","warning"])
      if(contrast(colors[background],colors[foreground])<4.5) throw new Error("Theme text colours need at least 4.5:1 contrast against both surfaces.");
    return {version:1,name:value.name.trim(),colors};
  }
  const api={validate,contrast,palettes,names:()=>root.AiMateFeatures?.extraThemes===false ? [] : names,
    apply(theme) {
      if(!root.document) return;
      for(const key of keys) root.document.documentElement.style.removeProperty("--"+key);
      if(root.AiMateFeatures?.extraThemes===false) return;
      let colors=palettes[theme];
      if(theme==="custom") {
        try { colors=validate(JSON.parse(root.localStorage.getItem("aimate.customTheme"))).colors; } catch { colors=palettes.life; }
      }
      if(colors) for(const key of keys) root.document.documentElement.style.setProperty("--"+key,colors[key]);
    }};
  if(typeof module!=="undefined" && module.exports) module.exports=api;
  if(!root.document) return;
  root.AiMateThemes=Object.freeze(api);
  root.document.addEventListener("DOMContentLoaded",()=>{
    if(root.AiMateFeatures?.extraThemes===false) return;
    const dialog=root.document.querySelector("#appearanceDialog"),options=dialog.querySelector(".theme-options");
    for(const [key,label,description] of [["life","Life","Colourful"],["brown-gold","Brown & gold","Warm & rich"],["custom","Imported","Your palette"]]) {
      const button=root.document.createElement("button");
      button.type="button";button.className="theme-option";button.dataset.themeChoice=key;button.setAttribute("aria-pressed","false");
      const preview=root.document.createElement("span");preview.className="theme-preview "+key;preview.setAttribute("aria-hidden","true");preview.innerHTML="<i></i><b></b>";
      const title=root.document.createElement("strong"),detail=root.document.createElement("small");title.textContent=label;detail.textContent=description;
      button.append(preview,title,detail);button.onclick=()=>root.AiMateAppearance.apply(key);options.append(button);
    }
    const row=root.document.createElement("div");row.className="theme-import-row";
    const input=root.document.createElement("input");input.type="file";input.accept=".json,application/json";input.hidden=true;
    const load=root.document.createElement("button");load.type="button";load.textContent="Import theme (.json)";load.onclick=()=>input.click();
    const template=root.document.createElement("button");template.type="button";template.textContent="Template";
    const error=root.document.createElement("p");error.className="hint";error.setAttribute("role","status");
    template.onclick=()=>{
      const url=URL.createObjectURL(new Blob([JSON.stringify({version:1,name:"My theme",colors:palettes["brown-gold"]},null,2)],{type:"application/json"}));
      const link=root.document.createElement("a");link.href=url;link.download="aimate-theme.json";link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
    };
    input.onchange=async()=>{
      const file=input.files[0];if(!file) return;
      try {
        if(file.size>4096) throw new Error("Use a theme JSON file up to 4 KB.");
        const theme=validate(JSON.parse(await file.text()));
        root.localStorage.setItem("aimate.customTheme",JSON.stringify(theme));
        root.AiMateAppearance.apply("custom");error.className="hint success";error.textContent="Theme imported: "+theme.name;
      } catch(e) {error.className="hint error";error.textContent=e instanceof SyntaxError ? "Invalid JSON. Start from the template." : e.message;}
      finally {input.value="";}
    };
    row.append(load,template,input);dialog.append(row,error);
    root.dispatchEvent(new CustomEvent("aimate-theme"));
  });
})(typeof window!=="undefined" ? window : globalThis);
