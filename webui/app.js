"use strict";

const NUM_KEYS = 16;

const ACTION_TYPES = [
  ["open_url", "Open URL"],
  ["launch_app", "Launch App"],
  ["exec", "Run Command"],
  ["key_sequence", "Type / Hotkey Sequence"],
  ["layer_switch", "Switch Layer"],
  ["macro", "Run Macro"],
];

const STEP_KINDS = [
  ["text", "Type text"],
  ["hotkey", "Press hotkey"],
  ["delay", "Wait (ms)"],
];

let config = null;
let savedSnapshot = "";
let apps = [];
let liveActiveLayer = null;
let editingLayerId = null;
let selectedKeyIndex = null;
let editingMacroId = null;

const el = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== undefined && v !== null) node.setAttribute(k, v);
  }
  for (const c of [].concat(children)) {
    if (c === null || c === undefined) continue;
    node.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return node;
};

// ---------------------------------------------------------------- toasts --

function toast(message, type = "success", ms = 3200) {
  const glyph = type === "success" ? "✓" : type === "error" ? "✕" : "ℹ";
  const node = el("div", { class: `toast ${type}` }, [
    el("span", { class: "glyph" }, glyph),
    el("span", {}, message),
  ]);
  document.getElementById("toasts").appendChild(node);
  setTimeout(() => {
    node.classList.add("leaving");
    setTimeout(() => node.remove(), 220);
  }, ms);
}

// ------------------------------------------------------------- data model --

function defaultAction(type) {
  switch (type) {
    case "open_url": return { type, url: "" };
    case "launch_app": return { type, desktop_id: "", name: "" };
    case "exec": return { type, command: "" };
    case "key_sequence": return { type, steps: [] };
    case "layer_switch": return { type, target: firstOtherLayerId(), mode: "toggle" };
    case "macro": return { type, id: Object.keys(config.macros)[0] || "" };
    default: return { type };
  }
}

function firstOtherLayerId() {
  const other = config.layers.find((l) => l.id !== editingLayerId);
  return (other || config.layers[0]).id;
}

function defaultStep(kind) {
  switch (kind) {
    case "text": return { kind, value: "" };
    case "hotkey": return { kind, keys: [] };
    case "delay": return { kind, ms: 100 };
    default: return { kind };
  }
}

function currentLayer() {
  return config.layers.find((l) => l.id === editingLayerId) || config.layers[0];
}

function isDirty() {
  return JSON.stringify(config) !== savedSnapshot;
}

function markSnapshot() {
  savedSnapshot = JSON.stringify(config);
}

function updateDirtyIndicator() {
  document.getElementById("save").classList.toggle("dirty", isDirty());
}

// ------------------------------------------------------------------- api --

async function api(path, options) {
  const res = await fetch(path, options);
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`${res.status}: ${detail}`);
  }
  return res.status === 204 ? null : res.json();
}

// ------------------------------------------------------------------ init --

async function init() {
  [config, apps] = await Promise.all([api("/api/config"), api("/api/apps")]);
  markSnapshot();
  editingLayerId = config.active_layer;
  document.getElementById("hold-ms").value = config.hold_ms;
  document.getElementById("rotation").value = String(config.rotation || 0);

  document.getElementById("add-layer").onclick = addLayer;
  document.getElementById("delete-layer").onclick = deleteLayer;
  document.getElementById("activate-layer").onclick = async () => {
    await api(`/api/layer/${encodeURIComponent(editingLayerId)}/activate`, { method: "POST" });
    toast(`Activated “${currentLayer().name}” on the device`);
  };
  document.getElementById("layer-name").oninput = (e) => {
    currentLayer().name = e.target.value;
    renderTabs();
    updateDirtyIndicator();
  };
  document.getElementById("hold-ms").oninput = (e) => {
    config.hold_ms = parseInt(e.target.value, 10) || 400;
    updateDirtyIndicator();
  };
  document.getElementById("rotation").onchange = (e) => {
    config.rotation = parseInt(e.target.value, 10);
    updateDirtyIndicator();
  };
  document.getElementById("save").onclick = save;
  document.getElementById("add-macro").onclick = addMacro;
  document.getElementById("macro-close").onclick = () => document.getElementById("macro-dialog").close();
  document.getElementById("macro-delete").onclick = deleteMacro;

  setupSettingsPopover();
  setupCommandPalette();
  setupKeyboardShortcuts();

  renderAll();
  connectEvents();
  refreshStatus();

  window.addEventListener("beforeunload", (e) => {
    if (isDirty()) { e.preventDefault(); e.returnValue = ""; }
  });
}

