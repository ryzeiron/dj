/* beamctl — interface live. Pas de framework : fetch + canvas + DOM. */
"use strict";

const TOKEN = new URLSearchParams(location.search).get("t");
const $ = (id) => document.getElementById(id);

const COLORS = {
  "blanc": [253, 253, 245], "rouge": [255, 45, 45], "vert": [37, 224, 90],
  "bleu": [43, 107, 255], "jaune": [255, 210, 30], "orange": [255, 122, 24],
  "cyan": [34, 224, 255], "rose": [255, 63, 174], "violet": [160, 60, 255],
  "arc-en-ciel": null   // teinte qui defile
};
const LENGTHS = [0.5, 1, 2, 4, 8, 16, 32];

let show = null;      // patch, looks, profils, effets
let status = null;    // etat courant du moteur
let touching = false; // un fader est en cours de manipulation
let smooth = [];      // etats lisses pour l'animation
let expert = localStorage.getItem("beamctl.expert") === "1";

/* ------------------------------------------------------------------ api */
async function api(path, body) {
  const url = path + (TOKEN ? (path.includes("?") ? "&" : "?") + "t=" + encodeURIComponent(TOKEN) : "");
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(url, options);
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).error || response.status);
  return response.json();
}

function alertBox(message) {
  const box = $("alert");
  box.textContent = message || "";
  box.classList.toggle("hidden", !message);
}

/* --------------------------------------------------------------- helpers */
function profileOf(fixture) {
  return (show.profiles || []).find((p) => p.id === (fixture || {}).profile_id);
}
function mainProfile() {
  return profileOf((show.fixtures || [])[0]) || (show.profiles || [])[0];
}
function currentLook() {
  return (status && status.look) || {};
}
function rgbOf(name, time) {
  const rgb = COLORS[name];
  if (rgb) return rgb;
  const hue = ((time || 0) * 60) % 360;          // arc-en-ciel anime
  const f = (n) => {
    const k = (n + hue / 30) % 12;
    return Math.round(255 * (1 - Math.max(-1, Math.min(Math.min(k - 3, 9 - k), 1))));
  };
  return [f(0), f(8), f(4)];
}
function cssColor(name, alpha, time) {
  const [r, g, b] = rgbOf(name, time);
  return alpha === undefined ? `rgb(${r},${g},${b})` : `rgba(${r},${g},${b},${alpha})`;
}

/* ------------------------------------------------------- apercu scenique */
function tickSmooth() {
  const fixtures = (status && status.fixtures) || [];
  if (smooth.length !== fixtures.length) {
    smooth = fixtures.map((f) => Object.assign({ pan: 0.5, tilt: 0.5, dimmer: 0 },
                                               f.state || {}));
  }
  fixtures.forEach((fixture, index) => {
    const target = fixture.state || {};
    const current = smooth[index];
    const k = 0.25;                                  // lissage exponentiel
    current.pan += ((target.pan ?? 0.5) - current.pan) * k;
    current.tilt += ((target.tilt ?? 0.5) - current.tilt) * k;
    current.dimmer += ((target.dimmer ?? 0) - current.dimmer) * 0.35;
    current.color = target.color;
    current.strobe = target.strobe || 0;
  });
}

