/* Electrical Laboratory (Stage 8) — circuit designer + calculations.
   Plain JS, no build step. Talks to the Stage 8 backend:
   POST /api/v1/circuits/simulate (MNA solver) and the Stage 6
   job API (POST /api/v1/simulations) for analytical calculations.
   The designer itself (drawing, wiring, local validation) works
   without a backend; running a simulation needs a signed-in
   project, like the rest of the lab. */
const API = (window.AIELAB_API_BASE || "http://127.0.0.1:8001");
const token = () => localStorage.getItem("aielab.token");
const $ = (id) => document.getElementById(id);
async function api(path, opts = {}) {
  const r = await (window.aielabFetchWithWake || fetch)(API + path, {
    ...opts,
    headers: { "Content-Type": "application/json", ...(token() ? { Authorization: "Bearer " + token() } : {}), ...(opts.headers || {}) },
  }, (attempt) => { const el = $("circuit-status"); if (el) el.textContent = "Waking the server… (retry " + attempt + ")"; });
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(body.error || ("HTTP " + r.status));
  return body;
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ---------- engineering values ---------- */
const SUFFIX = { p: 1e-12, n: 1e-9, u: 1e-6, µ: 1e-6, m: 1e-3, k: 1e3, K: 1e3, M: 1e6, G: 1e9 };
function parseEng(s) {
  if (typeof s === "number") return s;
  const m = String(s).trim().match(/^([-+0-9.eE]+)\s*([pnumkKMGµ]?)$/);
  if (!m) return NaN;
  return parseFloat(m[1]) * (SUFFIX[m[2]] || 1);
}
function fmtEng(v, unit = "") {
  if (v === null || v === undefined || isNaN(v)) return "—";
  const a = Math.abs(v);
  const table = [[1e9, "G"], [1e6, "M"], [1e3, "k"], [1, ""], [1e-3, "m"], [1e-6, "µ"], [1e-9, "n"], [1e-12, "p"]];
  for (const [f, s] of table) if (a >= f) return (v / f).toPrecision(4).replace(/\.?0+$/, "") + " " + s + unit;
  return v.toExponential(2) + " " + unit;
}

/* ---------- tabs ---------- */
document.querySelectorAll(".tab").forEach((b) => {
  b.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    for (const t of ["designer", "calcs", "motors", "jobs"]) {
      $("tab-" + t).hidden = t !== b.dataset.tab;
    }
    if (b.dataset.tab === "jobs") refreshJobs();
  });
});

/* ---------- projects ---------- */
let projectId = null;
async function loadProjects() {
  try {
    const data = await api("/api/v1/projects");
    for (const p of data.projects || []) {
      const o = document.createElement("option");
      o.value = p.id; o.textContent = (p.name || p.id) + " (" + (p.lab || "general") + ")";
      $("project-select").appendChild(o);
    }
    // Re-open the project this browser used last, when signed in.
    const last = localStorage.getItem("aielab.last_project");
    if (last && [...$("project-select").options].some((o) => o.value === last)) { $("project-select").value = last; projectId = last; }
  } catch { /* guest / backend down: designer still works */ }
  const q = new URLSearchParams(location.search);
  if (q.get("project")) { $("project-select").value = q.get("project"); projectId = q.get("project"); }
}
$("project-select").addEventListener("change", (e) => { projectId = e.target.value || null; if (e.target.value) localStorage.setItem("aielab.last_project", e.target.value); else localStorage.removeItem("aielab.last_project"); });
loadProjects();

/* ---------- component definitions ---------- */
const COMP_DEFS = {
  resistor: { label: "Resistor", terms: 2, defaults: { value: 1000, rating_W: 0.25 }, unit: "Ω", fields: [["value", "Resistance (Ω, e.g. 1k)"], ["rating_W", "Power rating (W)"]] },
  capacitor: { label: "Capacitor", terms: 2, defaults: { value: 1e-6 }, unit: "F", fields: [["value", "Capacitance (F, e.g. 1u)"]] },
  inductor: { label: "Inductor", terms: 2, defaults: { value: 0.01 }, unit: "H", fields: [["value", "Inductance (H, e.g. 10m)"]] },
  voltage_source: { label: "Voltage source", terms: 2, defaults: { value: 5, waveform: "dc", amplitude: 5, frequency: 50 }, unit: "V", fields: [["value", "DC value (V)"], ["waveform", "Waveform (dc/step/sine/pulse)"], ["amplitude", "Amplitude (V)"], ["frequency", "Frequency (Hz)"], ["offset", "Offset (V)"]] },
  current_source: { label: "Current source", terms: 2, defaults: { value: 0.01 }, unit: "A", fields: [["value", "Current (A)"]] },
  diode: { label: "Diode", terms: 2, defaults: { is: 1e-14, n: 1 }, fields: [["is", "Saturation current (A)"], ["n", "Ideality factor"]] },
  led: { label: "LED", terms: 2, defaults: { is: 1e-18, n: 1.8 }, fields: [["is", "Saturation current (A)"], ["n", "Ideality factor"]] },
  npn: { label: "NPN transistor", terms: 3, defaults: { is: 1e-15, beta: 100 }, fields: [["is", "Saturation current (A)"], ["beta", "Current gain β"]] },
  nmos: { label: "NMOS", terms: 3, defaults: { kp: 0.001, vth: 1, lambda: 0 }, fields: [["kp", "kp (A/V²)"], ["vth", "Threshold Vth (V)"], ["lambda", "λ (1/V)"]] },
  opamp: { label: "Op-amp", terms: 5, defaults: { gain: 100000 }, fields: [["gain", "Open-loop gain"]] },
  switch: { label: "Switch", terms: 2, defaults: { closed: true }, fields: [["closed", "Closed? (true/false)"]] },
  ground: { label: "Ground", terms: 1, defaults: {}, fields: [] },
};
const BOX = { 1: [40, 40], 2: [72, 48], 3: [72, 72], 5: [96, 72] };

