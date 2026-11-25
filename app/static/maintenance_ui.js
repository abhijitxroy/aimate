let cleanupReview=null;
async function loadCleanup() {
  cleanupReview=await api("/api/maintenance");
  const list=$("#cleanupItems"); list.replaceChildren();
  for(const row of cleanupReview.documents) list.append(element("p","",`Attachment: ${row.name}`));
  for(const row of cleanupReview.logs) list.append(element("p","",`Rotated diagnostics: ${row.name}`));
  list.append(element("p","hint",`${cleanupReview.expired_cache.length} expired snapshots · ${(cleanupReview.estimated_bytes/1024).toFixed(1)} KB removable content`));
  $("#cleanupNotice").textContent=cleanupReview.notice;
  $("#confirmCleanup").disabled=!cleanupReview.documents.length && !cleanupReview.expired_cache.length && !cleanupReview.logs.length;
}
$("#openMaintenance").onclick=async()=>{
  $("#cleanupError").textContent="";
  $("#cleanupDialog").showModal();
  try { await loadCleanup(); } catch(error) { $("#cleanupError").textContent=error.message; }
};
$("#confirmCleanup").onclick=async()=>{
  $("#confirmCleanup").disabled=true;
  try {
    const result=await api("/api/maintenance/cleanup",{method:"POST",body:JSON.stringify({fingerprint:cleanupReview.fingerprint})});
    await loadCleanup();
    $("#cleanupError").className="success";
    $("#cleanupError").textContent=`Completed · ${result.removed.documents} attachments, ${result.removed.expired_cache} snapshots, ${result.removed.logs} logs removed${result.removed.skipped_logs ? " · busy/changed logs kept" : ""}.`;
  } catch(error) { $("#cleanupError").className="error"; $("#cleanupError").textContent=error.message; }
};