function drawStage(timestamp) {
  const canvas = $("stage");
  const context = canvas.getContext("2d");
  const ratio = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  if (canvas.width !== Math.round(width * ratio)) {
    canvas.width = Math.round(width * ratio);
    canvas.height = Math.round(height * ratio);
  }
  context.setTransform(ratio, 0, 0, ratio, 0, 0);

  const time = timestamp / 1000;
  context.clearRect(0, 0, width, height);

  // sol
  const floor = context.createLinearGradient(0, height * 0.55, 0, height);
  floor.addColorStop(0, "#0e1119");
  floor.addColorStop(1, "#161b26");
  context.fillStyle = floor;
  context.fillRect(0, height * 0.55, width, height * 0.45);
  context.fillStyle = "#0b0d12";
  context.fillRect(0, 0, width, height * 0.55);

  const count = smooth.length;
  if (!count) return;

  context.globalCompositeOperation = "lighter";
  smooth.forEach((state, index) => {
    const headX = width * (index + 0.5) / count;
    const headY = 16;
    const targetX = state.pan * width;
    const targetY = height * 0.42 + state.tilt * height * 0.55;

    let level = Math.max(0, Math.min(1, state.dimmer));
    if (state.strobe > 0) {                          // clignotement visible
      level *= (Math.sin(time * state.strobe * Math.PI * 2) > 0) ? 1 : 0.08;
    }
    if (level < 0.01) return;

    const color = (alpha) => cssColor(state.color, alpha, time);
    const spread = 14 + level * 12;

    const gradient = context.createLinearGradient(headX, headY, targetX, targetY);
    gradient.addColorStop(0, color(0.8 * level));
    gradient.addColorStop(1, color(0.12 * level));
    context.fillStyle = gradient;
    context.beginPath();
    context.moveTo(headX - 5, headY);
    context.lineTo(headX + 5, headY);
    context.lineTo(targetX + spread, targetY);
    context.lineTo(targetX - spread, targetY);
    context.closePath();
    context.fill();

    const pool = context.createRadialGradient(targetX, targetY, 0, targetX, targetY, spread * 2);
    pool.addColorStop(0, color(0.95 * level));
    pool.addColorStop(1, color(0));
    context.fillStyle = pool;
    context.beginPath();
    context.ellipse(targetX, targetY, spread * 2, spread * 0.9, 0, 0, Math.PI * 2);
    context.fill();
  });

  // tetes
  context.globalCompositeOperation = "source-over";
  smooth.forEach((state, index) => {
    const headX = width * (index + 0.5) / count;
    context.fillStyle = "#2a3040";
    context.fillRect(headX - 11, 4, 22, 13);
    context.fillStyle = cssColor(state.color, Math.max(0.15, state.dimmer), time);
    context.fillRect(headX - 6, 14, 12, 4);
  });
}

function animate(timestamp) {
  tickSmooth();
  drawStage(timestamp || 0);
  requestAnimationFrame(animate);
}

/* ------------------------------------------------------------- rendering */
function renderLooks() {
  const grid = $("lookGrid");
  grid.innerHTML = "";
  (show.looks || []).forEach((look, index) => {
    const button = document.createElement("button");
    button.className = "look" + (status && status.active_look_id === look.id ? " active" : "");
    const key = index < 9 ? String(index + 1) : index === 9 ? "0" : "";
    const palette = look.color_mode === "static"
      ? [look.color]
      : (look.colors.length ? look.colors : [look.color]);
    const chips = palette.slice(0, 4)
      .map((c) => `<i style="background:${cssColor(c, 1, 0)}"></i>`).join("");
    button.innerHTML =
      `<span class="key">${key}</span>` +
      `<span class="lookName">${look.name}</span>` +
      `<span class="dots">${chips}<em>${"·".repeat(look.energy || 2)}</em></span>`;
    button.onclick = async () => {
      await api("/api/look/activate", { id: look.id });
      await refreshStatus();
      syncControls();
      renderLooks();
    };
    grid.appendChild(button);
  });
}

function effectLabel(id) {
  const effect = (show.effects || []).find((e) => e.id === id);
  return effect ? effect.label : id || "—";
}

function fillSelect(select, options, value) {
  select.innerHTML = "";
  options.forEach((option) => {
    const element = document.createElement("option");
    element.value = option.value;
    element.textContent = option.label;
    select.appendChild(element);
  });
  select.value = value;
}

