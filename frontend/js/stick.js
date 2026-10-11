window.STICK = (function () {
  const DEAD = 0.08;

  function shape(v) {
    const a = Math.abs(v);
    if (a < DEAD) return 0;
    const u = (a - DEAD) / (1 - DEAD);
    return (v < 0 ? -1 : 1) * u * u;
  }

  const all = [];

  let dragging = null;
  window.addEventListener("pointermove", (ev) => {
    if (dragging) dragging._at(ev);
  });
  ["pointerup", "pointercancel"].forEach(e =>
    window.addEventListener(e, () => {
      if (dragging) { const d = dragging; dragging = null; d.centre(); }
    }));

  function make(host, onChange) {
    if (!host || host.dataset.wired) return null;
    host.dataset.wired = "1";
    host.innerHTML =
      '<div class="jsring"><div class="jscross"></div><div class="jsknob"></div></div>';
    const ring = host.querySelector(".jsring");
    const knob = host.querySelector(".jsknob");

    const S = {
      raw: { x: 0, y: 0 },
      get x() { return shape(S.raw.x); },
      get y() { return shape(S.raw.y); },
      get live() { return !!(shape(S.raw.x) || shape(S.raw.y)); },
      centre, paint, ring, knob, host,
    };

    function paint() {
      const r = ring.getBoundingClientRect();
      const rad = (r.width || 160) / 2;
      knob.style.transform =
        `translate(${S.raw.x * rad * 0.62}px, ${-S.raw.y * rad * 0.62}px)`;
      knob.classList.toggle("live", S.live);
      if (onChange) onChange(S);
    }

    function centre() {
      S.raw.x = S.raw.y = 0;
      if (dragging === S) dragging = null;
      paint();
    }

    S._at = (ev) => {
      const r = ring.getBoundingClientRect();
      const rad = (r.width || 160) / 2;
      let x = (ev.clientX - r.left - rad) / rad;
      let y = (ev.clientY - r.top - rad) / rad;
      const m = Math.hypot(x, y);
      if (m > 1) { x /= m; y /= m; }
      S.raw.x = x;
      S.raw.y = -y;
      paint();
    };

    ring.addEventListener("pointerdown", (ev) => {
      dragging = S;
      ev.preventDefault();
      S._at(ev);
    });

    all.push(S);
    paint();
    return S;
  }

  const centreAll = () => all.forEach(s => s.centre());
  const repaintAll = () => all.forEach(s => s.paint());
  window.addEventListener("blur", centreAll);
  window.addEventListener("resize", repaintAll);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) centreAll();
  });

  return { make, shape, centreAll, repaintAll, DEAD };
})();
