const statusGrid = document.querySelector("#status-grid");
const settingsForm = document.querySelector("#settings-form");
const activityLog = document.querySelector("#activity-log");
const connectionStatus = document.querySelector("#connection-status");
const toast = document.querySelector("#toast");
const statusTemplate = document.querySelector("#status-template");
const settingTemplate = document.querySelector("#setting-template");
let controls = [];
let toastTimer;

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 2600);
}

function labelForState(state) {
  if (state === "on") return "Encendido";
  if (state === "off") return "Apagado";
  return "No disponible";
}

function renderStatus(states) {
  statusGrid.replaceChildren();
  for (const control of controls) {
    const fragment = statusTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".status-card");
    const state = states[control.id] || "unavailable";
    card.classList.add(`is-${state}`);
    card.querySelector(".relay-number").textContent = `R${control.relay}`;
    card.querySelector("h3").textContent = control.title;
    card.querySelector("p").textContent = labelForState(state);
    statusGrid.append(fragment);
  }
}

function renderSettings() {
  settingsForm.replaceChildren();
  for (const control of controls) {
    const fragment = settingTemplate.content.cloneNode(true);
    const row = fragment.querySelector(".setting-row");
    row.dataset.id = control.id;
    row.querySelector(".relay-badge").textContent = `Relé ${control.relay}`;
    row.querySelector("strong").textContent = control.title;
    row.querySelector("small").textContent = "Asignación física protegida";
    const input = row.querySelector(".name-input");
    input.value = control.title;
    input.dataset.id = control.id;
    const toggle = row.querySelector(".enabled-input");
    toggle.checked = control.enabled;
    toggle.dataset.id = control.id;
    settingsForm.append(fragment);
  }
}

function formatTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Ahora" : new Intl.DateTimeFormat("es-CO", { dateStyle: "short", timeStyle: "short" }).format(date);
}

function describeEvent(entry) {
  if (entry.event === "guest_control") return `Huésped: Relé ${entry.relay} ${entry.requested ? "encendido" : "apagado"}`;
  if (entry.event === "guest_control_failed") return `Falló la orden en relé ${entry.relay}`;
  if (entry.event === "admin_config") return `${entry.user || "Administrador"} actualizó la configuración`;
  return "Actividad del portal";
}

function renderLogs(entries) {
  activityLog.replaceChildren();
  if (!entries.length) {
    activityLog.textContent = "Aún no hay actividad registrada.";
    return;
  }
  for (const entry of entries.slice(0, 18)) {
    const item = document.createElement("div");
    const description = document.createElement("span");
    const time = document.createElement("time");
    item.className = "log-entry";
    description.textContent = describeEvent(entry);
    time.textContent = formatTime(entry.at);
    item.append(description, time);
    activityLog.append(item);
  }
}

async function refresh() {
  connectionStatus.textContent = "Actualizando";
  try {
    const [statusResponse, logsResponse] = await Promise.all([
      fetch("./api/admin/status", { cache: "no-store" }),
      fetch("./api/admin/logs", { cache: "no-store" })
    ]);
    if (!statusResponse.ok || !logsResponse.ok) throw new Error("No disponible");
    const status = await statusResponse.json();
    const logs = await logsResponse.json();
    controls = status.controls || [];
    renderStatus(status.states || {});
    renderSettings();
    renderLogs(logs.entries || []);
    connectionStatus.textContent = "Conectado";
    connectionStatus.classList.add("is-ready");
  } catch {
    connectionStatus.textContent = "Sin conexión";
    connectionStatus.classList.remove("is-ready");
    showToast("No fue posible actualizar la administración.");
  }
}

async function saveSettings() {
  const rows = [...settingsForm.querySelectorAll(".setting-row")];
  const updated = rows.map((row) => ({
    id: row.dataset.id,
    title: row.querySelector(".name-input").value,
    enabled: row.querySelector(".enabled-input").checked
  }));
  const button = document.querySelector("#save-settings");
  button.disabled = true;
  try {
    const response = await fetch("./api/admin/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ controls: updated })
    });
    if (!response.ok) throw new Error("No disponible");
    const data = await response.json();
    controls = data.controls || [];
    renderSettings();
    showToast("Configuración guardada para el portal.");
    await refresh();
  } catch {
    showToast("No se pudieron guardar los cambios.");
  } finally {
    button.disabled = false;
  }
}

document.querySelector("#refresh").addEventListener("click", refresh);
document.querySelector("#save-settings").addEventListener("click", saveSettings);
refresh();
window.setInterval(refresh, 30000);