function renderLiveOptions() {
  const profile = mainProfile() || {};
  const effects = show.effects || [];
  fillSelect($("positionEffect"),
    effects.filter((e) => e.kind === "position").map((e) => ({ value: e.id, label: e.label })),
    currentLook().position_effect || "none");
  fillSelect($("intensityEffect"),
    [{ id: "none", label: "Aucun" }].concat(effects.filter((e) => e.kind === "intensity"))
      .map((e) => ({ value: e.id, label: e.label })),
    currentLook().intensity_effect || "none");
  fillSelect($("gobo"), (profile.gobos || ["ouvert"]).map((g) => ({ value: g, label: g })),
    currentLook().gobo || "ouvert");

  const swatches = $("colorSwatches");
  swatches.innerHTML = "";
  const colors = profile.colors && profile.colors.length ? profile.colors : (show.colors || []);
  colors.forEach((name) => {
    const swatch = document.createElement("button");
    swatch.className = "swatch";
    swatch.title = name;
    swatch.dataset.color = name;
    swatch.style.background = name === "arc-en-ciel"
      ? "linear-gradient(90deg,#f00,#ff0,#0f0,#0ff,#00f,#f0f)"
      : cssColor(name, 1, 0);
    swatch.onclick = () => {
      setLive({ color: name, color_mode: "static" });
      [...swatches.children].forEach((c) => c.classList.toggle("on", c === swatch));
    };
    swatches.appendChild(swatch);
  });
}

function syncControls() {
  const look = currentLook();
  if (!look || touching) return;
  $("stageBadge").textContent = look.name || "";
  $("positionEffect").value = look.position_effect || "none";
  $("intensityEffect").value = look.intensity_effect || "none";
  $("gobo").value = look.gobo || "ouvert";
  $("prism").checked = !!look.prism;
  const lengthIndex = LENGTHS.indexOf(look.length);
  setSlider("length", lengthIndex < 0 ? 3 : lengthIndex);
  setSlider("size", Math.round((look.size || 0) * 100));
  setSlider("spread", Math.round((look.spread || 0) * 100));
  setSlider("dimmer", Math.round((look.dimmer || 0) * 100));
  setSlider("pan", Math.round((look.pan || 0) * 100));
  setSlider("tilt", Math.round((look.tilt || 0) * 100));
  setSlider("speed", Math.round((look.speed || 0) * 100));
  [...$("colorSwatches").children].forEach((c) =>
    c.classList.toggle("on", c.dataset.color === look.color && look.color_mode === "static"));
  updateLabels();
}

function setSlider(id, value) {
  const element = $(id);
  if (element && document.activeElement !== element) element.value = value;
}

function updateLabels() {
  $("lengthVal").textContent = LENGTHS[+$("length").value] + " temps";
  $("sizeVal").textContent = $("size").value + "%";
  $("spreadVal").textContent = $("spread").value + "%";
  $("dimmerVal").textContent = $("dimmer").value + "%";
  $("panVal").textContent = $("pan").value + "%";
  $("tiltVal").textContent = $("tilt").value + "%";
  $("speedVal").textContent = $("speed").value + "%";
}

function renderDmx() {
  const view = $("dmxView");
  const data = (status && status.dmx) || [];
  if (view.children.length !== data.length) {
    view.innerHTML = data.map((_, i) => `<div class="cell"><b>${i + 1}</b><span>0</span></div>`).join("");
  }
  data.forEach((value, i) => {
    const cell = view.children[i];
    if (cell) cell.lastElementChild.textContent = value;
  });
}

function applyExpert() {
  document.querySelectorAll(".expertOnly").forEach((node) =>
    node.classList.toggle("hidden", !expert));
  $("expertToggle").checked = expert;
}

/* ------------------------------------------------------------- live edit */
let livePending = null;
function setLive(values) {
  livePending = Object.assign(livePending || {}, values);
  clearTimeout(setLive._timer);
  setLive._timer = setTimeout(async () => {
    const payload = livePending;
    livePending = null;
    try { await api("/api/live", payload); } catch (e) { alertBox(String(e)); }
  }, 30);
}

function bindFader(id, key, transform) {
  const element = $(id);
  const push = () => { updateLabels(); setLive({ [key]: transform(+element.value) }); };
  element.addEventListener("input", push);
  element.addEventListener("pointerdown", () => { touching = true; });
  element.addEventListener("pointerup", () => { touching = false; });
  element.addEventListener("pointercancel", () => { touching = false; });
}