/* ---------- circuit state ---------- */
let circuit = { name: "Untitled circuit", components: [], connections: [] };
let counters = {};
let selectedId = null;
let mode = "select"; // select | wire | place:<type>
let pendingWire = null;
let drag = null;

function nextId(type) {
  const prefix = { resistor: "R", capacitor: "C", inductor: "L", voltage_source: "V", current_source: "I", diode: "D", led: "LED", npn: "Q", nmos: "M", opamp: "U", switch: "S", ground: "G" }[type];
  counters[prefix] = (counters[prefix] || 0) + 1;
  return prefix + counters[prefix];
}
function addComponent(type, x, y) {
  const id = nextId(type);
  circuit.components.push({ id, type, x: Math.round(x / 10) * 10, y: Math.round(y / 10) * 10, params: { ...COMP_DEFS[type].defaults }, nodes: Array.from({ length: COMP_DEFS[type].terms }, (_, i) => id + ":" + i) });
  selectedId = id;
  renderAll();
}
function termPos(c, term) {
  const [w, h] = BOX[COMP_DEFS[c.type].terms];
  if (COMP_DEFS[c.type].terms === 1) return { x: c.x + w / 2, y: c.y };
  if (COMP_DEFS[c.type].terms === 2) return term === 0 ? { x: c.x, y: c.y + h / 2 } : { x: c.x + w, y: c.y + h / 2 };
  if (COMP_DEFS[c.type].terms === 3) return [{ x: c.x + w / 2, y: c.y }, { x: c.x, y: c.y + h / 2 }, { x: c.x + w / 2, y: c.y + h }][term];
  return [{ x: c.x + w, y: c.y + h / 2 }, { x: c.x, y: c.y + h / 4 }, { x: c.x, y: c.y + 3 * h / 4 }, { x: c.x + w / 2, y: c.y }, { x: c.x + w / 2, y: c.y + h }][term];
}
function findTerminal(px, py) {
  for (const c of circuit.components) {
    for (let t = 0; t < COMP_DEFS[c.type].terms; t++) {
      const p = termPos(c, t);
      if (Math.hypot(p.x - px, p.y - py) < 10) return { comp: c.id, term: t, x: p.x, y: p.y };
    }
  }
  return null;
}
function findComponent(px, py) {
  for (let i = circuit.components.length - 1; i >= 0; i--) {
    const c = circuit.components[i];
    const [w, h] = BOX[COMP_DEFS[c.type].terms];
    if (px >= c.x - 4 && px <= c.x + w + 4 && py >= c.y - 4 && py <= c.y + h + 4) return c;
  }
  return null;
}

/* ---------- net resolution (mirrors backend/circuit.py exactly) ---------- */
function resolveNets(c) {
  const parent = new Map();
  const find = (k) => { if (!parent.has(k)) parent.set(k, k); let r = k; while (parent.get(r) !== r) r = parent.get(r); while (parent.get(k) !== r) { const n = parent.get(k); parent.set(k, n); k = n; } return r; };
  const union = (a, b) => { const ra = find(a), rb = find(b); if (ra !== rb) parent.set(ra, rb); };
  for (const comp of c.components) for (let i = 0; i < comp.nodes.length; i++) find(comp.id + ":" + i);
  for (const w of c.connections || []) { union(w.a.comp + ":" + w.a.term, w.b.comp + ":" + w.b.term); }
  for (const comp of c.components) if (comp.type === "ground") union(comp.id + ":0", "__ground__:0");
  const groups = new Map(); // root -> name
  const order = [];
  for (const comp of c.components) for (let i = 0; i < comp.nodes.length; i++) {
    const r = find(comp.id + ":" + i);
    if (!groups.has(r)) { groups.set(r, r === find("__ground__:0") ? "0" : null); order.push(r); }
  }
  let n = 0;
  for (const r of order) if (groups.get(r) === null) groups.set(r, "n" + (++n));
  const netOf = {};
  for (const comp of c.components) for (let i = 0; i < comp.nodes.length; i++) netOf[comp.id + ":" + i] = groups.get(find(comp.id + ":" + i));
  const members = {};
  for (const k in netOf) (members[netOf[k]] = members[netOf[k]] || []).push(k);
  return { netOf, members };
}