function renderAll() {
  renderTabs();
  renderGrid();
  renderPanel();
  renderMacroList();
  document.getElementById("layer-name").value = currentLayer().name;
  updateDirtyIndicator();
}

// ----------------------------------------------------------------- tabs --

function renderTabs() {
  const container = document.getElementById("layer-tabs");
  container.innerHTML = "";
  for (const layer of config.layers) {
    const dot = el("span", { class: "dot", style: `background:${layer.color}` });
    const tab = el(
      "div",
      {
        class: "tab" + (layer.id === editingLayerId ? " editing" : "") + (layer.id === liveActiveLayer ? " live" : ""),
        tabindex: "0",
        onclick: () => selectLayer(layer.id),
      },
      [dot, layer.name]
    );
    container.appendChild(tab);
  }
}

function selectLayer(id) {
  editingLayerId = id;
  selectedKeyIndex = null;
  renderAll();
}

// ----------------------------------------------------------------- grid --

function renderGrid() {
  const grid = document.getElementById("grid");
  grid.innerHTML = "";
  const layer = currentLayer();
  layer.keys.forEach((key, idx) => {
    const isEmpty = !key.tap.length && !key.hold.length;
    const badges = [];
    if (key.tap.length) badges.push(el("span", { class: "badge-chip" }, "tap"));
    if (key.hold.length) badges.push(el("span", { class: "badge-chip" }, "hold"));
    const node = el(
      "div",
      {
        class: "key" + (idx === selectedKeyIndex ? " selected" : "") + (isEmpty ? " empty" : ""),
        tabindex: "0",
        onclick: () => { selectedKeyIndex = idx; renderGrid(); renderPanel(); },
      },
      [
        el("span", { class: "idx-badge" }, String(idx)),
        el("div", { class: "swatch", style: `background:${key.color}` }),
        el("div", { class: "label" }, key.label || "—"),
        el("div", { class: "badges" }, badges),
      ]
    );
    grid.appendChild(node);
  });
}

// ---------------------------------------------------------------- panel --

function renderPanel() {
  const empty = document.getElementById("panel-empty");
  const content = document.getElementById("panel-content");
  if (selectedKeyIndex === null) {
    empty.hidden = false;
    content.hidden = true;
    return;
  }
  empty.hidden = true;
  content.hidden = false;
  content.innerHTML = "";

  const layer = currentLayer();
  const key = layer.keys[selectedKeyIndex];

  content.appendChild(
    el("div", { class: "panel-header" }, [
      el("div", { class: "key-chip" }, String(selectedKeyIndex)),
      el("h2", {}, key.label || `Key ${selectedKeyIndex}`),
      el("button", { class: "ghost icon", title: "Close", onclick: () => { selectedKeyIndex = null; renderGrid(); renderPanel(); } }, "✕"),
    ])
  );

  const labelField = el("div", { class: "field" }, [
    el("label", {}, "Label"),
    el("input", {
      type: "text", value: key.label,
      oninput: (e) => { key.label = e.target.value; updateDirtyIndicator(); },
      onchange: renderGrid,
    }),
  ]);
  const colorField = el("div", { class: "field", style: "width:60px" }, [
    el("label", {}, "LED"),
    el("input", {
      type: "color", value: key.color,
      oninput: (e) => { key.color = e.target.value; renderGrid(); updateDirtyIndicator(); },
    }),
  ]);
  content.appendChild(el("div", { class: "row", style: "align-items:flex-end" }, [labelField, colorField]));

  content.appendChild(renderActionSection("Tap", "Fires when the key is pressed and released quickly.", key.tap));
  content.appendChild(renderActionSection(
    "Hold",
    "Fires once held past the threshold. A single “Switch Layer → momentary” action here makes this key a temporary layer modifier.",
    key.hold
  ));
}

function renderActionSection(title, hint, list) {
  const testBtn = el("button", {
    class: "small ghost",
    onclick: async () => {
      try {
        await api("/api/test-action", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(list),
        });
        toast(`Fired “${title}” actions`);
      } catch (err) {
        toast(err.message, "error");
      }
    },
  }, "▶ Test");

  return el("section", { class: "block" }, [
    el("div", { class: "section-title" }, [title, list.length ? testBtn : null]),
    el("p", { class: "hint" }, hint),
    renderActionList(list, renderPanel),
  ]);
}