/* ----------------------------------------------------------- looks page */
function renderLookEditor() {
  const list = $("lookEditor");
  list.innerHTML = "";
  (show.looks || []).forEach((look) => {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML =
      `<div class="field"><label>Nom</label><input class="l-name" type="text" value="${look.name}"></div>
       <div class="field"><label>Palette (couleurs séparées par des virgules)</label>
         <input class="l-colors" type="text" value="${(look.colors || []).join(', ')}"></div>
       <div class="field"><label>Mode couleur</label>
         <select class="l-mode">
           <option value="static">une seule couleur</option>
           <option value="chase">défilement</option>
           <option value="spread">une par lampe</option>
           <option value="random">au hasard</option>
         </select></div>
       <div class="field"><label>Énergie</label>
         <select class="l-energy">
           <option value="1">calme</option>
           <option value="2">normal</option>
           <option value="3">gros son</option>
         </select></div>
       <div class="row">
         <button class="mini accent l-save">enregistrer</button>
         <button class="mini l-dup">dupliquer</button>
         <button class="mini danger l-del">supprimer</button>
       </div>`;
    item.querySelector(".l-mode").value = look.color_mode || "static";
    item.querySelector(".l-energy").value = String(look.energy || 2);

    item.querySelector(".l-save").onclick = async () => {
      const updated = Object.assign({}, look, {
        name: item.querySelector(".l-name").value.trim() || look.name,
        colors: item.querySelector(".l-colors").value.split(",").map((s) => s.trim()).filter(Boolean),
        color_mode: item.querySelector(".l-mode").value,
        energy: +item.querySelector(".l-energy").value
      });
      await api("/api/look/save", { look: updated });
      await reload();
    };
    item.querySelector(".l-dup").onclick = async () => {
      await api("/api/look/save", {
        look: Object.assign({}, look, {
          id: "l" + Date.now().toString(36), name: look.name + " (copie)"
        })
      });
      await reload();
    };
    item.querySelector(".l-del").onclick = async () => {
      if (!confirm("Supprimer « " + look.name + " » ?")) return;
      await api("/api/look/delete", { id: look.id });
      await reload();
    };
    list.appendChild(item);
  });
}

/* ----------------------------------------------------------- setup page */
function renderPatch() {
  const list = $("patchList");
  list.innerHTML = "";
  (show.fixtures || []).forEach((fixture, index) => {
    const item = document.createElement("div");
    item.className = "item";
    item.innerHTML =
      `<div class="field"><label>Nom</label><input class="f-name" type="text" value="${fixture.name}"></div>
       <div class="field"><label>Modèle</label><select class="f-profile"></select></div>
       <div class="field"><label>Adresse DMX</label>
         <input class="f-address" type="number" min="1" max="512" value="${fixture.address}"></div>
       <div class="field"><label>Ordre</label>
         <input class="f-order" type="number" min="0" value="${fixture.order}"></div>
       <label class="check"><input class="f-ipan" type="checkbox" ${fixture.invert_pan ? "checked" : ""}> inverser gauche/droite</label>
       <label class="check"><input class="f-itilt" type="checkbox" ${fixture.invert_tilt ? "checked" : ""}> inverser haut/bas</label>
       <label class="check"><input class="f-on" type="checkbox" ${fixture.enabled ? "checked" : ""}> active</label>
       <div class="row">
         <button class="mini f-solo">tester seule</button>
         <button class="mini danger f-del">retirer</button>
       </div>`;
    fillSelect(item.querySelector(".f-profile"),
      (show.profiles || []).map((p) => ({ value: p.id, label: p.name })), fixture.profile_id);
    item.querySelector(".f-del").onclick = () => { show.fixtures.splice(index, 1); renderPatch(); };
    item.querySelector(".f-solo").onclick = async () => {
      const solo = status && status.solo === fixture.id ? null : fixture.id;
      await api("/api/master", { solo });
      await refreshStatus();
    };
    item.dataset.id = fixture.id;
    list.appendChild(item);
  });
  const conflicts = $("conflicts");
  const problems = show.conflicts || [];
  conflicts.textContent = problems.join(" · ");
  conflicts.classList.toggle("hidden", problems.length === 0);
}

