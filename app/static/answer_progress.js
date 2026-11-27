/* Optional progress summaries, transformed only after safe Markdown rendering. */
window.AiMateAnswerProgress = Object.freeze({
  render(body) {
    if (window.AiMateFeatures?.answerProgress === false) return;
    // A sole, explicitly authored tone in a table cell is a compact result label.
    // Never infer Passed/Verified from ordinary words or recolour entire tables.
    for (const cell of body.querySelectorAll("td")) {
      const tone = cell.firstElementChild;
      if (cell.children.length === 1 && tone?.matches(
        ".answer-tone-success,.answer-tone-info,.answer-tone-warning,.answer-tone-danger"
      ) && cell.textContent.trim() === tone.textContent.trim()) {
        tone.classList.add("answer-progress-status");
      }
    }
    for (const quote of body.querySelectorAll("blockquote")) {
      const title = quote.firstElementChild, first = title?.firstChild;
      const match = title?.tagName === "P" && first?.nodeType === 3
        && first.textContent.match(/^\[!PROGRESS\]\s*/);
      const list = [...quote.children].find(child => child.tagName === "OL");
      if (!match || !list || !title.textContent.slice(match[0].length).trim()) continue;
      first.textContent = first.textContent.slice(match[0].length);
      title.classList.add("answer-progress-title");
      list.classList.add("answer-progress-steps");
      const panel = document.createElement("section");
      panel.className = "answer-progress";
      panel.setAttribute("aria-label", title.textContent);
      for (const step of list.children) {
        if (step.tagName !== "LI") continue;
        step.classList.add("answer-progress-step");
        for (const tone of step.querySelectorAll(
          ".answer-tone-success,.answer-tone-info,.answer-tone-warning,.answer-tone-danger"
        )) tone.classList.add("answer-progress-status");
      }
      panel.append(...quote.childNodes);
      quote.replaceWith(panel);
    }
  }
});
