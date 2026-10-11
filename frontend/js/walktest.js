window.WT = (function () {
  const el = (id) => document.getElementById(id);
  const LEGS = ["FR", "FL", "BR", "BL"];
  const PHASE = { FL: 0.00, BR: 0.25, FR: 0.50, BL: 0.75 };

  let state = null;
  let wired = false;
  let leg = "FR";
  let all = false;
  let idx = 0;
  let timer = null;
  let period = 1.6;
  let note = "";

  const running = () => timer !== null;

  function pointsOf(id) {
    if (!window.PTS || !state) return [];
    const rep = (state.legs || {})[id];
    if (!rep) return [];
    const out = [];
    PTS.pointsFor(state, id).forEach(p => {
      const knee = PTS.kneeAt(rep, p.thigh, p.k);
      if (knee == null) return;
      out.push({ i: p.i, thigh: Math.round(p.thigh), knee: Math.round(knee) });
    });
    return out;
  }

  function sendPoint(id, n) {
    const pts = pointsOf(id);
    if (!pts.length) return null;
    const p = pts[((n % pts.length) + pts.length) % pts.length];
    RD.send({ type: "leg_pair", leg: id, thigh: p.thigh, knee: p.knee });
    return p;
  }

  function step(delta) {
    const pts = pointsOf(leg);
    const n = (all ? Math.max(...LEGS.map(l => pointsOf(l).length || 0)) : pts.length) || 1;
    idx = ((idx + delta) % n + n) % n;
    if (!all) {
      sendPoint(leg, idx);
    } else {
      LEGS.forEach(l => {
        const len = pointsOf(l).length;
        if (len) sendPoint(l, idx + Math.round(PHASE[l] * len));
      });
    }
    paint();
  }

  function start() {
    if (running()) return;
    const n = Math.max(...LEGS.map(l => pointsOf(l).length || 0));
    if (!n) { note = "no points to walk"; paint(); return; }
    note = "";
    RD.hold(stop);
    const interval = Math.max(60, (period * 1000) / n);
    timer = setInterval(() => {
      if (!RD.isConnected() || (state && state.estop)) { stop(); return; }
      step(1);
    }, interval);
    paint();
  }

  function stop() {
    if (timer !== null) clearInterval(timer);
    timer = null;
    RD.release(stop);
    paint();
  }

  let sig = null;
  function paint() {
    const host = el("wt-panel");
    if (!host) return;
    const pts = pointsOf(leg);
    const n = (all ? Math.max(...LEGS.map(l => pointsOf(l).length || 0)) : pts.length) || 0;
    const relaxed = LEGS.filter(l => {
      const r = (state && (state.legs || {})[l]) || {};
      return r.relaxed;
    });
    const s = [leg, all, idx, n, running(), period, note, relaxed.join(",")].join("|");
    if (s === sig) return;
    sig = s;
    const cur = n ? ((idx % n) + n) % n : 0;
    const at = pts.length ? pts[((cur % pts.length) + pts.length) % pts.length] : null;
    host.innerHTML = `
      <div class="legbar">
        <div class="seg wt-seg" id="wt-legs">${
          LEGS.map(l => `<button class="mbtn${!all && l === leg ? " active" : ""}"
            data-wl="${l}" type="button">${l}</button>`).join("")}
          <button class="mbtn${all ? " active" : ""}" data-wl="ALL"
            type="button">All four</button></div>
      </div>
      <div class="stepbar">
        <button id="wt-prev" class="btn stepbtn" type="button"${
          running() ? " disabled" : ""}>◀</button>
        <span class="mono stepcount">${n ? (cur + 1) + " / " + n : "—"}</span>
        <button id="wt-next" class="btn stepbtn" type="button"${
          running() ? " disabled" : ""}>▶</button>
        <button id="wt-run" class="btn${running() ? " wt-stop" : ""}" type="button">${
          running() ? "Stop" : "Run the loop"}</button>
      </div>
      <label class="vslider"><span>Loop time</span>
        <input type="range" id="wt-period" min="0.6" max="8" step="0.1" value="${period}"/>
        <span class="setval mono">${period.toFixed(1)} s</span></label>
      ${at && !all ? `<p class="small muted">Sending <b class="mono">${leg}</b> to
        <b class="mono">${at.thigh} / ${at.knee} µs</b> — the same
        <b class="mono">leg_pair</b> the chart's dot sends, through the same corridor and
        the same speed limit.</p>` : ""}
      ${all ? `<p class="small muted">All four, offset by the crawl's phase table —
        ${LEGS.map(l => `${l} ${Math.round(PHASE[l] * 100)}%`).join(", ")}. Each leg walks
        its OWN stored points.</p>` : ""}
      ${relaxed.length ? `<p class="note warn">${relaxed.join(", ")} ${
        relaxed.length === 1 ? "is" : "are"} relaxed and will not move — a limp leg
        ignores position commands by design. Engage ${
        relaxed.length === 1 ? "it" : "them"} above first.</p>` : ""}
      ${note ? `<p class="note warn">${note}</p>` : ""}
      <p class="small muted"><b>This moves the robot.</b> The loop runs in this browser,
      so closing the tab, the E-STOP, or losing the connection all stop it. Step it by
      hand first — a point that puts a foot through the floor is much easier to see
      standing still.</p>`;

    const on = (id, ev, fn) => { const q = el(id); if (q) q.addEventListener(ev, fn); };
    host.querySelectorAll("[data-wl]").forEach(b => b.addEventListener("click", () => {
      if (b.dataset.wl === "ALL") { all = true; } else { all = false; leg = b.dataset.wl; }
      idx = 0;
      sig = null;
      paint();
    }));
    on("wt-prev", "click", () => step(-1));
    on("wt-next", "click", () => step(1));
    on("wt-run", "click", () => (running() ? stop() : start()));
    on("wt-period", "input", () => {
      period = +el("wt-period").value;
      if (running()) { stop(); start(); }
      sig = null;
      paint();
    });
  }

  function render(s) {
    state = s;
    if (!wired) { wired = true; }
    if (running() && s && s.estop) stop();
    paint();
  }

  return { render, stop };
})();
