"use strict";
// Reroll Observatory. All numbers come from the Python rules engine via /api; this file only draws.

const STATS = ["energy", "mood", "money", "social", "goal"];
const STAT_NAME = {
  en: { energy: "Energy", mood: "Mood", money: "Money", social: "Social", goal: "Goal" },
  zh: { energy: "精力", mood: "心情", money: "财务", social: "社交", goal: "目标" },
};
const T = {
  en: {
    legal: "For entertainment only. Not a prediction or advice.",
    hint: "Hover a choice to see the futures it leads to. Click a hollow ghost ○ to reroll a past day.",
    details: "Details", close: "Close", drawer: "Your multiverse",
    risk: "Risk outlook", branches: "Parallel lives", reroll: "Reroll a past day", tags: "Active habits", table: "Forecast",
    noTags: "No habits yet.", noReroll: "Make a choice first.",
    note: "Every number comes from simulated futures under made-up rules (params.yaml). It is a toy, not a prediction or advice.",
    day: (d) => `Day ${d}`, branch: "on",
    riskLevel: { low: "low risk", medium: "medium risk", high: "high risk" },
    riskText: (p, n, below) => `${p}% of ${n} simulated futures see energy, mood, money or social drop below ${below} within 7 days.`,
    thead: (s) => ["Day", "Low", `${s} median`, "High"],
    rerolled: (d, b) => `Rerolled Day ${d} on a new branch: ${b}`,
    switched: (b) => `Switched to ${b}`,
    from: (d) => (d === 0 ? "from the start" : `from Day ${d}`),
    tipChose: "Chose", tipGhost: "Ghost · not taken", tipClick: "Click to reroll from here", tipFuture: "Unobserved",
    tipMedian: "median", tipRange: "80% of futures",
    born: "born", today: "now", danger: "danger zone",
    stage: (s) => `${s} over time. The past is a golden line, skipped choices are ghost points, and the next 7 days are simulated futures.`,
    error: "Something went wrong",
  },
  zh: {
    legal: "仅供娱乐，不构成任何预测或建议。",
    hint: "悬停选项，看它通往哪些未来。点击空心的幽灵 ○，重来过去的某一天。",
    details: "详情", close: "关闭", drawer: "你的多重宇宙",
    risk: "风险展望", branches: "平行人生", reroll: "重来过去的某一天", tags: "活跃习惯", table: "预测",
    noTags: "还没有养成习惯。", noReroll: "先做一个选择吧。",
    note: "这里的每个数字都来自模拟的未来，规则写在 params.yaml 里，是编的。这是个玩具，不是预测，也不是建议。",
    day: (d) => `Day ${d}`, branch: "分支",
    riskLevel: { low: "低风险", medium: "中风险", high: "高风险" },
    riskText: (p, n, below) => `${n} 个模拟的未来里，有 ${p}% 会在 7 天内出现精力、心情、财务或社交跌破 ${below}。`,
    thead: (s) => ["天", "低", `${s}中位数`, "高"],
    rerolled: (d, b) => `已在新分支 ${b} 上重来 Day ${d}`,
    switched: (b) => `已切换到 ${b}`,
    from: (d) => (d === 0 ? "分叉自起点" : `分叉自 Day ${d}`),
    tipChose: "选择了", tipGhost: "幽灵 · 没选", tipClick: "点击从这里重来", tipFuture: "未观测",
    tipMedian: "中位数", tipRange: "80% 的未来",
    born: "出生", today: "现在", danger: "危险区",
    stage: (s) => `${s}随时间的变化：过去是一条金线，没选的选项是幽灵点，未来 7 天是模拟出来的人生轨迹。`,
    error: "出错了",
  },
};

let S = null;          // the latest /api/state snapshot
let stat = "energy";
let busy = false;
let hoverOpt = null;

