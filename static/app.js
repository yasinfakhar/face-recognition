const $ = (id) => document.getElementById(id);
const today = new Date().toISOString().slice(0, 10);
$("report-date").value = today;

function showMessage(text, error = false) { $("message").textContent = text; $("message").style.color = error ? "#ff8b8b" : "#ffb86b"; }
async function jsonRequest(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Request failed");
  return data;
}
async function refreshStatus() {
  try {
    const data = await jsonRequest("/api/status");
    const status = $("status"); status.textContent = data.running ? "LIVE" : "OFFLINE"; status.className = `status ${data.running ? "live" : "idle"}`;
    $("source-label").textContent = data.source || "No source";
    $("recognized").textContent = data.recognized.length;
    if (data.recognized.length) $("last-event").textContent = data.recognized[data.recognized.length - 1];
    if (data.last_error) showMessage(data.last_error, true);
    $("empty").style.display = data.running ? "none" : "block";
  } catch (error) { $("status").textContent = "UNAVAILABLE"; $("status").className = "status error"; }
}
async function loadReport() {
  try { const data = await jsonRequest(`/api/report?date=${$("report-date").value}`); $("report-summary").textContent = `${data.count} attendance event${data.count === 1 ? "" : "s"}`; $("report-body").innerHTML = data.rows.map(row => `<tr><td>${row.timestamp}</td><td>${row.name}</td></tr>`).join(""); }
  catch (error) { showMessage(error.message, true); }
}
$("start").onclick = async () => { try { await jsonRequest("/api/start", { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({ source:$("source").value, audio_dir:$("audio-dir").value, audio_player:$("audio-player").value }) }); showMessage("Feed started"); } catch (error) { showMessage(error.message, true); } };
$("stop").onclick = async () => { await jsonRequest("/api/stop", { method:"POST" }); showMessage("Feed stopped"); };
$("report-date").onchange = loadReport;
$("download").onclick = () => { window.location = `/api/report/download?date=${$("report-date").value}`; };
$("register").onsubmit = async (event) => { event.preventDefault(); try { const data = await jsonRequest("/api/register", { method:"POST", body:new FormData(event.target) }); showMessage(data.message); event.target.reset(); } catch (error) { showMessage(error.message, true); } };
refreshStatus(); loadReport(); setInterval(refreshStatus, 1500);
