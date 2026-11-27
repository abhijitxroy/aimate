/* Optional sidebar presentation; selection and chat operations stay unchanged. */
(() => {
  if (window.AiMateFeatures?.transparentChatRows === false) return;
  document.documentElement.classList.add("transparent-chat-rows");
})();
