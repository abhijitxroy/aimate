/* Local markdown-it 15.0.3; raw HTML and remote images are never rendered. */
const answerMarkdown = window.markdownit({html: false, breaks: false, linkify: false})
  .disable("image");
answerMarkdown.validateLink = url => {
  try { return ["https:", "http:"].includes(new URL(url).protocol); }
  catch { return false; }
};
const renderAnswerLink = answerMarkdown.renderer.rules.link_open ||
  ((tokens, index, options, env, renderer) => renderer.renderToken(tokens, index, options));
answerMarkdown.renderer.rules.link_open = (tokens, index, options, env, renderer) => {
  tokens[index].attrSet("target", "_blank");
  tokens[index].attrSet("rel", "noopener noreferrer");
  return renderAnswerLink(tokens, index, options, env, renderer);
};

function renderAnswer(body, text) {
  // Only the parser's escaped output enters this HTML sink. Never enable html
  // or add plugins that accept raw model-supplied HTML.
  body.innerHTML = answerMarkdown.render(text);
}
