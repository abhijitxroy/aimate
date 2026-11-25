/* Optional task priorities, enabled only by the backend's priority catalogue. */
(() => {
  "use strict";
  const input=document.getElementById("todoPriority"),filter=document.getElementById("todoPriorityFilter");
  let enabled=false;
  const labels={P0:"P0 · Critical",P1:"P1 · High",P2:"P2 · Normal",P3:"P3 · Low"};
  function configure(response,render) {
    enabled=Boolean(response.priorities?.length) && window.AiMateFeatures?.todoPriorities !== false;
    for(const [select,all] of [[input,false],[filter,true]]) {
      const previous=select.value;
      select.replaceChildren();
      const values=all ? ["",...(response.priorities || [])] : response.priorities || [];
      for(const value of values) {
        const option=document.createElement("option");option.value=value;
        option.textContent=value ? labels[value] || value : "All priorities";select.append(option);
      }
      select.value=values.includes(previous) ? previous : all ? "" : "P2";
      select.hidden=!enabled;
    }
    filter.onchange=render;
  }
  function rows(tasks) {
    if(!enabled) return tasks;
    return tasks.filter(task=>!filter.value || (task.priority || "P2")===filter.value)
      .sort((a,b)=>Number(Boolean(a.completed))-Number(Boolean(b.completed)) ||
        (a.priority || "P2").localeCompare(b.priority || "P2"));
  }
  function badge(task) {
    if(!enabled) return null;
    const node=document.createElement("span"),value=task.priority || "P2";
    node.className="todo-priority";node.dataset.priority=value;node.textContent=value;
    node.title=labels[value] || value;return node;
  }
  window.AiMateTodoPriorities=Object.freeze({configure,rows,badge,
    reset(){input.value="P2";input.disabled=false;},
    edit(task){input.value=task.priority || "P2";},
    lock(locked){input.disabled=locked;},
    payload(){return enabled ? {priority:input.value} : {};}
  });
})();
