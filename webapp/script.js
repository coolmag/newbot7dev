async function tick() {
  const el = document.getElementById("status");
  try {
    const r = await fetch("/api/radio/status");
    const j = await r.json();
    el.textContent = JSON.stringify(j, null, 2);
  } catch (e) {
    el.textContent = String(e);
  }
}
tick();
setInterval(tick, 3000);