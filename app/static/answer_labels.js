/* Optional semantic labels. Retain safe Markdown children and original source. */
window.AiMateAnswerLabels = Object.freeze({
  render(body) {
    if(window.AiMateFeatures?.answerLabels===false) return;
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
