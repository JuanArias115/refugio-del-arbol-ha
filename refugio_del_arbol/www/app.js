const controls = [
  { id: "external-lights", title: "Luces externas", icon: "lightbulb", active: false, available: true },
  { id: "night-lights", title: "Luces nocheros", icon: "moon", active: false, available: true },
  { id: "railing-light", title: "Luz baranda", icon: "fence", active: false, available: true },
  { id: "bridge-light", title: "Luz puente", icon: "bridge", active: false, available: true },
  { id: "jacuzzi-bubbles", title: "Burbujas del jacuzzi", icon: "waves", active: false, available: true, type: "jacuzzi" }
];

const icons = {
  lightbulb: '<svg viewBox="0 0 24 24"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M15.1 15.1A7 7 0 1 0 8.9 15.1c.5.5.8 1.2.8 1.9h4.6c0-.7.3-1.4.8-1.9Z"/></svg>',
  moon: '<svg viewBox="0 0 24 24"><path d="M20.8 15.2A9 9 0 0 1 8.8 3.2 9 9 0 1 0 20.8 15.2Z"/></svg>',
  fence: '<svg viewBox="0 0 24 24"><path d="M4 21V3l4 3 4-3 4 3 4-3v18"/><path d="M4 12h16"/></svg>',
  bridge: '<svg viewBox="0 0 24 24"><path d="M3 19h18"/><path d="M5 19v-4a7 7 0 0 1 14 0v4"/><path d="M8 19v-4a4 4 0 0 1 8 0v4"/><path d="M5 7h14"/><path d="M7 7V3m10 4V3"/></svg>',
  waves: '<svg viewBox="0 0 24 24"><path d="M2 7c1.5 0 1.5 1 3 1s1.5-1 3-1 1.5 1 3 1 1.5-1 3-1 1.5 1 3 1 1.5-1 3-1"/><path d="M2 12c1.5 0 1.5 1 3 1s1.5-1 3-1 1.5 1 3 1 1.5-1 3-1 1.5 1 3 1 1.5-1 3-1"/><path d="M2 17c1.5 0 1.5 1 3 1s1.5-1 3-1 1.5 1 3 1 1.5-1 3-1 1.5 1 3 1 1.5-1 3-1"/></svg>'
};

const grid = document.querySelector("#control-grid");
const template = document.querySelector("#control-template");
const toast = document.querySelector("#toast");
let toastTimer;
let apiAvailable = false;

function labelFor(control) {
  if (!control.available) return "No disponible";
  return control.active ? "Encendido" : "Apagado";
}

function showToast(message) {
  toast.textContent = message;
  toast.classList.add("is-visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("is-visible"), 2400);
}

function updateControl(control) {
  const card = grid.querySelector(`[data-control="${control.id}"]`);
  const button = card.querySelector(".control-switch");
  card.classList.toggle("is-active", control.active && control.available);
  card.classList.toggle("is-unavailable", !control.available);
  card.querySelector(".control-copy p").textContent = labelFor(control);
  button.disabled = !control.available;
  button.setAttribute("aria-checked", String(control.active && control.available));
  button.querySelector(".sr-only").textContent = `${control.title}: ${labelFor(control)}`;
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status", { cache: "no-store" });
    if (!response.ok) throw new Error("Estado no disponible");
    const data = await response.json();
    apiAvailable = true;

    controls.forEach((control) => {
      const state = data.controls?.[control.id];
      control.available = state === "on" || state === "off";
      control.active = state === "on";
      updateControl(control);
    });
  } catch {
    apiAvailable = false;
    controls.forEach((control) => {
      control.available = false;
      control.active = false;
      updateControl(control);
    });
  }
}

async function toggleControl(control) {
  if (!control.available) return;
  const desiredState = !control.active;

  if (!apiAvailable) {
    control.active = desiredState;
    updateControl(control);
    showToast(`${control.title}: ${labelFor(control).toLowerCase()}`);
    return;
  }

  const card = grid.querySelector(`[data-control="${control.id}"]`);
  const button = card.querySelector(".control-switch");
  button.disabled = true;
  control.active = desiredState;
  updateControl(control);
  try {
    const response = await fetch(`/api/controls/${control.id}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ state: desiredState })
    });
    if (!response.ok) throw new Error("No se pudo actualizar el control");
    const data = await response.json();
    control.available = data.state === "on" || data.state === "off";
    control.active = data.state === "on";
    updateControl(control);
    showToast(`${control.title}: ${labelFor(control).toLowerCase()}`);
    navigator.vibrate?.(12);
    window.setTimeout(refreshStatus, 2000);
  } catch {
    control.active = !desiredState;
    updateControl(control);
    showToast(`No fue posible actualizar ${control.title.toLowerCase()}`);
    await refreshStatus();
  } finally {
    updateControl(control);
  }
}

function renderControls() {
  for (const control of controls) {
    const fragment = template.content.cloneNode(true);
    const card = fragment.querySelector(".control-card");
    const button = fragment.querySelector(".control-switch");
    card.dataset.control = control.id;
    card.classList.toggle("jacuzzi", control.type === "jacuzzi");
    card.querySelector(".control-icon").innerHTML = icons[control.icon];
    card.querySelector("h3").textContent = control.title;
    button.addEventListener("click", () => toggleControl(control));
    grid.append(fragment);
    updateControl(control);
  }
}

document.querySelector("#today").textContent = new Intl.DateTimeFormat("es-ES", {
  weekday: "long",
  day: "numeric",
  month: "long"
}).format(new Date());

renderControls();
refreshStatus();
window.setInterval(refreshStatus, 30000);
