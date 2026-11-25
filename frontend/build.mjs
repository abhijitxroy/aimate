import {build} from "esbuild";
import {readFile,writeFile,readdir} from "node:fs/promises";
import {dirname,resolve,join} from "node:path";
import {fileURLToPath} from "node:url";
const root=dirname(fileURLToPath(import.meta.url));
await build({entryPoints:[join(root,"rich-editor.js")],bundle:true,minify:true,
  format:"iife",globalName:"AiMateRichComposerCore",target:["es2022"],legalComments:"eof",
  outfile:resolve(root,"../app/static/vendor/rich-editor.min.js")});
const licenses=[];
for(const entry of (await readdir(join(root,"node_modules/.pnpm"),{withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name,"en"))) {
  if(!entry.isDirectory()) continue;
  const directory=entry.name;
  if(directory.startsWith("@esbuild") || directory.startsWith("esbuild@") || directory==="node_modules") continue;
  const modules=join(root,"node_modules/.pnpm",directory,"node_modules");
  async function walk(folder) {
    for(const entry of (await readdir(folder,{withFileTypes:true})).sort((a,b)=>a.name.localeCompare(b.name,"en"))) {
      if(entry.isDirectory() && entry.name.startsWith("@")) await walk(join(folder,entry.name));
      else if(entry.isDirectory()) {
        for(const name of ["LICENSE","LICENSE.txt","LICENSE.md"]) {
          try {licenses.push(`\n${directory}\n${await readFile(join(folder,entry.name,name),"utf8")}`);break;}
          catch(error) {if(error.code!=="ENOENT") throw error;}
        }
      }
    }
  }
  await walk(modules);
}
await writeFile(resolve(root,"../app/static/vendor/rich-editor-LICENSE.txt"),
  "AiMate editor dependencies; MIT licenses follow.\n"+licenses.join("\n"),"utf8");
