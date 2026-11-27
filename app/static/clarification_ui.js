/* Choice controls fill a reply for review; they never send it automatically. */
window.AiMateClarification = (() => {
  "use strict";
  function render(message, completion) {
    if (completion?.status !== "awaiting_input" || message.root.querySelector(".clarification-choices") ||
        !completion.options?.length) return;
    const section = document.createElement("section");
    section.className = "clarification-choices";
    section.setAttribute("aria-label", "Answer clarification");
    const status = document.createElement("small");
    const fill = answers => {
      const field = document.querySelector("#question");
      const reply = `Regarding “${completion.question}”: ${answers.join(", ")}`;
      field.setRangeText((field.value ? "\n\n" : "") + reply, field.value.length, field.value.length, "end");
      field.dispatchEvent(new Event("input", {bubbles: true}));
      field.focus({preventScroll: true});
      window.AiMateRichComposer?.reveal();
      status.textContent = "Answer added to askbar. Review and send.";
      for (const control of section.querySelectorAll("button,input")) control.disabled = true;
    };
    if (completion.kind === "multiple") {
      for (const option of completion.options) {
        const label = document.createElement("label"), input = document.createElement("input");
        input.type = "checkbox"; input.value = option;
        label.append(input, document.createTextNode(option)); section.append(label);
      }
      const button = document.createElement("button");
      button.type = "button"; button.textContent = "Use selection";
      button.onclick = () => {
        const answers = [...section.querySelectorAll("input:checked")].map(node => node.value);
        if (!answers.length) { status.textContent = "Choose at least one option, or type your answer."; return; }
        fill(answers);
      };
      section.append(button);
    } else {
      for (const option of completion.options) {
        const button = document.createElement("button");
        button.type = "button"; button.textContent = option;
        button.onclick = () => fill([option]); section.append(button);
      }
    }
    section.append(status); message.root.append(section);
  }
  return Object.freeze({render});
})();