function renderActionList(list, rerender) {
  const container = el("div", { class: "action-list" });
  list.forEach((action, i) => container.appendChild(renderActionCard(list, action, i, rerender)));

  const select = el("select", {}, ACTION_TYPES.map(([v, l]) => el("option", { value: v }, l)));
  const addRow = el("div", { class: "add-row" }, [
    select,
    el("button", { class: "small", onclick: () => { list.push(defaultAction(select.value)); updateDirtyIndicator(); rerender(); } }, "+ Add"),
  ]);
  container.appendChild(addRow);
  return container;
}

let dragCtx = null;

function renderActionCard(list, action, index, rerender) {
  const body = el("div", { class: "field" });
  fillActionBody(body, action, rerender);

  const typeSelect = el(
    "select",
    { onchange: (e) => { list[index] = defaultAction(e.target.value); updateDirtyIndicator(); rerender(); } },
    ACTION_TYPES.map(([v, l]) => el("option", { value: v, selected: v === action.type ? "" : undefined }, l))
  );

  const card = el("div", { class: "action-card", draggable: "true" }, [
    el("div", { class: "head" }, [
      el("div", { class: "head-left" }, [
        el("span", { class: "drag-handle" }, "⠿"),
        typeSelect,
      ]),
      el("button", { class: "small danger ghost", onclick: () => { list.splice(index, 1); updateDirtyIndicator(); rerender(); } }, "Remove"),
    ]),
    body,
  ]);

  card.addEventListener("dragstart", (e) => {
    dragCtx = { list, index };
    card.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
  });
  card.addEventListener("dragend", () => { card.classList.remove("dragging"); dragCtx = null; });
  card.addEventListener("dragover", (e) => {
    if (!dragCtx || dragCtx.list !== list) return;
    e.preventDefault();
    card.classList.add("drag-over");
  });
  card.addEventListener("dragleave", () => card.classList.remove("drag-over"));
  card.addEventListener("drop", (e) => {
    e.preventDefault();
    card.classList.remove("drag-over");
    if (!dragCtx || dragCtx.list !== list || dragCtx.index === index) return;
    const [moved] = list.splice(dragCtx.index, 1);
    list.splice(index, 0, moved);
    updateDirtyIndicator();
    rerender();
  });

  return card;
}

function fillActionBody(body, action, rerender) {
  body.innerHTML = "";
  if (action.type === "open_url") {
    body.appendChild(el("label", {}, "URL"));
    body.appendChild(el("input", {
      type: "url", value: action.url, placeholder: "https://mail.proton.me",
      oninput: (e) => { action.url = e.target.value; updateDirtyIndicator(); },
    }));
  } else if (action.type === "launch_app") {
    body.appendChild(el("label", {}, "Application"));
    body.appendChild(renderAppCombobox(action));
  } else if (action.type === "exec") {
    body.appendChild(el("label", {}, "Shell command"));
    body.appendChild(el("input", {
      type: "text", value: action.command, placeholder: "notify-send hello",
      oninput: (e) => { action.command = e.target.value; updateDirtyIndicator(); },
    }));
  } else if (action.type === "key_sequence") {
    body.appendChild(renderStepList(action.steps, rerender));
  } else if (action.type === "layer_switch") {
    const targetSelect = el(
      "select",
      { onchange: (e) => { action.target = e.target.value; updateDirtyIndicator(); } },
      config.layers.map((l) => el("option", { value: l.id, selected: l.id === action.target ? "" : undefined }, l.name))
    );
    const modeSelect = el(
      "select",
      { onchange: (e) => { action.mode = e.target.value; updateDirtyIndicator(); } },
      [
        el("option", { value: "toggle", selected: action.mode === "toggle" ? "" : undefined }, "Toggle (press to switch, press again to return)"),
        el("option", { value: "momentary", selected: action.mode === "momentary" ? "" : undefined }, "Momentary (active only while held)"),
      ]
    );
    body.appendChild(el("div", { class: "field" }, [el("label", {}, "Target layer"), targetSelect]));
    body.appendChild(el("div", { class: "field" }, [el("label", {}, "Mode"), modeSelect]));
  } else if (action.type === "macro") {
    const ids = Object.keys(config.macros);
    if (!ids.length) {
      body.appendChild(el("p", { class: "empty-hint" }, "No macros defined yet — add one in the Macros section."));
    } else {
      body.appendChild(el(
        "select",
        { onchange: (e) => { action.id = e.target.value; updateDirtyIndicator(); } },
        ids.map((id) => el("option", { value: id, selected: id === action.id ? "" : undefined }, config.macros[id].name))
      ));
    }
  }
}

