/* Conversation-bound streams; a page may navigate while another chat answers. */
window.AiMateRuns = (() => {
  const runs = new Map();
  return {
    get: id => runs.get(id),
    size: () => runs.size,
    start(id, run) {
      if (runs.has(id)) throw new Error("This conversation is already answering.");
      if (runs.size >= 3) throw new Error("Three chats are answering. Wait for one to finish.");
      runs.set(id, run);
    },
    finish(id, run) { if (runs.get(id) === run) runs.delete(id); },
    abortAll() { for (const run of runs.values()) run.controller.abort(); }
  };
})();
