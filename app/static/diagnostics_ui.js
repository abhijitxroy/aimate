/* Sanitized diagnostics are available only to administrators/developers. */
$("#openDiagnostics").onclick = async () => {
  try {
    const result=await api("/api/diagnostics");
    $("#auditDialog").querySelector("h2").textContent="Diagnostics";
    $("#auditContent").textContent=JSON.stringify(result,null,2);
    $("#auditDialog").showModal();
  } catch(error) { $("#settingsStatus").textContent=error.message; }
};