// ------------------------------------------------------- app combobox --

function renderAppCombobox(action) {
  const wrap = el("div", { class: "combobox" });
  const current = apps.find((a) => a.desktop_id === action.desktop_id);
  const input = el("input", {
    type: "text",
    placeholder: "Search installed apps…",
    value: current ? current.name : action.name || "",
  });
  const list = el("div", { class: "combobox-list" });
  list.hidden = true;
  let activeIndex = -1;
  let matches = [];

  function renderList(filterText) {
    const q = filterText.trim().toLowerCase();
    matches = q ? apps.filter((a) => a.name.toLowerCase().includes(q)) : apps.slice(0, 30);
    list.innerHTML = "";
    if (!matches.length) {
      list.appendChild(el("div", { class: "combobox-item" }, "No matching apps"));
    } else {
      matches.slice(0, 30).forEach((a, i) => {
        const item = el(
          "div",
          {
            class: "combobox-item" + (i === activeIndex ? " active" : ""),
            onmousedown: (e) => { e.preventDefault(); choose(a); },
          },
          [el("span", {}, a.name), el("span", { class: "muted" }, a.desktop_id)]
        );
        list.appendChild(item);
      });
    }
    list.hidden = false;
  }

  function choose(a) {
    action.desktop_id = a.desktop_id;
    action.name = a.name;
    input.value = a.name;
    list.hidden = true;
    updateDirtyIndicator();
  }

  input.addEventListener("input", () => { activeIndex = -1; renderList(input.value); });
  input.addEventListener("focus", () => renderList(input.value));
  input.addEventListener("blur", () => setTimeout(() => { list.hidden = true; }, 120));
  input.addEventListener("keydown", (e) => {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); activeIndex = Math.min(activeIndex + 1, matches.length - 1); renderList(input.value); }
    else if (e.key === "ArrowUp") { e.preventDefault(); activeIndex = Math.max(activeIndex - 1, 0); renderList(input.value); }
    else if (e.key === "Enter") { e.preventDefault(); if (matches[activeIndex]) choose(matches[activeIndex]); }
    else if (e.key === "Escape") { list.hidden = true; }
  });

  wrap.appendChild(input);
  wrap.appendChild(list);
  return wrap;
}

// ------------------------------------------------------------- sequences --

function renderStepList(steps, rerender) {
  const container = el("div", { class: "step-list" });
  steps.forEach((step, i) => container.appendChild(renderStepCard(steps, step, i, rerender)));
  const select = el("select", {}, STEP_KINDS.map(([v, l]) => el("option", { value: v }, l)));
  const addRow = el("div", { class: "add-row" }, [
    select,
    el("button", { class: "small", onclick: () => { steps.push(defaultStep(select.value)); updateDirtyIndicator(); rerender(); } }, "+ Step"),
  ]);
  container.appendChild(addRow);
  return container;
}

function renderStepCard(steps, step, index, rerender) {
  let field;
  if (step.kind === "text") {
    field = el("input", {
      type: "text", value: step.value, placeholder: "text to type",
      oninput: (e) => { step.value = e.target.value; updateDirtyIndicator(); },
    });
  } else if (step.kind === "hotkey") {
    field = el("input", {
      type: "text", value: (step.keys || []).join("+"), placeholder: "ctrl+shift+t",
      oninput: (e) => { step.keys = e.target.value.split("+").map((s) => s.trim()).filter(Boolean); updateDirtyIndicator(); },
    });
  } else {
    field = el("input", {
      type: "number", value: step.ms,
      oninput: (e) => { step.ms = parseInt(e.target.value, 10) || 0; updateDirtyIndicator(); },
    });
  }
  const kindLabel = STEP_KINDS.find(([v]) => v === step.kind)[1];
  return el("div", { class: "step-card" }, [
    el("span", { class: "hint", style: "white-space:nowrap" }, kindLabel + ":"),
    field,
    el("button", { class: "small danger ghost", onclick: () => { steps.splice(index, 1); updateDirtyIndicator(); rerender(); } }, "×"),
  ]);
}