/* ---------- drawing ---------- */
const cv = $("schematic"), ctx = cv.getContext("2d");
function draw() {
  ctx.clearRect(0, 0, cv.width, cv.height);
  ctx.strokeStyle = "#222"; ctx.lineWidth = 1;
  for (let x = 0; x <= cv.width; x += 20) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, cv.height); ctx.stroke(); }
  for (let y = 0; y <= cv.height; y += 20) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(cv.width, y); ctx.stroke(); }
  const fg = getComputedStyle(document.body).getPropertyValue("--hatch-widget-text") || "#111";
  ctx.strokeStyle = fg; ctx.fillStyle = fg; ctx.lineWidth = 1.6;
  // wires (elbow routed)
  for (const w of circuit.connections) {
    const a = termOf(w.a), b = termOf(w.b);
    if (!a || !b) continue;
    const mx = (a.x + b.x) / 2;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(mx, a.y); ctx.lineTo(mx, b.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  }
  if (pendingWire) { ctx.beginPath(); ctx.arc(pendingWire.x, pendingWire.y, 6, 0, 7); ctx.stroke(); }
  for (const c of circuit.components) drawComponent(c, fg);
}
function termOf(ref) {
  const c = circuit.components.find((x) => x.id === ref.comp);
  return c ? termPos(c, ref.term) : null;
}
function drawComponent(c, fg) {
  const [w, h] = BOX[COMP_DEFS[c.type].terms];
  const cx = c.x, cy = c.y, midY = cy + h / 2, midX = cx + w / 2;
  ctx.save();
  if (c.id === selectedId) { ctx.fillStyle = "rgba(80,140,255,0.15)"; ctx.fillRect(cx - 6, cy - 6, w + 12, h + 12); }
  ctx.strokeStyle = fg; ctx.fillStyle = fg; ctx.lineWidth = 1.6;
  const line = (x1, y1, x2, y2) => { ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke(); };
  const circle = (x, y, r) => { ctx.beginPath(); ctx.arc(x, y, r, 0, 7); ctx.stroke(); };
  switch (c.type) {
    case "resistor": {
      line(cx, midY, cx + 12, midY);
      ctx.beginPath(); ctx.moveTo(cx + 12, midY);
      for (let i = 0; i < 6; i++) ctx.lineTo(cx + 12 + (i + 1) * 8, midY + (i % 2 ? -8 : 8));
      ctx.lineTo(cx + 60, midY); ctx.stroke();
      line(cx + 60, midY, cx + w, midY);
      break;
    }
    case "capacitor": line(cx, midY, cx + 32, midY); line(cx + 32, midY - 14, cx + 32, midY + 14); line(cx + 40, midY - 14, cx + 40, midY + 14); line(cx + 40, midY, cx + w, midY); break;
    case "inductor": {
      line(cx, midY, cx + 12, midY);
      for (let i = 0; i < 4; i++) { ctx.beginPath(); ctx.arc(cx + 18 + i * 12, midY, 6, Math.PI, 0); ctx.stroke(); }
      line(cx + 60, midY, cx + w, midY);
      break;
    }
    case "voltage_source": circle(midX, midY, 14); line(cx, midY, midX - 14, midY); line(midX + 14, midY, cx + w, midY); ctx.font = "12px sans-serif"; ctx.fillText("+", midX - 3, midY - 3); ctx.fillText("−", midX - 3, midY + 11); break;
    case "current_source": circle(midX, midY, 14); line(cx, midY, midX - 14, midY); line(midX + 14, midY, cx + w, midY); ctx.beginPath(); ctx.moveTo(midX, midY - 8); ctx.lineTo(midX, midY + 8); ctx.moveTo(midX - 4, midY + 4); ctx.lineTo(midX, midY + 8); ctx.lineTo(midX + 4, midY + 4); ctx.stroke(); break;
    case "diode": case "led": {
      line(cx, midY, cx + 24, midY);
      ctx.beginPath(); ctx.moveTo(cx + 24, midY - 10); ctx.lineTo(cx + 24, midY + 10); ctx.lineTo(cx + 44, midY); ctx.closePath(); ctx.stroke();
      line(cx + 44, midY - 10, cx + 44, midY + 10); line(cx + 44, midY, cx + w, midY);
      if (c.type === "led") { line(cx + 30, midY - 16, cx + 38, midY - 24); line(cx + 40, midY - 16, cx + 48, midY - 24); }
      break;
    }
    case "npn": case "nmos": {
      const top = termPos(c, 0), left = termPos(c, 1), bot = termPos(c, 2);
      line(top.x, top.y, top.x, cy + 24); line(left.x, left.y, cx + 26, left.y); line(bot.x, bot.y, bot.x, cy + h - 24);
      line(cx + 26, cy + 24, cx + 26, cy + h - 24);
      ctx.beginPath(); ctx.moveTo(cx + 26, cy + 30); ctx.lineTo(cx + 44, cy + 30); ctx.moveTo(cx + 26, cy + h - 30); ctx.lineTo(cx + 44, cy + h - 30); ctx.stroke();
      line(cx + 44, cy + 30, cx + 44, cy + h - 30);
      if (c.type === "npn") { ctx.beginPath(); ctx.moveTo(cx + 44, cy + h - 38); ctx.lineTo(cx + 38, cy + h - 30); ctx.moveTo(cx + 44, cy + h - 38); ctx.lineTo(cx + 50, cy + h - 30); ctx.stroke(); }
      break;
    }
    case "opamp": {
      ctx.beginPath(); ctx.moveTo(cx + 8, cy + 6); ctx.lineTo(cx + 8, cy + h - 6); ctx.lineTo(cx + w - 16, midY); ctx.closePath(); ctx.stroke();
      ctx.font = "13px sans-serif"; ctx.fillText("+", cx + 16, cy + 26); ctx.fillText("−", cx + 16, cy + 56);
      line(cx, cy + h / 4, cx + 8, cy + h / 4); line(cx, cy + 3 * h / 4, cx + 8, cy + 3 * h / 4);
      line(cx + w - 16, midY, cx + w, midY); line(midX, cy, midX, cy + 6); line(midX, cy + h - 6, midX, cy + h);
      break;
    }
    case "switch": {
      line(cx, midY, cx + 20, midY);
      const closed = c.params.closed !== false;
      if (closed) line(cx + 20, midY, cx + 52, midY); else { ctx.beginPath(); ctx.moveTo(cx + 20, midY); ctx.lineTo(cx + 48, midY - 14); ctx.stroke(); }
      line(cx + 52, midY, cx + w, midY);
      break;
    }
    case "ground": line(cx + w / 2, cy, cx + w / 2, cy + 14); line(cx + 4, cy + 14, cx + w - 4, cy + 14); line(cx + 10, cy + 20, cx + w - 10, cy + 20); line(cx + 16, cy + 26, cx + w - 16, cy + 26); break;
  }
  // terminals
  for (let t = 0; t < COMP_DEFS[c.type].terms; t++) {
    const p = termPos(c, t);
    ctx.beginPath(); ctx.arc(p.x, p.y, 3.5, 0, 7); ctx.fill();
  }
  ctx.font = "11px sans-serif";
  ctx.fillText(c.id, cx, cy + h + 12);
  const v = c.params.value;
  if (v !== undefined) ctx.fillText(fmtEng(typeof v === "number" ? v : parseEng(v), COMP_DEFS[c.type].unit || ""), cx, cy + h + 24);
  ctx.restore();
}

