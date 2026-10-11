window.SK = (function () {
  const el = (id) => document.getElementById(id);
  const f1 = (n) => (Math.round(n * 10) / 10).toFixed(1);

  const KEY = "suki.sketch";
  const TOOLS = {
    pen:   { label: "Pencil", hint: "draw freehand" },
    line:  { label: "Line", hint: "press, drag, release — a straight line" },
    erase: { label: "Erase", hint: "tap a stroke to remove it" },
  };
  const FALLBACK = "#f87171";

  let opt = { colour: FALLBACK, w: 3, tool: "pen" };
  try { Object.assign(opt, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) { }
  const save = () => {
    try { localStorage.setItem(KEY, JSON.stringify(opt)); } catch (e) { }
  };

  let stroke = null;
  let sig = null;
  let lastState = null, lastLeg = null;

  const sk = (state) => (state && state.sketch) || {};
  const strokesFor = (state, leg) => (sk(state).legs || {})[leg] || [];
  const palette = (state) => sk(state).palette || [FALLBACK];
  const widths = (state) => sk(state).widths || [1.5, 3, 6];
  const colourOf = (state, c) => palette(state).indexOf(c) >= 0 ? c : FALLBACK;

  const tool = () => opt.tool;

  function overlay(state, leg, g) {
    if (!g) return "";
    let out = '<g class="sk-layer" pointer-events="none">';
    strokesFor(state, leg).forEach((s, i) => {
      const pts = s.pts || [];
      if (pts.length < 2) return;
      const d = "M" + pts.map(p => `${f1(g.sx(p[0]))},${f1(g.sy(p[1]))}`).join(" L");
      out += `<path class="sk-s" data-i="${i}" d="${d}" fill="none"
        stroke="${colourOf(state, s.colour)}" stroke-width="${+s.w || 3}"
        stroke-linecap="round" stroke-linejoin="round" stroke-opacity="0.9"/>`;
    });
    return out + "</g>";
  }

  function livePath(svg, state, g) {
    if (!svg) return;
    let n = svg.querySelector(".sk-live");
    if (!stroke || stroke.pts.length < 2) {
      if (n) n.remove();
      return;
    }
    if (!n) {
      n = document.createElementNS("http://www.w3.org/2000/svg", "path");
      n.setAttribute("class", "sk-live");
      n.setAttribute("fill", "none");
      n.setAttribute("stroke-linecap", "round");
      n.setAttribute("stroke-linejoin", "round");
      n.setAttribute("pointer-events", "none");
      svg.appendChild(n);
    }
    n.setAttribute("stroke", colourOf(state, opt.colour));
    n.setAttribute("stroke-width", String(opt.w));
    n.setAttribute("d", "M" + stroke.pts
      .map(p => `${f1(g.sx(p[0]))},${f1(g.sy(p[1]))}`).join(" L"));
  }

  const MIN_STEP = 5;
  const MAX_SAMPLES = 400;

  function start(thigh, knee) {
    stroke = { pts: [[thigh, knee]] };
  }

  function move(thigh, knee) {
    if (!stroke) return false;
    if (opt.tool === "line") {
      stroke.pts[1] = [thigh, knee];
      return true;
    }
    const last = stroke.pts[stroke.pts.length - 1];
    if (Math.abs(thigh - last[0]) < MIN_STEP && Math.abs(knee - last[1]) < MIN_STEP)
      return false;
    if (stroke.pts.length >= MAX_SAMPLES) return false;
    stroke.pts.push([thigh, knee]);
    return true;
  }

  function end(leg) {
    const s = stroke;
    stroke = null;
    if (!s || s.pts.length < 2) return false;
    RD.send({ type: "sketch_add", leg,
              stroke: { colour: opt.colour, w: opt.w, pts: s.pts } });
    return true;
  }

  function cancel() { stroke = null; }

  function strokeAt(state, leg, g, pt) {
    let best = null, bestd = 14 * 14;
    strokesFor(state, leg).forEach((s, i) => {
      const pts = s.pts || [];
      for (let n = 0; n < pts.length - 1; n++) {
        const ax = g.sx(pts[n][0]), ay = g.sy(pts[n][1]);
        const bx = g.sx(pts[n + 1][0]), by = g.sy(pts[n + 1][1]);
        const vx = bx - ax, vy = by - ay;
        const L2 = vx * vx + vy * vy;
        const t = L2 < 1e-9 ? 0
          : Math.max(0, Math.min(1, ((pt[0] - ax) * vx + (pt[1] - ay) * vy) / L2));
        const dx = pt[0] - (ax + vx * t), dy = pt[1] - (ay + vy * t);
        const d2 = dx * dx + dy * dy;
        if (d2 <= bestd) { bestd = d2; best = i; }
      }
    });
    return best;
  }

  function eraseAt(state, leg, g, pt) {
    const i = strokeAt(state, leg, g, pt);
    if (i === null) return false;
    RD.send({ type: "sketch_erase", leg, index: i });
    return true;
  }

  function render(state, leg) {
    const host = el("sk-panel");
    if (!host) return;
    lastState = state; lastLeg = leg;
    const pal = palette(state);
    const wds = widths(state);
    const mine = strokesFor(state, leg).length;
    const total = Object.keys(sk(state).legs || {})
      .reduce((n, l) => n + strokesFor(state, l).length, 0);

    const next = JSON.stringify([leg, opt, mine, total, pal.length, wds]);
    if (next === sig) return;
    sig = next;

    host.innerHTML = `
      <div class="sk-bar">
        <div class="seg sk-tools">${Object.keys(TOOLS).map(k =>
          `<button class="mbtn${opt.tool === k ? " active" : ""}" data-tool="${k}"
            type="button" title="${TOOLS[k].hint}">${TOOLS[k].label}</button>`)
          .join("")}</div>
        <span class="grow"></span>
        <button class="btn sk-undo" type="button" ${mine ? "" : "disabled"}>Undo</button>
        <button class="btn sk-clear" type="button" ${mine ? "" : "disabled"}>Clear
          ${leg}</button>
      </div>
      <div class="sk-bar">
        <span class="sk-cols">${pal.map(c =>
          `<button class="sk-sw${c === opt.colour ? " on" : ""}" data-col="${c}"
            type="button" style="--c:${c}" title="${c}"></button>`).join("")}</span>
        <span class="grow"></span>
        <span class="sk-ws">${wds.map(w =>
          `<button class="sk-w${+w === +opt.w ? " on" : ""}" data-w="${w}" type="button"
            title="${w} px"><i style="height:${Math.max(2, w)}px"></i></button>`)
          .join("")}</span>
      </div>
      <small class="muted sk-hint">${mine} stroke${mine === 1 ? "" : "s"} on ${leg}${
        total > mine ? `, ${total} in all` : ""} — ink, nothing else. It is stored in
        chart units so it stays on the corridor when the axes move, and
        <b>nothing reads it</b>: no stroke is ever turned into a walking point.</small>`;
    wire(host, leg);
  }

  function wire(host, leg) {
    const all = (s) => host.querySelectorAll(s);
    const q = (s) => host.querySelector(s);
    const repaint = () => { sig = null; render(lastState, lastLeg); };

    all("[data-tool]").forEach(b => b.addEventListener("click", () => {
      opt.tool = b.dataset.tool;
      cancel();
      save();
      repaint();
    }));
    all(".sk-sw").forEach(b => b.addEventListener("click", () => {
      opt.colour = b.dataset.col;
      save();
      repaint();
    }));
    all(".sk-w").forEach(b => b.addEventListener("click", () => {
      opt.w = +b.dataset.w;
      save();
      repaint();
    }));
    const u = q(".sk-undo");
    if (u) u.addEventListener("click", () => RD.send({ type: "sketch_undo", leg }));
    const c = q(".sk-clear");
    if (c) c.addEventListener("click", () => {
      if (!window.confirm(`Rub out every stroke on ${leg}?`)) return;
      RD.send({ type: "sketch_clear", leg });
    });
  }

  return { render, overlay, livePath, start, move, end, cancel, eraseAt, tool };
})();