// ---------------------------------------------------------------- macros --

function renderMacroList() {
  const container = document.getElementById("macro-list");
  container.innerHTML = "";
  const ids = Object.keys(config.macros);
  if (!ids.length) {
    container.appendChild(el("p", { class: "empty-hint" }, "No macros yet."));
    return;
  }
  for (const id of ids) {
    container.appendChild(el("div", { class: "row", style: "margin-bottom:6px" }, [
      el("button", { class: "small", onclick: () => openMacroDialog(id) }, config.macros[id].name),
    ]));
  }
}

function addLayer() {
  let n = config.layers.length + 1;
  let id = `layer-${n}`;
  while (config.layers.some((l) => l.id === id)) { n += 1; id = `layer-${n}`; }
  config.layers.push({
    id, name: `Layer ${n}`, color: "#4a5568",
    keys: Array.from({ length: NUM_KEYS }, () => ({ label: "", color: "#1a1a1a", tap: [], hold: [] })),
  });
  editingLayerId = id;
  updateDirtyIndicator();
  renderAll();
}

function deleteLayer() {
  if (config.layers.length <= 1) { toast("You need at least one layer.", "error"); return; }
  if (!confirm(`Delete layer "${currentLayer().name}"?`)) return;
  config.layers = config.layers.filter((l) => l.id !== editingLayerId);
  if (config.active_layer === editingLayerId) config.active_layer = config.layers[0].id;
  editingLayerId = config.layers[0].id;
  selectedKeyIndex = null;
  updateDirtyIndicator();
  renderAll();
}

function addMacro() {
  let n = Object.keys(config.macros).length + 1;
  let id = `macro-${n}`;
  while (config.macros[id]) { n += 1; id = `macro-${n}`; }
  config.macros[id] = { id, name: `Macro ${n}`, steps: [] };
  updateDirtyIndicator();
  renderMacroList();
  openMacroDialog(id);
}

function openMacroDialog(id) {
  editingMacroId = id;
  const macro = config.macros[id];
  document.getElementById("macro-name").value = macro.name;
  document.getElementById("macro-name").oninput = (e) => {
    macro.name = e.target.value;
    updateDirtyIndicator();
    renderMacroList();
  };
  const actionsContainer = document.getElementById("macro-actions");
  actionsContainer.innerHTML = "";
  actionsContainer.appendChild(renderActionList(macro.steps, () => openMacroDialog(id)));
  document.getElementById("macro-dialog").showModal();
}

function deleteMacro() {
  if (!editingMacroId) return;
  delete config.macros[editingMacroId];
  document.getElementById("macro-dialog").close();
  updateDirtyIndicator();
  renderMacroList();
  renderPanel();
}

// ----------------------------------------------------------------- save --