/* ---------- palette & canvas interaction ---------- */
const palette = $("palette");
for (const [type, def] of Object.entries(COMP_DEFS)) {
  const b = document.createElement("button");
  b.className = "btn"; b.textContent = def.label; b.dataset.type = type;
  b.addEventListener("click", () => {
    mode = "place:" + type; selectedId = null;
    palette.querySelectorAll("button").forEach((x) => x.classList.remove("active"));
    b.classList.add("active");
    $("circuit-status").textContent = "Click the canvas to place a " + def.label + ".";
  });
  palette.appendChild(b);
}
$("tool-wire").addEventListener("click", () => { mode = "wire"; pendingWire = null; $("circuit-status").textContent = "Wire mode: click two terminals to connect them."; });
$("tool-select").addEventListener("click", () => { mode = "select"; pendingWire = null; });
$("btn-clear").addEventListener("click", () => { if (confirm("Clear the whole circuit?")) { circuit = { name: "Untitled circuit", components: [], connections: [] }; counters = {}; selectedId = null; renderAll(); } });

cv.addEventListener("mousedown", (e) => {
  const r = cv.getBoundingClientRect();
  const px = (e.clientX - r.left) * (cv.width / r.width), py = (e.clientY - r.top) * (cv.height / r.height);
  const term = findTerminal(px, py);
  if (mode === "wire" || term) {
    if (term) {
      if (!pendingWire) { pendingWire = term; }
      else if (pendingWire.comp !== term.comp || pendingWire.term !== term.term) {
        circuit.connections.push({ a: { comp: pendingWire.comp, term: pendingWire.term }, b: { comp: term.comp, term: term.term } });
        pendingWire = null;
      }
      renderAll(); return;
    }
  }
  if (mode.startsWith("place:")) { addComponent(mode.slice(6), px - 36, py - 24); mode = "select"; palette.querySelectorAll("button").forEach((x) => x.classList.remove("active")); return; }
  const c = findComponent(px, py);
  if (c) { selectedId = c.id; drag = { id: c.id, dx: px - c.x, dy: py - c.y }; renderAll(); }
  else { selectedId = null; renderAll(); }
});
cv.addEventListener("mousemove", (e) => {
  if (!drag) return;
  const r = cv.getBoundingClientRect();
  const px = (e.clientX - r.left) * (cv.width / r.width), py = (e.clientY - r.top) * (cv.height / r.height);
  const c = circuit.components.find((x) => x.id === drag.id);
  if (c) { c.x = Math.round((px - drag.dx) / 10) * 10; c.y = Math.round((py - drag.dy) / 10) * 10; draw(); }
});
window.addEventListener("mouseup", () => { drag = null; });

/* ---------- inspector & BOM ---------- */
function renderInspector() {
  const el = $("inspector");
  const c = circuit.components.find((x) => x.id === selectedId);
  if (!c) { el.innerHTML = "<p class='small muted'>Nothing selected.</p>"; return; }
  const def = COMP_DEFS[c.type];
  let h = `<p><strong>${esc(c.id)}</strong> — ${def.label}</p>`;
  for (const [key, label] of def.fields) {
    const val = c.params[key];
    h += `<div class="field-row"><label>${esc(label)}</label><input data-param="${esc(key)}" type="text" value="${esc(val)}"></div>`;
  }
  h += `<div class="btn-row"><button class="btn danger" id="btn-del-comp">Delete</button></div>`;
  el.innerHTML = h;
  el.querySelectorAll("input[data-param]").forEach((inp) => {
    inp.addEventListener("change", () => {
      const key = inp.dataset.param;
      let v = inp.value.trim();
      if (v === "true") v = true; else if (v === "false") v = false;
      else if (!isNaN(parseEng(v)) && key !== "waveform") v = parseEng(v);
      c.params[key] = v;
      renderAll();
    });
  });
  $("btn-del-comp").addEventListener("click", () => {
    circuit.components = circuit.components.filter((x) => x.id !== c.id);
    circuit.connections = circuit.connections.filter((w) => w.a.comp !== c.id && w.b.comp !== c.id);
    selectedId = null; renderAll();
  });
}
function renderBOM() {
  const el = $("bom");
  if (!circuit.components.length) { el.innerHTML = "<p class='small muted'>No components.</p>"; return; }
  el.innerHTML = "<table class='results'><tr><th>ID</th><th>Type</th><th>Value</th></tr>" +
    circuit.components.map((c) => `<tr><td>${esc(c.id)}</td><td>${esc(COMP_DEFS[c.type].label)}</td><td>${esc(c.params.value !== undefined ? fmtEng(c.params.value, COMP_DEFS[c.type].unit || "") : "—")}</td></tr>`).join("") + "</table>";
}
function renderWires() {
  const el = $("wire-list");
  if (!circuit.connections.length) { el.innerHTML = "<p class='small muted'>No wires yet.</p>"; return; }
  el.innerHTML = circuit.connections.map((w, i) =>
    `<div class="field-row"><span>${esc(w.a.comp)}:${w.a.term} ↔ ${esc(w.b.comp)}:${w.b.term}</span><button class="btn danger" data-wire="${i}">✕</button></div>`).join("");
  el.querySelectorAll("button[data-wire]").forEach((b) => b.addEventListener("click", () => { circuit.connections.splice(+b.dataset.wire, 1); renderAll(); }));
}
function renderOutputNodes() {
  const { members } = resolveNets(circuit);
  const sel = $("an-output-node");
  const cur = sel.value;
  sel.innerHTML = "<option value=''>(all nodes)</option>" + Object.keys(members).filter((n) => n !== "0").map((n) => `<option value="${esc(n)}">${esc(n)} (${esc(members[n].join(", "))})</option>`).join("");
  sel.value = cur;
}
function renderAll() { draw(); renderInspector(); renderBOM(); renderWires(); renderOutputNodes(); }