function collectPatch() {
  return [...$("patchList").children].map((item, index) => ({
    id: item.dataset.id || "f" + (index + 1),
    name: item.querySelector(".f-name").value,
    profile_id: item.querySelector(".f-profile").value,
    address: +item.querySelector(".f-address").value,
    order: +item.querySelector(".f-order").value,
    invert_pan: item.querySelector(".f-ipan").checked,
    invert_tilt: item.querySelector(".f-itilt").checked,
    enabled: item.querySelector(".f-on").checked
  }));
}

function renderOutputFields() {
  const driver = $("driver").value;
  const network = driver === "artnet" || driver === "sacn";
  $("fieldHost").classList.toggle("hidden", !network);
  $("fieldUniverse").classList.toggle("hidden", !network);
  $("fieldPort").classList.toggle("hidden", driver !== "enttec" && driver !== "opendmx");
}

function describeTestChannel(address) {
  for (const fixture of show.fixtures || []) {
    const profile = profileOf(fixture);
    if (!profile) continue;
    const offset = address - fixture.address;
    if (offset >= 0 && offset < profile.footprint) {
      return `${fixture.name} · canal ${offset + 1} du profil : ${profile.channels[offset]}`;
    }
  }
  return "aucune lampe sur ce canal";
}

/* -------------------------------------------------------------- wizard */
const wizard = { count: 2, profile: "beam100_14ch", output: { driver: "dummy" } };

function openWizard() {
  const choices = $("wizCount");
  choices.innerHTML = "";
  [1, 2, 3, 4, 6, 8].forEach((n) => {
    const button = document.createElement("button");
    button.className = "choice";
    button.innerHTML = `${n}<small>lampe${n > 1 ? "s" : ""}</small>`;
    button.onclick = () => { wizard.count = n; wizStep(2); };
    choices.appendChild(button);
  });
  wizStep(1);
  $("wizard").classList.remove("hidden");
}

function wizStep(step) {
  [1, 2, 3, 4].forEach((n) => $("wizStep" + n).classList.toggle("hidden", n !== step));
  $("wizExtra").classList.add("hidden");
}

async function wizFinish() {
  const response = await api("/api/wizard", {
    count: wizard.count, profile_id: wizard.profile, output: wizard.output
  });
  $("wizAddresses").innerHTML = response.addresses
    .map((address, i) => `<div><b>Beam ${i + 1}</b><span>adresse ${address}</span></div>`).join("");
  $("wizOutput").textContent = response.output_error
    ? "⚠ " + response.output_error
    : "Interface : " + response.output;
  wizStep(4);
  await reload();
}

/* ------------------------------------------------------------- polling */
async function refreshStatus() {
  status = await api("/api/status");
  $("bpm").textContent = status.bpm.toFixed(1);
  $("outputName").textContent = status.output;
  $("blackout").classList.toggle("on", status.blackout);
  $("strobe").classList.toggle("on", status.strobe);
  $("masterVal").textContent = Math.round(status.master_dimmer * 100) + "%";
  setSlider("master", Math.round(status.master_dimmer * 100));
  const beat = Math.floor(status.bar_phase * 4) % 4;
  [...document.querySelectorAll(".beatDots i")].forEach((dot, i) =>
    dot.classList.toggle("on", i === beat));
  document.querySelectorAll("[data-auto]").forEach((button) =>
    button.classList.toggle("on", (button.dataset.auto || "") === (status.auto || "")));
  alertBox(status.output_error);
  if (expert && !$("page-setup").classList.contains("hidden")) renderDmx();
  if (refreshStatus.lastLook !== status.active_look_id) {
    refreshStatus.lastLook = status.active_look_id;
    renderLooks();
    syncControls();
  }
}

async function reload() {
  show = await api("/api/show");
  await refreshStatus();
  renderLooks();
  renderLiveOptions();
  syncControls();
  renderLookEditor();
  renderPatch();
  const output = show.config.output || {};
  $("driver").value = output.driver || "dummy";
  $("host").value = output.host || "";
  $("universe").value = output.universe ?? 0;
  $("serialPort").value = output.port || "";
  renderOutputFields();
  applyExpert();
}