async function save() {
  const status = document.getElementById("save-status");
  status.textContent = "Saving…";
  try {
    config = await api("/api/config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
    markSnapshot();
    updateDirtyIndicator();
    status.textContent = "Saved";
    toast("Saved to device");
    setTimeout(() => { status.textContent = ""; }, 1800);
  } catch (err) {
    status.textContent = "";
    toast(err.message, "error");
  }
}

// -------------------------------------------------------------- status --

async function refreshStatus() {
  const status = await api("/api/status");
  liveActiveLayer = status.active_layer;
  renderTabs();
}

function setStatusPill(state) {
  const pill = document.getElementById("status-pill");
  const label = document.getElementById("status-label");
  pill.className = "status-pill " + state;
  label.textContent = state === "connected" ? "Live" : state === "error" ? "Reconnecting…" : "Connecting…";
}

function connectEvents() {
  const source = new EventSource("/api/events");
  source.onopen = () => setStatusPill("connected");
  source.onmessage = (e) => {
    setStatusPill("connected");
    const data = JSON.parse(e.data);
    if (data.active_layer) {
      liveActiveLayer = data.active_layer;
      renderTabs();
    }
  };
  source.onerror = () => {
    setStatusPill("error");
    source.close();
    setTimeout(connectEvents, 3000);
  };
}

// -------------------------------------------------------------- settings --

function setupSettingsPopover() {
  const btn = document.getElementById("settings-btn");
  const pop = document.getElementById("settings-popover");
  btn.onclick = (e) => {
    e.stopPropagation();
    pop.hidden = !pop.hidden;
  };
  document.addEventListener("click", (e) => {
    if (!pop.hidden && !pop.contains(e.target) && e.target !== btn) pop.hidden = true;
  });
}

// ---------------------------------------------------------- command palette --

function buildCommandIndex() {
  const items = [];
  items.push({ group: "Actions", glyph: "💾", label: "Save to device", run: save });
  items.push({ group: "Actions", glyph: "➕", label: "Add layer", run: addLayer });
  items.push({ group: "Actions", glyph: "➕", label: "Add macro", run: addMacro });
  items.push({ group: "Actions", glyph: "⚙", label: "Open settings", run: () => { document.getElementById("settings-popover").hidden = false; } });
  for (const layer of config.layers) {
    items.push({ group: "Layers", glyph: "▤", label: `Go to layer: ${layer.name}`, run: () => selectLayer(layer.id) });
  }
  const layer = currentLayer();
  layer.keys.forEach((key, idx) => {
    if (key.label || key.tap.length || key.hold.length) {
      items.push({
        group: `Keys — ${layer.name}`,
        glyph: "⌨",
        label: `Edit key ${idx}: ${key.label || "(unlabeled)"}`,
        run: () => { selectedKeyIndex = idx; renderGrid(); renderPanel(); },
      });
    }
  });
  for (const id of Object.keys(config.macros)) {
    items.push({ group: "Macros", glyph: "✳", label: `Edit macro: ${config.macros[id].name}`, run: () => openMacroDialog(id) });
  }
  return items;
}

function setupCommandPalette() {
  const backdrop = document.getElementById("cmdk-backdrop");
  const input = document.getElementById("cmdk-input");
  const list = document.getElementById("cmdk-list");
  let items = [];
  let filtered = [];
  let activeIndex = 0;

  function open() {
    items = buildCommandIndex();
    input.value = "";
    activeIndex = 0;
    renderList("");
    backdrop.hidden = false;
    setTimeout(() => input.focus(), 0);
  }
  function close() { backdrop.hidden = true; }

  function renderList(query) {
    const q = query.trim().toLowerCase();
    filtered = q ? items.filter((it) => it.label.toLowerCase().includes(q)) : items;
    list.innerHTML = "";
    if (!filtered.length) {
      list.appendChild(el("div", { class: "cmdk-empty" }, "No matches"));
      return;
    }
    let lastGroup = null;
    filtered.forEach((it, i) => {
      if (it.group !== lastGroup) {
        list.appendChild(el("div", { class: "cmdk-group-label" }, it.group));
        lastGroup = it.group;
      }
      list.appendChild(el(
        "div",
        {
          class: "cmdk-item" + (i === activeIndex ? " active" : ""),
          onmousedown: (e) => { e.preventDefault(); it.run(); close(); },
        },
        [el("span", { class: "glyph" }, it.glyph), el("span", {}, it.label)]
      ));
    });
  }

  document.getElementById("cmdk-trigger").onclick = open;
  backdrop.addEventListener("mousedown", (e) => { if (e.target === backdrop) close(); });
  input.addEventListener("input", () => { activeIndex = 0; renderList(input.value); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); activeIndex = Math.min(activeIndex + 1, filtered.length - 1); renderList(input.value); }
    else if (e.key === "ArrowUp") { e.preventDefault(); activeIndex = Math.max(activeIndex - 1, 0); renderList(input.value); }
    else if (e.key === "Enter") { e.preventDefault(); if (filtered[activeIndex]) { filtered[activeIndex].run(); close(); } }
    else if (e.key === "Escape") { close(); }
  });

  window.__openCommandPalette = open;
}

function setupKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    const mod = e.metaKey || e.ctrlKey;
    if (mod && e.key.toLowerCase() === "k") { e.preventDefault(); window.__openCommandPalette(); }
    else if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); }
    else if (e.key === "Escape") {
      const macroDialog = document.getElementById("macro-dialog");
      if (macroDialog.open) macroDialog.close();
      document.getElementById("settings-popover").hidden = true;
    }
  });
}

init().catch((err) => {
  document.body.innerHTML = `<p style="padding:20px;color:#f56565">Failed to load: ${err.message}</p>`;
});
