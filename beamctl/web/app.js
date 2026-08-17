/* beamctl — interface live. Pas de framework : fetch + DOM. */
"use strict";

const TOKEN = new URLSearchParams(location.search).get("t");
const $ = (id) => document.getElementById(id);

const COLORS = {
  "blanc": "#fdfdf5", "rouge": "#ff2d2d", "vert": "#25e05a", "bleu": "#2b6bff",
  "jaune": "#ffd21e", "orange": "#ff7a18", "cyan": "#22e0ff", "rose": "#ff3fae",
  "violet": "#a03cff", "arc-en-ciel": "linear-gradient(90deg,#f00,#ff0,#0f0,#0ff,#00f,#f0f)",
  "ouvert": "#333a4a"
};
const LENGTHS = [0.5, 1, 2, 4, 8, 16, 32];

let show = null;      // patch, looks, profils, effets
let status = null;    // etat courant du moteur
let touching = false; // un fader est en cours de manipulation

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
function swatchStyle(name) {
  const color = COLORS[name] || "#666";
  return color.startsWith("linear") ? `background:${color}` : `background:${color}`;
}

/* ------------------------------------------------------------- rendering */
function renderLooks() {
  const grid = $("lookGrid");
  grid.innerHTML = "";
  (show.looks || []).forEach((look, index) => {
    const button = document.createElement("button");
    button.className = "look" + (status && status.active_look_id === look.id ? " active" : "");
    const key = index < 9 ? String(index + 1) : index === 9 ? "0" : "";
    const palette = look.color_mode === "static" ? [look.color] : (look.colors.length ? look.colors : [look.color]);
    button.innerHTML =
      `<span class="chip" style="${swatchStyle(palette[0])}"></span>` +
      `<span class="key">${key}</span>` +
      `<span>${look.name}</span>` +
      `<em>${effectLabel(look.position_effect)} · ${effectLabel(look.intensity_effect)}</em>`;
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
    effects.filter((e) => e.kind === "intensity").concat([{ id: "none", label: "Aucune" }])
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
    swatch.style.cssText = swatchStyle(name);
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
  $("positionEffect").value = look.position_effect || "none";
  $("intensityEffect").value = look.intensity_effect || "none";
  $("gobo").value = look.gobo || "ouvert";
  $("prism").checked = !!look.prism;
  setSlider("length", LENGTHS.indexOf(look.length) < 0 ? 3 : LENGTHS.indexOf(look.length));
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

function renderRig() {
  const rig = $("rig");
  const fixtures = (status && status.fixtures) || [];
  if (rig.children.length !== fixtures.length) {
    rig.innerHTML = fixtures.map((fixture) =>
      `<div class="head" data-id="${fixture.id}">
         <div>${fixture.name}</div>
         <div class="beam"><span class="dot"></span></div>
         <b>ch ${fixture.address}</b>
       </div>`).join("");
  }
  fixtures.forEach((fixture, index) => {
    const card = rig.children[index];
    if (!card) return;
    const dot = card.querySelector(".dot");
    const state = fixture.state || {};
    const color = COLORS[state.color] || "#fff";
    dot.style.left = ((state.pan || 0.5) * 100) + "%";
    dot.style.top = ((state.tilt || 0.5) * 100) + "%";
    dot.style.background = color.startsWith("linear") ? "#fff" : color;
    dot.style.color = color.startsWith("linear") ? "#fff" : color;
    dot.style.opacity = Math.max(0.06, state.dimmer || 0);
  });
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
      `<div class="field"><label>Nom</label><input type="text" value="${look.name}"></div>
       <div class="field"><label>Palette (couleurs séparées par des virgules)</label>
         <input type="text" value="${(look.colors || []).join(', ')}"></div>
       <div class="field"><label>Mode couleur</label>
         <select>
           <option value="static">fixe</option>
           <option value="chase">défilement</option>
           <option value="spread">une par lampe</option>
           <option value="random">aléatoire</option>
         </select></div>
       <div class="row">
         <button class="mini accent">enregistrer</button>
         <button class="mini">dupliquer</button>
         <button class="mini danger">supprimer</button>
       </div>`;
    const [nameInput, colorsInput] = item.querySelectorAll("input");
    const modeSelect = item.querySelector("select");
    modeSelect.value = look.color_mode || "static";
    const [saveButton, dupButton, deleteButton] = item.querySelectorAll("button");

    saveButton.onclick = async () => {
      const updated = Object.assign({}, look, {
        name: nameInput.value.trim() || look.name,
        colors: colorsInput.value.split(",").map((s) => s.trim()).filter(Boolean),
        color_mode: modeSelect.value
      });
      await api("/api/look/save", { look: updated });
      await reload();
    };
    dupButton.onclick = async () => {
      const copy = Object.assign({}, look, {
        id: "l" + Date.now().toString(36),
        name: look.name + " (copie)"
      });
      await api("/api/look/save", { look: copy });
      await reload();
    };
    deleteButton.onclick = async () => {
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
       <div class="field"><label>Profil</label><select class="f-profile"></select></div>
       <div class="field"><label>Adresse DMX</label>
         <input class="f-address" type="number" min="1" max="512" value="${fixture.address}"></div>
       <div class="field"><label>Ordre</label>
         <input class="f-order" type="number" min="0" value="${fixture.order}"></div>
       <label class="check"><input class="f-ipan" type="checkbox" ${fixture.invert_pan ? "checked" : ""}> inverser pan</label>
       <label class="check"><input class="f-itilt" type="checkbox" ${fixture.invert_tilt ? "checked" : ""}> inverser tilt</label>
       <label class="check"><input class="f-on" type="checkbox" ${fixture.enabled ? "checked" : ""}> active</label>
       <div class="row">
         <button class="mini f-solo">solo</button>
         <button class="mini danger f-del">retirer</button>
       </div>`;
    const select = item.querySelector(".f-profile");
    fillSelect(select, (show.profiles || []).map((p) => ({ value: p.id, label: p.name })), fixture.profile_id);
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
  $("fieldHost").classList.toggle("hidden", driver !== "artnet" && driver !== "sacn");
  $("fieldUniverse").classList.toggle("hidden", driver !== "artnet" && driver !== "sacn");
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
  return "aucune lampe patchée sur ce canal";
}

/* ------------------------------------------------------------- polling */
async function refreshStatus() {
  status = await api("/api/status");
  $("bpm").textContent = status.bpm.toFixed(1);
  $("outputName").textContent = status.output;
  $("blackout").classList.toggle("on", status.blackout);
  $("strobe").classList.toggle("on", status.strobe);
  $("freeze").classList.toggle("on", status.freeze);
  $("masterVal").textContent = Math.round(status.master_dimmer * 100) + "%";
  setSlider("master", Math.round(status.master_dimmer * 100));
  const beat = Math.floor(status.bar_phase * 4) % 4;
  [...document.querySelectorAll(".beatDots i")].forEach((dot, i) => dot.classList.toggle("on", i === beat));
  alertBox(status.output_error);
  renderRig();
  if (!$("page-setup").classList.contains("hidden")) renderDmx();
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
  $("driver").value = (show.config.output || {}).driver || "dummy";
  $("host").value = (show.config.output || {}).host || "";
  $("universe").value = (show.config.output || {}).universe ?? 0;
  $("serialPort").value = (show.config.output || {}).port || "";
  renderOutputFields();
}

/* --------------------------------------------------------------- events */
function bindEvents() {
  document.querySelectorAll(".tab").forEach((tab) => {
    tab.onclick = () => {
      document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      ["live", "looks", "setup"].forEach((page) =>
        $("page-" + page).classList.toggle("hidden", page !== tab.dataset.page));
    };
  });

  $("blackout").onclick = async () => {
    await api("/api/master", { blackout: !status.blackout });
    await refreshStatus();
  };
  $("freeze").onclick = async () => {
    await api("/api/master", { freeze: !status.freeze });
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
  $("clearLive").onclick = async () => { await api("/api/live/clear", {}); await refreshStatus(); syncControls(); };

  $("addLook").onclick = async () => {
    const id = "l" + Date.now().toString(36);
    await api("/api/look/save", { look: { id, name: "Nouveau look" } });
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

  document.addEventListener("keydown", (event) => {
    if (event.repeat || /input|select|textarea/i.test(event.target.tagName)) return;
    const key = event.key.toLowerCase();
    if (key === " ") { event.preventDefault(); $("blackout").click(); }
    else if (key === "t") $("tap").click();
    else if (key === "f") $("freeze").click();
    else if (key === "s") strobe(true);
    else if (/^[0-9]$/.test(key)) {
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
  try {
    await reload();
  } catch (e) {
    alertBox("Connexion impossible : " + e);
  }
  setInterval(() => refreshStatus().catch(() => {}), 200);
})();
