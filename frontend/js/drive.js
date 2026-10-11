window.DRV = (function () {
  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let state = null;
  let wired = false;

  const sticks = [];
  const makeStick = (host) => {
    const s = STICK.make(host, readout);
    if (s) sticks.push(s);
    return s;
  };

  function command() {
    const S = sticks.find(s => s.live) || sticks[0] || { x: 0, y: 0 };
    const fwd = S.y, turn = S.x;
    const o = (window.SIM && SIM.gaitOpts) ? SIM.gaitOpts() : null;
    if (!o || !o.period) return { fwd, turn, mms: 0, degs: 0, o: null };
    const top = o.stride / o.period;
    const TRACK = 78.0;
    const topTurn = (2 * top) / (Math.PI * TRACK) * 360;
    return { fwd, turn, mms: fwd * top, degs: turn * topTurn, o, top, topTurn };
  }

  function readout() {
    const c = command();
    const still = !c.fwd && !c.turn;
    const txt = !c.o
      ? '<span class="muted">waiting for the Simulator\'s gait numbers…</span>'
      : still
      ? '<span class="muted">centred — <b class="mono">0 mm/s</b></span>'
      : `${c.mms >= 0 ? "forward" : "reverse"} <b class="mono">${
          Math.abs(c.mms).toFixed(0)} mm/s</b> · turn <b class="mono">${
          Math.abs(c.degs).toFixed(0)}°/s</b> ${c.degs > 0 ? "right" : c.degs < 0 ? "left" : ""}`;
    const sub = c.o
      ? `flat out this gait is <b class="mono">${c.top.toFixed(0)} mm/s</b> — ${
          c.o.stride} mm of stride once every ${c.o.period.toFixed(2)} s. Change either
          on the Simulator tab and this follows.`
      : "";
    [el("drv-read"), el("fs-read")].forEach(n => { if (n) n.innerHTML = txt; });
    [el("drv-read-sub"), el("fs-read-sub")].forEach(n => { if (n) n.innerHTML = sub; });
  }

  let actSig = null;
  function drawActions() {
    const rows = (state || {}).actions || [];
    const next = rows.map(a => a.id + ":" + a.name).join("|");
    if (next === actSig) return;
    actSig = next;
    const html = rows.length
      ? rows.map(a => `<button class="btn drv-act" data-run="${a.id}" type="button">${
          esc(a.name)}</button>`).join("")
      : '<span class="muted small">no recorded actions — record one on the Calibration'
        + ' tab and it appears here.</span>';
    ["drv-actions", "fs-actions"].forEach(id => {
      const n = el(id);
      if (!n) return;
      n.innerHTML = html;
      n.querySelectorAll("[data-run]").forEach(b => b.addEventListener("click", () => {
        RD.send({ type: "action_run", id: +b.dataset.run });
      }));
    });
  }

  let quadSig = null;
  function drawQuads() {
    const host = el("drv-legs");
    if (!host || !window.CAL || !CAL.quadSVG) return;
    const legs = (CAL.LEG_QUAD || []).filter(l => ((state || {}).legs || {})[l]);
    const sig = legs.join(",");
    if (sig !== quadSig) {
      quadSig = sig;
      host.innerHTML = legs.map(l =>
        `<div class="cq" data-leg="${l}">
          <div class="cq-h"><b>${esc((CAL.LEG_NAMES || {})[l] || l)}</b>
            <span class="grow"></span>
            <span class="legstate cq-st" data-st="${l}">--</span></div>
          <div class="cq-c" data-c="${l}"></div>
        </div>`).join("");
    }
    legs.forEach(l => {
      const box = host.querySelector(`[data-c="${l}"]`);
      if (box) box.innerHTML = CAL.quadSVG(state, l, Math.max(200, box.clientWidth || 280));
      const st = host.querySelector(`[data-st="${l}"]`);
      const pair = CAL.legPair(state, l);
      if (st && pair) {
        const bad = pair.thigh && pair.knee &&
          (pair.thigh.outside || pair.knee.outside);
        st.textContent = !pair.rep.ok ? "not measured" : bad ? "outside" : "in range";
        st.className = "legstate cq-st " + (!pair.rep.ok || bad ? "bad" : "ok");
      }
    });
  }

  let camHome = null;
  function openFull() {
    const wrap = el("fs-cam"), cam = el("cam");
    if (!wrap || !cam) return;
    camHome = cam.parentNode;
    wrap.appendChild(cam);
    el("fullscreen").classList.remove("hidden");
    document.body.classList.add("fs-open");
    const n = el("fullscreen");
    if (n.requestFullscreen) n.requestFullscreen().catch(() => {});
    actSig = null;
    drawActions();
    sticks.forEach(s => s.paint());
  }

  function closeFull() {
    const cam = el("cam");
    if (camHome && cam) camHome.insertBefore(cam, camHome.firstChild);
    camHome = null;
    el("fullscreen").classList.add("hidden");
    document.body.classList.remove("fs-open");
    if (document.fullscreenElement && document.exitFullscreen)
      document.exitFullscreen().catch(() => {});
    sticks.forEach(s => s.paint());
  }

  function wire() {
    wired = true;
    makeStick(el("drv-stick"));
    makeStick(el("fs-stick"));
    const open = el("drv-full"), open2 = el("cam-full");
    [open, open2].forEach(b => b && b.addEventListener("click", openFull));
    const close = el("fs-close");
    if (close) close.addEventListener("click", closeFull);
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape" && !el("fullscreen").classList.contains("hidden"))
        closeFull();
    });
    document.addEventListener("fullscreenchange", () => {
      if (!document.fullscreenElement && !el("fullscreen").classList.contains("hidden"))
        closeFull();
    });
    const stop = el("fs-estop");
    if (stop) stop.addEventListener("click", () => el("estop").click());
  }

  function render(s) {
    state = s;
    if (!wired) wire();
    drawActions();
    const panel = el("tab-drive");
    if (panel && panel.classList.contains("active")) drawQuads();
    const b = el("fs-estop");
    if (b) {
      const on = !!s.estop;
      b.textContent = on ? "UNLOCK" : "E-STOP";
      b.className = "estop" + (on ? " unlock" : "");
    }
    const dot = el("fs-conn");
    if (dot) dot.className = "dot " + (RD.isConnected() ? "on" : "off");
    readout();
  }

  return { render, openFull, closeFull };
})();