// ============================================================ helpers
const $ = (id) => document.getElementById(id);
function h(tag, cls, text, parent) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (text != null) e.textContent = text;
  if (parent) parent.appendChild(e);
  return e;
}
const lang = () => (S && S.lang === "zh" ? "zh" : "en");
const tr = () => T[lang()];
const sname = (k) => STAT_NAME[lang()][k];
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const ease = (t) => 1 - Math.pow(1 - t, 3);
const lerp = (a, b, t) => a + (b - a) * t;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const chosenOf = (c) => c.options.find((o) => o.id === c.chosen);
function mulberry32(seed) {
  return function () {
    seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function toast(msg) {
  const el = $("toast"); el.textContent = msg; el.classList.add("show");
  clearTimeout(toast.t); toast.t = setTimeout(() => el.classList.remove("show"), 3200);
}

async function api(path, body) {
  const res = await fetch(path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {});
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `${res.status}`);
  return data;
}

// ============================================================ stage (canvas)
const cv = $("stage");
const ctx = cv.getContext("2d");
let W = 0, H = 0, dpr = 1, starLayer = null, hits = [];
const COLORS = { real: "#c4801c", maybe: "114,127,224", ghost: "#5d6391", ink3: "#757aa3", ink2: "#a9adca", bad: "214,81,81" };
const GHOST_RGB = "93,99,145";
const anim = { growT0: 0, collapse: null, measure: null, flash: null };
const mixRgb = (a, b, t) => { const x = a.split(",").map(Number), y = b.split(",").map(Number); return x.map((v, i) => Math.round(lerp(v, y[i], t))).join(","); };

function resize() {
  dpr = Math.min(2, devicePixelRatio || 1);
  W = cv.clientWidth || innerWidth; H = cv.clientHeight || innerHeight;
  if (!W || !H) { starLayer = null; return; } // not laid out yet; the ResizeObserver calls again
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  starLayer = document.createElement("canvas");
  starLayer.width = cv.width; starLayer.height = cv.height;
  const s = starLayer.getContext("2d");
  s.scale(dpr, dpr);
  const g = s.createRadialGradient(W * 0.62, H * 0.38, 0, W * 0.62, H * 0.38, Math.max(W, H) * 0.75);
  g.addColorStop(0, "#151a3a"); g.addColorStop(1, "#0b0d1c");
  s.fillStyle = g; s.fillRect(0, 0, W, H);
  const rng = mulberry32(7);
  for (let i = 0, n = Math.round((W * H) / 4200); i < n; i++) {
    s.globalAlpha = 0.12 + rng() * 0.5;
    s.fillStyle = rng() < 0.12 ? COLORS.real : "#c9cce6";
    s.beginPath(); s.arc(rng() * W, rng() * H, rng() < 0.93 ? 0.6 : 1.3, 0, Math.PI * 2); s.fill();
  }
  s.globalAlpha = 1;
}

function layout(snap = S) {
  const today = snap.today;
  const days = snap.forecast.days;
  const top = 92;
  const plotBottom = Math.max(top + 160, H - $("bottom").offsetHeight + 30);
  const xL = W < 560 ? 26 : 56;
  const xNow = W * (W < 560 ? 0.34 : 0.42);
  const xR = W - (W < 560 ? 54 : 110);
  const X = (d) => (d <= today ? (today === 0 ? xNow : xL + (d / today) * (xNow - xL)) : xNow + ((d - today) / days) * (xR - xNow));
  const [lo, hi] = snap.bounds[stat];
  const Y = (v) => top + (1 - (v - lo) / (hi - lo)) * (plotBottom - top);
  return { today, days, top, plotBottom, xL, xNow, xR, X, Y };
}

/** Draw simulated futures as threads. `runs[r][i]` is the stat on day today+1+i of run r. */
function drawThreads(G, runs, start, { alpha, color, grow = 1, collapseTo = null, collapseT = 0 }) {
  const { X, Y, today } = G;
  ctx.save();
  ctx.globalCompositeOperation = "lighter";
  ctx.lineWidth = 1.1; ctx.lineCap = "round"; ctx.lineJoin = "round";
  const steps = runs[0].length, shown = grow * steps, time = performance.now() / 1000;
  runs.forEach((run, r) => {
    const shimmer = reduced() ? 1 : 0.75 + 0.25 * Math.sin(time * 1.3 + r * 1.7);
    ctx.strokeStyle = `rgba(${color},${alpha * shimmer})`;
    ctx.beginPath();
    let px = start.x, py = start.y;
    if (collapseTo) { px = lerp(px, collapseTo.x, collapseT); py = lerp(py, collapseTo.y, collapseT); }
    ctx.moveTo(px, py);
    let ex = px, ey = py;
    for (let i = 0; i < steps && i < shown; i++) {
      const part = Math.min(1, shown - i);
      const x0 = i === 0 ? start.x : X(today + i), y0 = i === 0 ? start.y : Y(run[i - 1]);
      let x = lerp(x0, X(today + i + 1), part), y = lerp(y0, Y(run[i]), part);
      if (collapseTo) { x = lerp(x, collapseTo.x, collapseT); y = lerp(y, collapseTo.y, collapseT); }
      const mx = (ex + x) / 2;
      ctx.bezierCurveTo(mx, ey, mx, y, x, y);
      ex = x; ey = y;
    }
    ctx.stroke();
    if (grow >= 1 && !collapseTo) {
      ctx.fillStyle = `rgba(${color},${Math.min(1, alpha * 4) * shimmer})`;
      ctx.beginPath(); ctx.arc(ex, ey, 1.4, 0, Math.PI * 2); ctx.fill();
    }
  });
  ctx.restore();
}

/** Direct labels at the right edge: option letter + where 80% of its futures land. Nudged apart. */
function drawEndLabels(G) {
  const x = G.xR + 14;
  const rows = S.decision.options.map((o) => {
    const bands = S.option_forecasts[o.id].bands[stat];
    const b = bands[bands.length - 1];
    return { o, b, y: G.Y(b.p50) };
  }).sort((a, b) => a.y - b.y);
  for (let i = 1; i < rows.length; i++) rows[i].y = Math.max(rows[i].y, rows[i - 1].y + 22);
  for (const r of rows) {
    const on = !hoverOpt || hoverOpt.id === r.o.id;
    ctx.globalAlpha = on ? 1 : 0.35;
    ctx.strokeStyle = "rgba(114,127,224,0.9)"; ctx.lineWidth = 1.2;
    ctx.beginPath(); ctx.arc(x + 8, r.y, 9, 0, Math.PI * 2); ctx.stroke();
    ctx.fillStyle = COLORS.ink2; ctx.font = "500 11px 'IBM Plex Mono', monospace"; ctx.textAlign = "center";
    ctx.fillText(r.o.id.toUpperCase(), x + 8, r.y + 4);
    ctx.textAlign = "left"; ctx.fillStyle = on ? "#eceef8" : COLORS.ink3; ctx.font = "500 12px 'IBM Plex Mono', monospace";
    ctx.fillText(`${r.b.p10}–${r.b.p90}`, x + 24, r.y + 4);
  }
  ctx.globalAlpha = 1;
}

function draw() {
  if (!starLayer || !S) return;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.drawImage(starLayer, 0, 0, W, H);
  const G = layout();
  const { X, Y, today, plotBottom } = G;
  hits = [];
  const path = S.path;
  const nowV = S.state[stat];
  const tNow = performance.now();

  // danger zone: a red haze under the threshold
  if (S.risk_stats.includes(stat)) {
    const yD = Y(S.danger_below), y0 = Y(S.bounds[stat][0]);
    const g = ctx.createLinearGradient(0, yD, 0, y0);
    g.addColorStop(0, `rgba(${COLORS.bad},0)`); g.addColorStop(1, `rgba(${COLORS.bad},0.16)`);
    ctx.fillStyle = g; ctx.fillRect(G.xL, yD, G.xR - G.xL, y0 - yD);
    ctx.fillStyle = COLORS.ink3; ctx.font = "11px 'IBM Plex Mono', monospace";
    ctx.fillText(tr().danger, G.xL, y0 - 8);
  }

  // day ticks
  ctx.font = "11px 'IBM Plex Mono', monospace"; ctx.textAlign = "center";
  for (let d = 0; d <= today + G.days; d++) {
    if (d < today && today > 8 && d % Math.ceil(today / 8)) continue;
    ctx.fillStyle = d === today ? COLORS.ink2 : COLORS.ink3;
    ctx.globalAlpha = d > today ? 0.6 : 1;
    ctx.fillText(d === 0 ? tr().born : d === today ? tr().today : d > today ? `+${d - today}` : String(d), X(d), plotBottom + 22);
  }
  ctx.globalAlpha = 1; ctx.textAlign = "left";

  // other branches, from where they split off this timeline
  ctx.lineWidth = 1.5; ctx.strokeStyle = COLORS.ghost;
  for (const b of S.others) {
    const pts = b.points.filter((p) => p.day <= today);
    if (pts.length < 2) continue;
    ctx.globalAlpha = 0.5;
    ctx.beginPath();
    pts.forEach((p, i) => (i ? ctx.lineTo(X(p.day), Y(p.state[stat])) : ctx.moveTo(X(p.day), Y(p.state[stat]))));
    ctx.stroke();
    const last = pts[pts.length - 1];
    ctx.fillStyle = COLORS.ink3; ctx.font = "11px 'IBM Plex Mono', monospace";
    ctx.fillText(b.name, X(last.day) + 8, Y(last.state[stat]) - 8);
  }
  ctx.globalAlpha = 1;

  // ghosts: what each skipped option would have done that day
  path.forEach((c, i) => {
    const prev = i === 0 ? { day: 0, state: S.initial } : path[i - 1];
    for (const o of c.options) {
      if (o.id === c.chosen) continue;
      const gv = o.state_if[stat];
      const x = X(c.day), y = Y(gv);
      ctx.strokeStyle = COLORS.ghost; ctx.globalAlpha = 0.55; ctx.lineWidth = 1.2;
      ctx.beginPath(); ctx.moveTo(X(prev.day), Y(prev.state[stat])); ctx.lineTo(x, y); ctx.stroke();
      ctx.globalAlpha = 1; ctx.lineWidth = 2;
      ctx.fillStyle = "#0b0d1c"; ctx.beginPath(); ctx.arc(x, y, 4.5, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
      hits.push({ x, y, r: 14, kind: "ghost", c, o, gv });
    }
  });

  // reality: the golden thread
  const pts = [{ day: 0, state: S.initial }, ...path];
  ctx.save();
  ctx.shadowColor = COLORS.real; ctx.shadowBlur = 14;
  ctx.strokeStyle = COLORS.real; ctx.lineWidth = 3; ctx.lineJoin = "round"; ctx.lineCap = "round";
  ctx.beginPath();
  pts.forEach((c, i) => (i ? ctx.lineTo(X(c.day), Y(c.state[stat])) : ctx.moveTo(X(c.day), Y(c.state[stat]))));
  ctx.stroke();
  ctx.restore();
  for (const c of pts.slice(1, -1)) {
    ctx.fillStyle = COLORS.real; ctx.strokeStyle = "#0b0d1c"; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(X(c.day), Y(c.state[stat]), 4, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    hits.push({ x: X(c.day), y: Y(c.state[stat]), r: 12, kind: "past", c });
  }

  // the future
  const now = { x: X(today), y: Y(nowV) };
  const runsOf = (id) => S.option_forecasts[id].paths[stat];
  if (anim.collapse || anim.measure) {
    // waiting for the server (measure), then collapsing onto the observed value
    const col = anim.collapse;
    const m = anim.measure;
    const raw = col ? Math.min(1, (tNow - col.t0) / col.ms) : 0;
    const greyT = Math.min(1, (tNow - m.t0) / 500);
    for (const o of S.decision.options) {
      if (o.id === m.chosen) {
        drawThreads(G, runsOf(o.id), now, { alpha: 0.11, color: COLORS.maybe, collapseTo: col ? col.to : null, collapseT: ease(raw) });
      } else {
        drawThreads(G, runsOf(o.id), now, { alpha: 0.09 * (1 - 0.6 * greyT) * (1 - raw), color: mixRgb(COLORS.maybe, GHOST_RGB, greyT) });
      }
    }
  } else {
    const grow = reduced() ? 1 : ease(Math.min(1, (tNow - anim.growT0) / 1100));
    if (hoverOpt) {
      drawThreads(G, S.forecast.paths[stat], now, { alpha: 0.025, color: COLORS.maybe, grow });
      drawThreads(G, runsOf(hoverOpt.id), now, { alpha: 0.13, color: "150,160,255" });
    } else {
      drawThreads(G, S.forecast.paths[stat], now, { alpha: 0.075, color: COLORS.maybe, grow });
    }
    if (grow >= 1) drawEndLabels(G);
  }

  // now: a pulsing star
  const pulse = reduced() ? 0 : (tNow / 2400) % 1;
  ctx.save();
  ctx.strokeStyle = COLORS.real; ctx.globalAlpha = 0.7 * (1 - pulse); ctx.lineWidth = 1.5;
  ctx.beginPath(); ctx.arc(now.x, now.y, 6 + pulse * 18, 0, Math.PI * 2); ctx.stroke();
  ctx.globalAlpha = 1; ctx.shadowColor = COLORS.real; ctx.shadowBlur = 18; ctx.fillStyle = COLORS.real;
  ctx.beginPath(); ctx.arc(now.x, now.y, 6, 0, Math.PI * 2); ctx.fill();
  ctx.restore();

  if (anim.flash) {
    const t = (tNow - anim.flash.t0) / 520;
    if (t >= 1) anim.flash = null;
    else {
      ctx.save(); ctx.strokeStyle = COLORS.real; ctx.globalAlpha = 1 - t; ctx.lineWidth = 2;
      ctx.shadowColor = COLORS.real; ctx.shadowBlur = 20;
      ctx.beginPath(); ctx.arc(anim.flash.x, anim.flash.y, 6 + ease(t) * 40, 0, Math.PI * 2); ctx.stroke(); ctx.restore();
    }
  }
  draw.G = G;
}

let rafId = 0;
function safeDraw() { try { draw(); } catch (err) { console.error("reroll: frame failed", err); } }
function loop() { safeDraw(); rafId = requestAnimationFrame(loop); }
function start() { cancelAnimationFrame(rafId); if (reduced()) safeDraw(); else loop(); }
const redraw = () => { if (reduced()) safeDraw(); };

// ---- pointer: tooltips and ghost clicks
function showTip(x, y, build) {
  const tip = $("tip"); tip.replaceChildren(); build(tip);
  tip.classList.add("show");
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  tip.style.left = `${clamp(x + 16 + tw > W ? x - 16 - tw : x + 16, 8, W - tw - 8)}px`;
  tip.style.top = `${clamp(y - th - 12, 8, H - th - 8)}px`;
}
const hideTip = () => $("tip").classList.remove("show");
function hitAt(x, y) {
  let best = null, bd = Infinity;
  for (const t of hits) { const d = Math.hypot(t.x - x, t.y - y); if (d < t.r && d < bd) { best = t; bd = d; } }
  return best;
}
cv.addEventListener("pointermove", (e) => {
  if (!S) return;
  const t = hitAt(e.clientX, e.clientY);
  cv.style.cursor = t && t.kind === "ghost" ? "pointer" : "default";
  const G = draw.G;
  if (t && t.kind === "ghost") {
    showTip(t.x, t.y, (tip) => {
      h("div", "h", `Day ${t.c.day} · ${tr().tipGhost}`, tip);
      h("div", "t", t.o.label, tip);
      h("div", "n", `${sname(stat)} ${t.gv}`, tip);
      h("div", "h", tr().tipClick, tip);
    });
  } else if (t && t.kind === "past") {
    showTip(t.x, t.y, (tip) => {
      h("div", "h", `Day ${t.c.day} · ${t.c.id}`, tip);
      h("div", "t", `${tr().tipChose} ${chosenOf(t.c).label}`, tip);
      h("div", "n", STATS.map((k) => `${sname(k)} ${t.c.state[k]}`).join("  "), tip);
    });
  } else if (G && e.clientX > G.xNow + 8 && e.clientX < G.xR + 40 && e.clientY < G.plotBottom + 10 && e.clientY > G.top - 10) {
    const i = clamp(Math.round(((e.clientX - G.xNow) / (G.xR - G.xNow)) * G.days), 1, G.days);
    const b = S.forecast.bands[stat][i - 1];
    showTip(G.X(G.today + i), G.Y(b.p50), (tip) => {
      h("div", "h", `Day ${G.today + i} · ${tr().tipFuture}`, tip);
      h("div", "n", `${tr().tipMedian} ${b.p50}`, tip);
      h("div", "n", `${tr().tipRange} ${b.p10}–${b.p90}`, tip);
    });
  } else hideTip();
});
cv.addEventListener("pointerleave", hideTip);
cv.addEventListener("click", (e) => { const t = hitAt(e.clientX, e.clientY); if (t && t.kind === "ghost") reroll(t.c, t.o.id); });

// ============================================================ overlay ui
function renderTop() {
  const b = $("branch"); b.replaceChildren(); b.append(`${tr().branch} `); h("b", null, S.branch, b);
  const seg = $("stats"); seg.replaceChildren();
  for (const k of STATS) {
    const btn = h("button", null, sname(k), seg);
    btn.type = "button"; btn.id = `stat-${k}`;
    btn.setAttribute("aria-pressed", String(k === stat));
    btn.addEventListener("click", () => { stat = k; renderAll(); });
  }
  $("openDrawer").textContent = tr().details;
  $("closeDrawer").textContent = tr().close;
}

function renderDecision() {
  const d = S.decision;
  $("day").textContent = tr().day(d.day);
  const risk = $("risk"); risk.className = `risk risk-${S.forecast.risk}`; risk.textContent = tr().riskLevel[S.forecast.risk];
  $("question").textContent = d.question;
  $("hint").textContent = tr().hint;
  $("legal").textContent = tr().legal;
  const box = $("options"); box.replaceChildren();
  for (const o of d.options) {
    const b = h("button", "opt", null, box);
    b.type = "button"; b.id = `opt-${o.id}`; b.disabled = busy; b.title = o.hint;
    h("span", "k", o.id.toUpperCase(), b);
    b.append(o.label);
    const on = () => { if (!busy) { hoverOpt = o; redraw(); } };
    const off = () => { if (hoverOpt === o) { hoverOpt = null; redraw(); } };
    b.addEventListener("pointerenter", on); b.addEventListener("focus", on);
    b.addEventListener("pointerleave", off); b.addEventListener("blur", off);
    b.addEventListener("click", () => choose(o.id));
  }
}

function renderDrawer() {
  const t = tr(), fc = S.forecast;
  $("drawerTitle").textContent = t.drawer;
  $("dRiskT").textContent = t.risk; $("dBranchT").textContent = t.branches; $("dRerollT").textContent = t.reroll;
  $("dTagsT").textContent = t.tags; $("dTableT").textContent = `${t.table} · ${sname(stat)}`; $("dNote").textContent = t.note;

  const risk = $("dRisk"); risk.replaceChildren();
  const lvl = h("p", `risk risk-${fc.risk}`, t.riskLevel[fc.risk], risk); lvl.style.margin = "0";
  const meter = h("div", `meter risk-${fc.risk}`, null, risk);
  h("div", null, null, meter).style.width = `${Math.max(2, fc.danger_prob * 100)}%`;
  h("p", null, t.riskText(Math.round(fc.danger_prob * 100), fc.runs, S.danger_below), risk);

  const bl = $("dBranches"); bl.replaceChildren();
  for (const b of S.branches) {
    const btn = h("button", null, null, h("li", null, null, bl));
    btn.type = "button"; btn.setAttribute("aria-current", String(b.current));
    h("span", "mono", b.name, btn);
    h("span", "meta", [`Day ${b.head_day}`, b.from_day != null ? t.from(b.from_day) : ""].filter(Boolean).join(" · "), btn);
    btn.addEventListener("click", () => checkout(b.name));
  }

  const rl = $("dReroll"); rl.replaceChildren();
  if (!S.path.length) h("p", null, t.noReroll, rl);
  for (const c of S.path.slice().reverse()) {
    for (const o of c.options) {
      if (o.id === c.chosen) continue;
      const btn = h("button", null, null, h("li", null, null, rl));
      btn.type = "button";
      h("span", null, `Day ${c.day}: ${o.label}`, btn);
      h("span", "meta", `≠ ${chosenOf(c).label}`, btn);
      btn.addEventListener("click", () => { closeDrawer(); reroll(c, o.id); });
    }
  }

  const tg = $("dTags"); tg.replaceChildren();
  if (!S.tags.length) h("p", null, t.noTags, tg);
  for (const x of S.tags) h("span", "chip", `${x.name}${x.count > 1 ? ` ×${x.count}` : ""} · Day ${x.expires_day}`, tg);

  const table = $("dTable"); table.replaceChildren();
  const hr = h("tr", null, null, h("thead", null, null, table));
  for (const c of t.thead(sname(stat))) h("th", null, c, hr);
  const body = h("tbody", null, null, table);
  fc.bands[stat].forEach((b, i) => {
    const r = h("tr", null, null, body);
    for (const v of [`Day ${S.today + i + 1}`, b.p10, b.p50, b.p90]) h("td", null, String(v), r);
  });
}

function renderAll() {
  document.documentElement.lang = lang() === "zh" ? "zh-CN" : "en";
  cv.setAttribute("aria-label", tr().stage(sname(stat)));
  renderTop(); renderDecision(); renderDrawer();
  redraw();
}

function showSubtitle() {
  const c = S.path[S.path.length - 1];
  if (!c || !c.narration) return;
  const el = $("subtitle");
  el.textContent = c.narration;
  el.classList.add("show");
  clearTimeout(showSubtitle.t);
  showSubtitle.t = setTimeout(() => el.classList.remove("show"), 7000);
}

function setState(next) {
  S = next;
  anim.growT0 = performance.now();
  if (S.notice) toast(S.notice);
}

function fail(err) {
  busy = false; anim.measure = null; anim.collapse = null;
  toast(`${tr().error}: ${err.message}`);
  if (S) renderAll();
}

// ============================================================ actions
async function choose(id) {
  if (busy) return;
  busy = true; hoverOpt = null; hideTip();
  for (const b of document.querySelectorAll(".opt")) b.disabled = true;
  const G = layout();
  const day = S.decision.day;
  anim.measure = { t0: performance.now(), chosen: id };
  let next;
  try {
    next = await api("/api/commit", { option: id });
  } catch (err) { return fail(err); }
  // the observed value is known only now: collapse onto it in the old geometry, then show the new world
  const c = next.path[next.path.length - 1];
  if (!reduced()) {
    anim.collapse = { t0: performance.now(), ms: 650, to: { x: G.X(day), y: G.Y(c.state[stat]) } };
    await wait(650);
  }
  anim.collapse = null; anim.measure = null;
  setState(next);
  const G2 = layout();
  anim.flash = { t0: performance.now(), x: G2.X(c.day), y: G2.Y(c.state[stat]) };
  busy = false;
  renderAll(); showSubtitle();
}

async function reroll(c, optionId) {
  if (busy) return;
  busy = true; hideTip();
  let next;
  try { next = await api("/api/whatif", { commit: c.id, option: optionId }); } catch (err) { return fail(err); }
  setState(next);
  const nc = S.path[S.path.length - 1];
  const G = layout();
  anim.flash = { t0: performance.now(), x: G.X(nc.day), y: G.Y(nc.state[stat]) };
  busy = false;
  renderAll(); showSubtitle();
  toast(tr().rerolled(nc.day, S.branch));
}

async function checkout(name) {
  if (busy || name === S.branch) return;
  busy = true;
  let next;
  try { next = await api("/api/checkout", { branch: name }); } catch (err) { return fail(err); }
  setState(next);
  busy = false;
  renderAll();
  toast(tr().switched(name));
}

function openDrawer() { $("drawer").classList.add("open"); $("scrim").classList.add("open"); $("openDrawer").setAttribute("aria-expanded", "true"); $("closeDrawer").focus(); }
function closeDrawer() { $("drawer").classList.remove("open"); $("scrim").classList.remove("open"); $("openDrawer").setAttribute("aria-expanded", "false"); }
$("openDrawer").addEventListener("click", openDrawer);
$("closeDrawer").addEventListener("click", () => { closeDrawer(); $("openDrawer").focus(); });
$("scrim").addEventListener("click", closeDrawer);
addEventListener("keydown", (e) => {
  if (e.key === "Escape") closeDrawer();
  if (busy || !S || $("drawer").classList.contains("open")) return;
  if (/^[a-d]$/i.test(e.key)) { const btn = $(`opt-${e.key.toLowerCase()}`); if (btn) btn.click(); }
});
new ResizeObserver(() => { resize(); safeDraw(); }).observe(cv);
matchMedia("(prefers-reduced-motion: reduce)").addEventListener("change", start);

(async function boot() {
  resize();
  try {
    setState(await api("/api/state"));
  } catch (err) {
    $("loading").textContent = `${T.en.error}: ${err.message}`;
    return;
  }
  $("loading").remove();
  renderAll();
  start();
})();