/* --------------------------------------------------------------- events */
function bindEvents() {
  document.querySelectorAll(".tab[data-page]").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab[data-page]").forEach((t) =>
        t.classList.toggle("active", t === tab));
      ["live", "looks", "setup"].forEach((page) =>
        $("page-" + page).classList.toggle("hidden", page !== tab.dataset.page));
    };
  });

  $("blackout").onclick = async () => {
    await api("/api/master", { blackout: !status.blackout });
    await refreshStatus();
  };
  const strobe = (on) => api("/api/master", { strobe: on }).then(refreshStatus).catch(() => {});
  $("strobe").addEventListener("pointerdown", () => strobe(true));
  $("strobe").addEventListener("pointerup", () => strobe(false));
  $("strobe").addEventListener("pointerleave", () => strobe(false));

  $("master").addEventListener("input", (event) => {
    $("masterVal").textContent = event.target.value + "%";
    api("/api/master", { dimmer: +event.target.value / 100 }).catch(() => {});
  });

  $("tap").onclick = () => api("/api/tempo", { tap: true }).then(refreshStatus);
  $("resync").onclick = () => api("/api/tempo", { resync: true });
  document.querySelectorAll("[data-nudge]").forEach((button) => {
    button.onclick = () => api("/api/tempo", { nudge: +button.dataset.nudge }).then(refreshStatus);
  });

  document.querySelectorAll("[data-auto]").forEach((button) => {
    button.onclick = () => api("/api/auto", { mode: button.dataset.auto }).then(refreshStatus);
  });
  $("surprise").onclick = async () => {
    await api("/api/surprise", {});
    await refreshStatus();
    syncControls();
  };

  bindFader("length", "length", (v) => LENGTHS[v]);
  bindFader("size", "size", (v) => v / 100);
  bindFader("spread", "spread", (v) => v / 100);
  bindFader("dimmer", "dimmer", (v) => v / 100);
  bindFader("pan", "pan", (v) => v / 100);
  bindFader("tilt", "tilt", (v) => v / 100);
  bindFader("speed", "speed", (v) => v / 100);
  $("gobo").onchange = (e) => setLive({ gobo: e.target.value });
  $("positionEffect").onchange = (e) => setLive({ position_effect: e.target.value });
  $("intensityEffect").onchange = (e) => setLive({ intensity_effect: e.target.value });
  $("prism").onchange = (e) => setLive({ prism: e.target.checked });

  $("storeLive").onclick = async () => { await api("/api/live/store", {}); await reload(); };
  $("clearLive").onclick = async () => {
    await api("/api/live/clear", {});
    await refreshStatus();
    syncControls();
  };

  $("addLook").onclick = async () => {
    await api("/api/look/save", { look: { id: "l" + Date.now().toString(36), name: "Nouveau look" } });
    await reload();
  };

  $("addFixture").onclick = () => {
    const last = (show.fixtures || [])[show.fixtures.length - 1];
    const profile = mainProfile() || { id: "beam100_14ch", footprint: 14 };
    show.fixtures.push({
      id: "f" + Date.now().toString(36),
      name: "Beam " + (show.fixtures.length + 1),
      profile_id: last ? last.profile_id : profile.id,
      address: last ? last.address + (profileOf(last) || profile).footprint : 1,
      order: show.fixtures.length,
      invert_pan: false, invert_tilt: false, enabled: true
    });
    renderPatch();
  };
  $("autoAddress").onclick = () => {
    let next = 1;
    show.fixtures = collectPatch().map((fixture) => {
      const profile = (show.profiles || []).find((p) => p.id === fixture.profile_id);
      fixture.address = next;
      next += profile ? profile.footprint : 1;
      return fixture;
    });
    renderPatch();
  };
  $("savePatch").onclick = async () => {
    const response = await api("/api/patch", { fixtures: collectPatch() });
    show.fixtures = response.fixtures;
    show.conflicts = response.conflicts;
    renderPatch();
    renderLiveOptions();
  };

  $("driver").onchange = renderOutputFields;
  $("applyOutput").onclick = async () => {
    const driver = $("driver").value;
    const config = { driver };
    if (driver === "artnet" || driver === "sacn") {
      if ($("host").value.trim()) config.host = $("host").value.trim();
      config.universe = +$("universe").value;
    }
    if (driver === "enttec" || driver === "opendmx") config.port = $("serialPort").value.trim();
    try {
      const response = await api("/api/output", config);
      alertBox("");
      $("outputName").textContent = response.output;
    } catch (e) { alertBox(String(e)); }
  };

  $("expertToggle").onchange = (event) => {
    expert = event.target.checked;
    localStorage.setItem("beamctl.expert", expert ? "1" : "0");
    applyExpert();
  };

  const sendTest = () => {
    const address = +$("testChannel").value;
    $("testVal").textContent = $("testValue").value;
    $("testInfo").textContent = describeTestChannel(address);
    api("/api/test", { address, value: +$("testValue").value }).catch(() => {});
  };
  $("testValue").addEventListener("input", sendTest);
  $("testChannel").addEventListener("change", sendTest);
  $("testClear").onclick = () => api("/api/test", { clear: true }).then(() => {
    $("testInfo").textContent = "canaux relâchés";
  });

  // assistant
  $("openWizard").onclick = openWizard;
  $("wizClose").onclick = () => $("wizard").classList.add("hidden");
  $("wizDone").onclick = () => $("wizard").classList.add("hidden");
  document.querySelectorAll("[data-profile]").forEach((button) => {
    button.onclick = () => { wizard.profile = button.dataset.profile; wizStep(3); };
  });
  document.querySelectorAll("[data-driver]").forEach((button) => {
    button.onclick = () => {
      const driver = button.dataset.driver;
      wizard.output = { driver };
      if (driver === "dummy") return wizFinish();
      const network = driver === "artnet";
      $("wizExtraLabel").textContent = network
        ? "Adresse IP du boîtier (laisse vide pour diffuser à tout le réseau)"
        : "Port série du boîtier (python -m beamctl --list-serial pour le trouver)";
      $("wizExtraInput").value = network ? "" : "/dev/ttyUSB0";
      $("wizExtraInput").placeholder = network ? "192.168.1.50" : "/dev/ttyUSB0 ou COM3";
      $("wizExtra").classList.remove("hidden");
    };
  });
  $("wizExtraOk").onclick = () => {
    const value = $("wizExtraInput").value.trim();
    if (wizard.output.driver === "artnet") {
      if (value) wizard.output.host = value;
    } else {
      wizard.output.port = value;
    }
    wizFinish();
  };

  // aide
  $("helpBtn").onclick = () => $("help").classList.remove("hidden");
  $("helpClose").onclick = () => $("help").classList.add("hidden");
  document.querySelectorAll(".overlay").forEach((overlay) => {
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) overlay.classList.add("hidden");
    });
  });

  document.addEventListener("keydown", (event) => {
    if (event.repeat || /input|select|textarea/i.test(event.target.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === " ") { event.preventDefault(); $("blackout").click(); }
    else if (key === "t") $("tap").click();
    else if (key === "s") strobe(true);
    else if (key === "r") $("surprise").click();
    else if (key === "escape") document.querySelectorAll(".overlay").forEach((o) => o.classList.add("hidden"));
    else if (key === "a") {
      const next = status && status.auto ? "" : "normal";
      api("/api/auto", { mode: next }).then(refreshStatus);
    } else if (key === "arrowup" || key === "arrowdown") {
      event.preventDefault();
      const step = key === "arrowup" ? 5 : -5;
      const value = Math.max(0, Math.min(100, Math.round(status.master_dimmer * 100) + step));
      api("/api/master", { dimmer: value / 100 }).then(refreshStatus);
    } else if (/^[0-9]$/.test(key)) {
      const index = key === "0" ? 9 : +key - 1;
      const button = $("lookGrid").children[index];
      if (button) button.click();
    }
  });
  document.addEventListener("keyup", (event) => {
    if (event.key.toLowerCase() === "s") strobe(false);
  });
}

/* ----------------------------------------------------------------- boot */
(async function main() {
  bindEvents();
  requestAnimationFrame(animate);
  try {
    await reload();
    if (!show.config.wizard_done) openWizard();
  } catch (e) {
    alertBox("Connexion impossible : " + e);
  }
  setInterval(() => refreshStatus().catch(() => {}), 150);
})();
