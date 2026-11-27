/* Optional semantic labels. Retain safe Markdown children and original source. */
window.AiMateAnswerLabels = Object.freeze({
  render(body) {
    if(window.AiMateFeatures?.answerLabels===false) return;
    body.classList.add("answer-presented");
    const circle="M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0";
    const icons={success:circle+" M7 12l3 3 7-7",warning:"M12 3 2 21h20L12 3 M12 9v5 M12 17v1",
      danger:circle+" M12 7v6 M12 16v1",note:circle+" M12 11v6 M12 7v1",
      tip:"M12 3 15 9l6 3-6 3-3 6-3-6-6-3 6-3 3-6"};
    for(const callout of body.querySelectorAll(".answer-callout")) {
      const title=callout.querySelector(".callout-title");
      if(!title || title.querySelector("svg")) continue;
      const kind=Object.keys(icons).find(key=>callout.classList.contains(key));
      if(!kind) continue;
      const svg=document.createElementNS("http://www.w3.org/2000/svg","svg");
      svg.setAttribute("viewBox","0 0 24 24");svg.setAttribute("aria-hidden","true");
      svg.setAttribute("fill","none");svg.setAttribute("stroke","currentColor");
      svg.setAttribute("stroke-width","1.8");svg.setAttribute("stroke-linecap","round");
      svg.setAttribute("stroke-linejoin","round");
      const path=document.createElementNS(svg.namespaceURI,"path");
      path.setAttribute("d",icons[kind]);svg.append(path);
      const text=document.createElement("span");
      text.textContent=title.textContent.replace(/^[^\w]+\s*/,"");
      title.replaceChildren(svg,text);
    }
    for(const quote of body.querySelectorAll("blockquote")) {
      const paragraph=quote.querySelector("p"),first=paragraph?.firstChild;
      const match=first?.nodeType===3 && first.textContent.match(/^\[!(KEEP|CHECK|REMOVE|OPTIONAL)\]\s*/i);
      if(!match) continue;
      const label=match[1].toUpperCase();
      first.textContent=first.textContent.slice(match[0].length);
      if(!paragraph.textContent.trim() && !paragraph.childElementCount) paragraph.remove();
      const card=document.createElement("section");
      card.className="answer-classification "+label.toLowerCase();
      card.setAttribute("aria-label",label+" finding");
      const badge=document.createElement("span");
      badge.className="answer-classification-label";badge.textContent=label;
      card.append(badge,...quote.childNodes);quote.replaceWith(card);
    }
    for(const card of body.querySelectorAll(".answer-classification")) {
      if(card.parentElement.classList.contains("answer-classification-grid")) continue;
      const grid=document.createElement("div");
      grid.className="answer-classification-grid";
      grid.setAttribute("aria-label","Classified findings");
      card.before(grid);
      let next=card;
      while(next?.classList.contains("answer-classification")) {
        const following=next.nextElementSibling;
        grid.append(next);next=following;
      }
    }
  }
});