/* ---------- save / load / demos ---------- */
$("btn-save-circuit").addEventListener("click", () => {
  const blob = new Blob([JSON.stringify({ name: circuit.name, components: circuit.components, connections: circuit.connections }, null, 2)], { type: "application/json" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = (circuit.name || "circuit").replace(/\s+/g, "-") + ".json"; a.click();
});
$("btn-load-circuit").addEventListener("click", () => $("file-circuit").click());
$("file-circuit").addEventListener("change", async (e) => {
  const f = e.target.files[0]; if (!f) return;
  loadCircuitJSON(JSON.parse(await f.text()));
});
$("btn-bom-csv").addEventListener("click", () => {
  const rows = [["ID", "Type", "Value"], ...circuit.components.map((c) => [c.id, COMP_DEFS[c.type].label, c.params.value ?? ""])];
  const blob = new Blob([rows.map((r) => r.join(",")).join("\n")], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = "bom.csv"; a.click();
});
function loadCircuitJSON(data) {
  circuit = { name: data.name || "Loaded circuit", components: [], connections: data.connections || [] };
  counters = {};
  // Demo files use net names; convert nets into wires between terminals.
  const byNet = {};
  for (const comp of data.components || []) {
    const c = { ...comp, x: comp.x ?? 80, y: comp.y ?? 80, params: comp.params || {}, nodes: comp.nodes.map((_, i) => comp.id + ":" + i) };
    circuit.components.push(c);
    comp.nodes.forEach((net, i) => { (byNet[net] = byNet[net] || []).push({ comp: comp.id, term: i }); });
    const m = comp.id.match(/^([A-Za-z]+)(\d+)$/);
    if (m) counters[m[1]] = Math.max(counters[m[1]] || 0, +m[2]);
  }
  if (!data.connections) {
    for (const net in byNet) {
      const ts = byNet[net];
      if (net === "0") { for (const t of ts) circuit.connections.push({ a: t, b: { comp: "__gnd__", term: 0 } }); }
      else for (let i = 1; i < ts.length; i++) circuit.connections.push({ a: ts[i - 1], b: ts[i] });
    }
    // add a ground component for the "0" net (the wires to it were
    // already added in the nets loop above)
    if (byNet["0"]) {
      circuit.components.push({ id: "__gnd__", type: "ground", x: 80, y: 420, params: {}, nodes: ["__gnd__:0"] });
    }
  }
  // lay out components in a row if they have no positions
  circuit.components.forEach((c, i) => { if (c.x === 80 && c.y === 80) { c.x = 60 + (i % 4) * 180; c.y = 60 + Math.floor(i / 4) * 160; } });
  renderAll();
  $("circuit-status").textContent = "Loaded " + circuit.name + " — " + circuit.components.length + " components, " + circuit.connections.length + " wires.";
}
$("demo-select").addEventListener("change", async (e) => {
  const name = e.target.value; if (!name) return;
  try {
    const data = await (await fetch("workspace/test-circuits/" + name + ".json")).json();
    loadCircuitJSON(data);
  } catch (err) { $("circuit-status").textContent = "Could not load demo: " + err.message; }
});

/* ---------- validation (local mirror of backend rules) ---------- */
function validateLocal() {
  const errors = [];
  if (!circuit.components.length) errors.push("Circuit is empty.");
  const ids = new Set();
  for (const c of circuit.components) {
    if (ids.has(c.id)) errors.push("Duplicate component id: " + c.id);
    ids.add(c.id);
    if (!COMP_DEFS[c.type]) errors.push(c.id + ": unknown type " + c.type);
    if (c.type === "resistor" || c.type === "capacitor" || c.type === "inductor") {
      if (!(c.params.value > 0)) errors.push(c.id + ": value must be > 0.");
    }
  }
  const { members } = resolveNets(circuit);
  if (!members["0"] && !circuit.components.some((c) => c.type === "ground")) errors.push("No ground reference — add a ground component or a node named 0.");
  return errors;
}
$("btn-validate").addEventListener("click", () => {
  const errors = validateLocal();
  $("sim-warnings").textContent = "";
  $("sim-results").innerHTML = errors.length
    ? "<p class='warn-list'>" + errors.map(esc).join("<br>") + "</p>"
    : "<p>✓ Circuit looks valid — " + circuit.components.length + " components, " + circuit.connections.length + " wires.</p>";
});

/* ---------- run simulation ---------- */
$("analysis-type").addEventListener("change", (e) => {
  document.querySelectorAll("[data-analysis]").forEach((el) => { el.style.display = el.dataset.analysis === e.target.value ? "" : "none"; });
});
document.querySelectorAll("[data-analysis]").forEach((el) => { el.style.display = el.dataset.analysis === "transient" ? "" : "none"; });
$("btn-run").addEventListener("click", async () => {
  const errors = validateLocal();
  if (errors.length) { $("sim-results").innerHTML = "<p class='warn-list'>" + errors.map(esc).join("<br>") + "</p>"; return; }
  if (backendDown) { $("sim-results").innerHTML = "<p class='warn-list'>The backend is not reachable — sign-in and simulation both need it. The hosted server sleeps when idle; if it stays down, wait a minute and try again.</p>"; return; }
  if (!projectId) { $("sim-results").innerHTML = "<p>Sign in and pick a project to run the simulation — the solver runs on the backend and stores the result as a job on that project. The circuit itself is saved in your browser.</p>"; return; }
  const type = $("analysis-type").value;
  const analysis = { type };
  if (type === "transient") { analysis.duration = parseEng($("an-duration").value); analysis.steps = +$("an-steps").value; if ($("an-output-node").value) analysis.output_nodes = [$("an-output-node").value]; }
  if (type === "ac") { analysis.f_start = parseEng($("an-fstart").value); analysis.f_stop = parseEng($("an-fstop").value); analysis.points = +$("an-points").value; if ($("an-output-node").value) analysis.output_node = $("an-output-node").value; }
  $("sim-results").innerHTML = "<p>Running…</p>";
  try {
    const job = await api("/api/v1/circuits/simulate", { method: "POST", body: JSON.stringify({ project_id: projectId, circuit: { name: circuit.name, components: circuit.components, connections: circuit.connections }, analysis }) });
    const res = job.results;
    if (job.status === "failed") { $("sim-results").innerHTML = "<p class='warn-list'>Simulation failed: " + esc(res.error || "unknown error") + "</p>"; return; }
    renderSimResults(res.values);
    $("sim-warnings").textContent = (res.values.warnings || []).join(" ");
  } catch (err) {
    $("sim-results").innerHTML = "<p class='warn-list'>Could not run: " + esc(err.message) + " — is the backend reachable? The hosted server sleeps when idle and can take a minute to wake.</p>";
  }
});
function renderSimResults(v) {
  const { members } = resolveNets(circuit);
  const netLabel = (n) => n === "0" ? "0 (ground)" : n + (members[n] ? " (" + members[n].join(", ") + ")" : "");
  let h = "";
  if (v.analysis === "dc") {
    h += "<h3>DC operating point</h3><table class='results'><tr><th>Node</th><th>Voltage</th></tr>" +
      Object.entries(v.voltages).map(([n, x]) => `<tr><td>${esc(netLabel(n))}</td><td>${fmtEng(x, "V")}</td></tr>`).join("") + "</table>";
    h += "<h3>Power</h3><table class='results'><tr><th>Component</th><th>Power absorbed</th></tr>" +
      Object.entries(v.power).map(([id, p]) => `<tr><td>${esc(id)}</td><td>${p === null ? "—" : fmtEng(p, "W")}</td></tr>`).join("") + "</table>";
  } else if (v.analysis === "transient") {
    h += "<h3>Transient — node voltages over time</h3><canvas class='chart' id='chart-transient' width='880' height='220'></canvas>";
    h += "<p class='small muted'>Duration " + fmtEng(v.t[v.t.length - 1], "s") + ", " + v.t.length + " points, backward-Euler stepping. Final voltages: " +
      Object.entries(v.voltages).map(([n, arr]) => esc(netLabel(n)) + " = " + fmtEng(arr[arr.length - 1], "V")).join("; ") + "</p>";
    setTimeout(() => drawTimeChart($("chart-transient"), v.t, v.voltages), 0);
  } else {
    h += "<h3>AC frequency response</h3><canvas class='chart' id='chart-ac-mag' width='880' height='220'></canvas><canvas class='chart' id='chart-ac-phase' width='880' height='220' style='margin-top:8px'></canvas>";
    h += "<p class='small muted'>Small-signal analysis, linearised at the DC operating point. DC voltages: " +
      Object.entries(v.dc_operating_point).map(([n, x]) => esc(netLabel(n)) + " = " + fmtEng(x, "V")).join("; ") + "</p>";
    setTimeout(() => { drawBode($("chart-ac-mag"), v.frequencies_hz, v.magnitude_v, true); drawBode($("chart-ac-phase"), v.frequencies_hz, v.phase_deg, false); }, 0);
  }
  $("sim-results").innerHTML = h;
}
const COLORS = ["#2563eb", "#dc2626", "#059669", "#d97706", "#7c3aed", "#0891b2"];
function drawTimeChart(c, t, series) {
  if (!c) return;
  const x2 = c.getContext("2d");
  const W = c.width, H = c.height, pad = 40;
  let lo = Infinity, hi = -Infinity;
  for (const arr of Object.values(series)) for (const v of arr) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
  if (lo === hi) { lo -= 1; hi += 1; }
  const padY = (hi - lo) * 0.1 || 1; lo -= padY; hi += padY;
  const X = (i) => pad + (i / (t.length - 1)) * (W - 2 * pad);
  const Y = (v) => H - pad - ((v - lo) / (hi - lo)) * (H - 2 * pad);
  x2.strokeStyle = "#888"; x2.lineWidth = 1;
  x2.strokeRect(pad, pad, W - 2 * pad, H - 2 * pad);
  x2.fillStyle = "#888"; x2.font = "11px sans-serif";
  x2.fillText(fmtEng(hi, "V"), 4, pad + 4); x2.fillText(fmtEng(lo, "V"), 4, H - pad);
  x2.fillText("0 s", pad, H - 8); x2.fillText(fmtEng(t[t.length - 1], "s"), W - pad - 40, H - 8);
  let i = 0;
  for (const [name, arr] of Object.entries(series)) {
    x2.strokeStyle = COLORS[i % COLORS.length]; x2.lineWidth = 1.6; x2.beginPath();
    arr.forEach((v, j) => { const x = X(j), y = Y(v); j ? x2.lineTo(x, y) : x2.moveTo(x, y); });
    x2.stroke();
    x2.fillStyle = COLORS[i % COLORS.length]; x2.fillText(name, pad + 8 + i * 70, pad + 14);
    i++;
  }
}
function drawBode(c, freqs, series, isMag) {
  if (!c) return;
  const x2 = c.getContext("2d");
  const W = c.width, H = c.height, pad = 40;
  const logF = freqs.map((f) => Math.log10(f));
  const f0 = logF[0], f1 = logF[logF.length - 1];
  let lo = Infinity, hi = -Infinity;
  for (const arr of Object.values(series)) for (const v of arr) { lo = Math.min(lo, isMag ? Math.log10(Math.max(v, 1e-9)) : v); hi = Math.max(hi, isMag ? Math.log10(Math.max(v, 1e-9)) : v); }
  if (lo === hi) { lo -= 1; hi += 1; }
  const X = (f) => pad + ((Math.log10(f) - f0) / (f1 - f0)) * (W - 2 * pad);
  const Y = (v) => { const lv = isMag ? Math.log10(Math.max(v, 1e-9)) : v; return H - pad - ((lv - lo) / (hi - lo)) * (H - 2 * pad); };
  x2.strokeStyle = "#888"; x2.lineWidth = 1; x2.strokeRect(pad, pad, W - 2 * pad, H - 2 * pad);
  x2.fillStyle = "#888"; x2.font = "11px sans-serif";
  x2.fillText(isMag ? "Magnitude (V, log scale)" : "Phase (deg)", 4, pad - 6);
  x2.fillText(fmtEng(freqs[0], "Hz"), pad, H - 8); x2.fillText(fmtEng(freqs[freqs.length - 1], "Hz"), W - pad - 50, H - 8);
  let i = 0;
  for (const [name, arr] of Object.entries(series)) {
    x2.strokeStyle = COLORS[i % COLORS.length]; x2.lineWidth = 1.6; x2.beginPath();
    arr.forEach((v, j) => { const x = X(freqs[j]), y = Y(v); j ? x2.lineTo(x, y) : x2.moveTo(x, y); });
    x2.stroke();
    x2.fillStyle = COLORS[i % COLORS.length]; x2.fillText(name, pad + 8 + i * 70, pad + 14);
    i++;
  }
}

/* ---------- calculations tab ---------- */
const ELEC_SOLVERS = ["ohm_law", "series_parallel", "rc_time_constant", "rlc_resonance", "ac_power", "transformer", "dc_motor", "battery_config", "motor_gearbox", "solenoid", "wire_resistance"];
const CALC_FIELDS = {
  ohm_law: [["voltage_V", "Voltage (V) — leave blank to solve"], ["current_A", "Current (A) — leave blank to solve"], ["resistance_ohm", "Resistance (Ω) — leave blank to solve"]],
  series_parallel: [["kind", "Kind (resistor/capacitor/inductor)"], ["mode", "Mode (series/parallel)"], ["values", "Values, comma-separated"]],
  rc_time_constant: [["resistance_ohm", "Resistance (Ω)"], ["capacitance_F", "Capacitance (F)"], ["voltage_V", "Step voltage (V)"]],
  rlc_resonance: [["resistance_ohm", "Resistance (Ω)"], ["inductance_H", "Inductance (H)"], ["capacitance_F", "Capacitance (F)"]],
  ac_power: [["voltage_rms_V", "Voltage RMS (V)"], ["current_rms_A", "Current RMS (A)"], ["power_factor", "Power factor (0–1)"]],
  transformer: [["primary_voltage_V", "Primary voltage (V)"], ["turns_primary", "Primary turns"], ["turns_secondary", "Secondary turns"], ["efficiency", "Efficiency (0–1)"], ["load_power_W", "Load power (W)"]],
  dc_motor: [["voltage_V", "Supply voltage (V)"], ["resistance_ohm", "Armature resistance (Ω)"], ["kt_Nm_per_A", "Kt (N·m/A)"], ["ke_V_per_rad_s", "Ke (V·s/rad)"], ["load_torque_Nm", "Load torque (N·m)"]],
  battery_config: [["cell_voltage_V", "Cell voltage (V)"], ["cell_capacity_Ah", "Cell capacity (Ah)"], ["series", "Cells in series"], ["parallel", "Strings in parallel"], ["load_current_A", "Load current (A)"]],
  motor_gearbox: [["voltage_V", "Supply voltage (V)"], ["resistance_ohm", "Armature resistance (Ω)"], ["kt_Nm_per_A", "Kt (N·m/A)"], ["ke_V_per_rad_s", "Ke (V·s/rad)"], ["load_torque_Nm", "Load torque at output (N·m)"], ["gear_ratio", "Gear ratio"], ["gear_efficiency", "Gear efficiency (0–1)"]],
  solenoid: [["turns", "Turns"], ["length_m", "Length (m)"], ["area_m2", "Cross-section area (m²)"], ["mu_r", "Relative permeability μr"], ["current_A", "Current (A)"]],
  wire_resistance: [["material_id", "Material (id, e.g. copper-c110)"], ["length_m", "Length (m)"], ["area_mm2", "Cross-section (mm²)"], ["current_A", "Current (A)"]],
};
const UNIT_LABELS = { voltage_V: "V", current_A: "A", resistance_ohm: "Ω", power_W: "W", tau_s: "s", cutoff_hz: "Hz", voltage_at_tau_V: "V", settle_5tau_s: "s", resonant_freq_hz: "Hz", angular_freq_rad_s: "rad/s", quality_factor: "", bandwidth_hz: "Hz", apparent_power_VA: "VA", real_power_W: "W", reactive_power_var: "var", phase_angle_deg: "°", secondary_voltage_V: "V", turns_ratio: "", secondary_current_A: "A", primary_current_A: "A", stall_current_A: "A", stall_torque_Nm: "N·m", no_load_speed_rpm: "rpm", speed_rpm: "rpm", power_in_W: "W", power_out_W: "W", efficiency: "", total_voltage_V: "V", total_capacity_Ah: "Ah", energy_Wh: "Wh", runtime_h: "h", motor_speed_rpm: "rpm", motor_torque_Nm: "N·m", output_speed_rpm: "rpm", output_torque_Nm: "N·m", motor_current_A: "A", inductance_H: "H", field_T: "T", flux_Wb: "Wb", energy_J: "J", resistivity_ohm_m: "Ω·m", voltage_drop_V: "V", power_loss_W: "W", equivalent: "" };
let solverMeta = {};
let backendDown = false;  // set when the solver list cannot be fetched
async function loadSolvers() {
  try {
    const data = await api("/api/v1/solvers");
    solverMeta = data.solvers || {};
    const sel = $("calc-solver");
    for (const id of ELEC_SOLVERS) {
      if (!solverMeta[id]) continue;
      const o = document.createElement("option");
      o.value = id; o.textContent = solverMeta[id].label;
      sel.appendChild(o);
    }
    renderCalcForm();
  } catch { backendDown = true; $("calc-form").innerHTML = "<p class='warn-list'>Backend not reachable — the hosted server sleeps when idle; wait a minute and reload the page.</p>"; }
}
function renderCalcForm() {
  const id = $("calc-solver").value;
  const meta = solverMeta[id] || {};
  let h = "<p class='small muted'>" + esc((meta.assumptions || []).join(" ")) + "</p>";
  for (const [key, label] of CALC_FIELDS[id] || []) {
    h += `<div class="field-row"><label>${esc(label)}</label><input data-calc="${esc(key)}" type="text" placeholder="${esc(key)}"></div>`;
  }
  $("calc-form").innerHTML = h;
}
$("calc-solver").addEventListener("change", renderCalcForm);
$("btn-calc-run").addEventListener("click", async () => {
  const id = $("calc-solver").value;
  if (backendDown) { $("calc-results").innerHTML = "<p class='warn-list'>The backend is not reachable — the hosted server sleeps when idle; wait a minute and try again.</p>"; return; }
  if (!projectId) { $("calc-results").innerHTML = "<p>Sign in and pick a project to run and store the calculation.</p>"; return; }
  const inputs = {};
  document.querySelectorAll("input[data-calc]").forEach((inp) => {
    const v = inp.value.trim();
    if (v === "") return;
    if (id === "series_parallel" && inp.dataset.calc === "values") inputs.values = v.split(",").map((x) => parseEng(x));
    else if (inp.dataset.calc === "kind" || inp.dataset.calc === "mode" || inp.dataset.calc === "material_id") inputs[inp.dataset.calc] = v;
    else inputs[inp.dataset.calc] = parseEng(v);
  });
  try {
    const job = await api("/api/v1/simulations", { method: "POST", body: JSON.stringify({ project_id: projectId, solver: id, inputs }) });
    const res = job.results;
    if (job.status === "failed") { $("calc-results").innerHTML = "<p class='warn-list'>" + esc(res.error || "failed") + "</p>"; return; }
    const vals = res.values || {};
    $("calc-results").innerHTML = "<table class='results'>" +
      Object.entries(vals).map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, " "))}</td><td><strong>${esc(typeof v === "number" ? fmtEng(v, UNIT_LABELS[k] || "") : String(v))}</strong></td></tr>`).join("") +
      "</table><p class='small muted'>Method: " + esc(res.method || "analytical") + ". " + esc((res.assumptions || []).join(" ")) + "</p>";
  } catch (err) { $("calc-results").innerHTML = "<p class='warn-list'>" + esc(err.message) + "</p>"; }
});
loadSolvers();

/* ---------- motors & batteries tab ---------- */
async function runSolverInto(solver, inputs, el) {
  if (!projectId) { el.innerHTML = "<p>Sign in and pick a project to run and store the calculation.</p>"; return; }
  try {
    const job = await api("/api/v1/simulations", { method: "POST", body: JSON.stringify({ project_id: projectId, solver, inputs }) });
    const res = job.results;
    if (job.status === "failed") { el.innerHTML = "<p class='warn-list'>" + esc(res.error || "failed") + "</p>"; return; }
    const vals = res.values || {};
    el.innerHTML = "<table class='results'>" +
      Object.entries(vals).map(([k, v]) => `<tr><td>${esc(k.replace(/_/g, " "))}</td><td><strong>${esc(typeof v === "number" ? fmtEng(v, UNIT_LABELS[k] || "") : String(v))}</strong></td></tr>`).join("") + "</table>";
  } catch (err) { el.innerHTML = "<p class='warn-list'>" + esc(err.message) + "</p>"; }
}
$("btn-motor-run").addEventListener("click", () => runSolverInto("dc_motor", {
  voltage_V: +$("m-volt").value, resistance_ohm: +$("m-ra").value, kt_Nm_per_A: +$("m-kt").value,
  ke_V_per_rad_s: +$("m-ke").value, load_torque_Nm: +$("m-tl").value,
}, $("motor-results")));
$("btn-motor-gear-run").addEventListener("click", () => runSolverInto("motor_gearbox", {
  voltage_V: +$("m-volt").value, resistance_ohm: +$("m-ra").value, kt_Nm_per_A: +$("m-kt").value,
  ke_V_per_rad_s: +$("m-ke").value, load_torque_Nm: +$("mg-tl").value,
  gear_ratio: +$("mg-ratio").value, gear_efficiency: +$("mg-eff").value,
}, $("motor-gear-results")));
$("btn-battery-run").addEventListener("click", () => runSolverInto("battery_config", {
  cell_voltage_V: +$("b-v").value, cell_capacity_Ah: +$("b-ah").value,
  series: +$("b-s").value, parallel: +$("b-p").value, load_current_A: +$("b-i").value,
}, $("battery-results")));
$("btn-transformer-run").addEventListener("click", () => runSolverInto("transformer", {
  primary_voltage_V: +$("t-v1").value, turns_primary: +$("t-n1").value, turns_secondary: +$("t-n2").value,
  efficiency: +$("t-eff").value, load_power_W: +$("t-p").value,
}, $("transformer-results")));

/* ---------- jobs tab ---------- */
async function refreshJobs() {
  if (!projectId) { $("jobs-list").innerHTML = "<p>Pick a project to see its simulation jobs.</p>"; return; }
  try {
    const data = await api("/api/v1/simulations?project_id=" + encodeURIComponent(projectId));
    const jobs = (data.simulations || []).filter((j) => j.solver.startsWith("circuit_") || ELEC_SOLVERS.includes(j.solver));
    $("jobs-list").innerHTML = jobs.length ? jobs.map((j) =>
      `<div class="card" style="margin-bottom:8px"><strong>${esc(j.solver)}</strong> — ${esc(j.status)} — ${esc(j.created_at || "")}<br><span class="small muted">${esc(JSON.stringify(j.results || {}).slice(0, 300))}</span></div>`).join("")
      : "<p>No electrical jobs on this project yet.</p>";
  } catch (err) { $("jobs-list").innerHTML = "<p class='warn-list'>" + esc(err.message) + "</p>"; }
}
$("btn-jobs-refresh").addEventListener("click", refreshJobs);

renderAll();
