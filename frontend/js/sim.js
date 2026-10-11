window.SIM = (function () {
  const el = (id) => document.getElementById(id);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
  const D = 180 / Math.PI;

  let GEO = null;
  const FALLBACK_GEO = { l_upper: 107, l_lower: 138, body_length: 230,
                         body_width: 78, base_height: 150 };
  const legGeo = () => (GEO && GEO.leg) || FALLBACK_GEO;

  fetch("api/geometry").then(r => r.json()).then(j => {
    if (!j || !j.leg) return;
    GEO = j;
    standBandCache = null;
    arcCache = {};
    const b = standBand();
    if (b && (P.stand < b[0] || P.stand > b[1])) {
      P.stand = Math.round((b[0] + b[1]) / 2 + (b[1] - b[0]) * 0.15);
      LEGS.forEach(L => { if (!ikTarget[L.id].moved) ikTarget[L.id] = { x: 0, y: P.stand }; });
      save();
    }
  }).catch(() => { });

  function interp(x, pts, xi, yi) {
    if (!pts || pts.length < 2) return null;
    let a = null, b = null;
    if (x <= pts[0][xi]) { a = pts[0]; b = pts[1]; }
    else if (x >= pts[pts.length - 1][xi]) { a = pts[pts.length - 2]; b = pts[pts.length - 1]; }
    else {
      for (let i = 1; i < pts.length; i++) {
        if (x <= pts[i][xi]) { a = pts[i - 1]; b = pts[i]; break; }
      }
    }
    if (!a || !b || Math.abs(b[xi] - a[xi]) < 1e-12) return pts[0][yi];
    return a[yi] + (x - a[xi]) / (b[xi] - a[xi]) * (b[yi] - a[yi]);
  }

  const angleCache = {};
  function anglePts(legId, joint) {
    const key = legId + "|" + joint;
    if (angleCache[key] !== undefined) return angleCache[key];
    const rec = GEO && GEO.angles && GEO.angles[key];
    const pts = rec && rec.points && rec.points.length >= 2
      ? rec.points.slice().sort((p, q) => p[0] - q[0]) : null;
    if (GEO) angleCache[key] = pts;
    return pts;
  }
  const provisional = (legId) => {
    const a = GEO && GEO.angles;
    return !!(a && ((a[legId + "|thigh"] || {}).provisional ||
                    (a[legId + "|knee"] || {}).provisional));
  };

  const poseFeet = () => {
    if (!GEO || !GEO.poses) return [];
    const L1 = femur(), L2 = tibia();
    return GEO.poses.map(p => {
      const feet = {};
      LEGS.forEach(L => {
        const r = (p.legs || {})[L.id];
        if (!r) return;
        const th = usToDeg(L.id, "thigh", r.thigh), kn = usToDeg(L.id, "knee", r.knee);
        if (th == null || kn == null) return;
        const f = forward(th, clamp(kn, 1, 179), L1, L2, KNEE_BACK);
        feet[L.id] = { x: f.fx, y: f.fy, thigh: th, knee: kn };
      });
      return { name: p.name, feet };
    }).filter(p => Object.keys(p.feet).length);
  };

  let standBandCache = null;
  function standBand() {
    if (standBandCache) return standBandCache;
    const ys = poseFeet().flatMap(p => Object.values(p.feet).map(f => f.y));
    if (ys.length < 2) return null;
    standBandCache = [Math.floor(Math.min.apply(null, ys)),
                      Math.ceil(Math.max.apply(null, ys))];
    return standBandCache;
  }

  const legLen = (kneeDeg) => {
    const a = femur(), b = tibia();
    return Math.sqrt(a * a + b * b - 2 * a * b * Math.cos(kneeDeg / D));
  };

  function reachOf(legId) {
    const rep = ((state || {}).legs || {})[legId];
    if (!rep || !rep.safe_band) return null;
    let kMin = Infinity, kMax = -Infinity;
    (rep.safe_band || []).forEach(run => (run || []).forEach(node => {
      [node[1], node[2]].forEach(us => {
        const a = usToDeg(legId, "knee", us);
        if (a == null) return;
        if (a < kMin) kMin = a;
        if (a > kMax) kMax = a;
      });
    }));
    if (!isFinite(kMin) || !isFinite(kMax)) return null;
    return { kMin, kMax, dMin: legLen(kMin), dMax: legLen(kMax) };
  }

  function tightestLeg() {
    let worst = null;
    LEGS.forEach(L => {
      const r = reachOf(L.id);
      if (r && (!worst || r.dMin > worst.dMin)) worst = Object.assign({ id: L.id }, r);
    });
    return worst;
  }

  function liftAt(x, worst) {
    const w = worst || tightestLeg();
    if (!w) return null;
    const d = Math.hypot(x, P.stand);
    if (w.dMin >= d) return 0;
    return P.stand - Math.sqrt(Math.max(0, w.dMin * w.dMin - x * x));
  }

  const usToDeg = (legId, joint, us) => interp(us, anglePts(legId, joint), 0, 1);
  const degToUs = (legId, joint, deg) => {
    const pts = anglePts(legId, joint);
    if (!pts) return null;
    const byDeg = pts.slice().sort((p, q) => p[1] - q[1]);
    const us = interp(deg, byDeg, 1, 0);
    return us == null ? null : Math.round(us);
  };

  const LEGS = [
    { id: "FL", name: "Front-Left",  front: 1, side: -1 },
    { id: "FR", name: "Front-Right", front: 1, side:  1 },
    { id: "BL", name: "Back-Left",   front: 0, side: -1 },
    { id: "BR", name: "Back-Right",  front: 0, side:  1 },
  ];

  const GAITS = {
    walk:  { label: "Crawl", duty: 0.75, ph: { FL: 0.00, BR: 0.25, FR: 0.50, BL: 0.75 } },
    trot:  { label: "Trot",  duty: 0.50, ph: { FL: 0.00, FR: 0.50, BL: 0.50, BR: 0.00 } },
    pace:  { label: "Pace",  duty: 0.50, ph: { FL: 0.00, BL: 0.00, FR: 0.50, BR: 0.50 } },
    bound: { label: "Bound", duty: 0.55, ph: { FL: 0.00, FR: 0.00, BL: 0.50, BR: 0.50 } },
  };

  const KEY = "suki.sim";
  const P = {
    gait: "walk", period: 1.6, stride: 44, clear: 6, duty: 0.75,
    stand: 180, centre: -32, ghost: true,
    ptsLeg: "FR", ptsMode: "step",
    driveMode: "stick", auto: "wander", trail: true,
  };
  try { Object.assign(P, JSON.parse(localStorage.getItem(KEY) || "{}")); } catch (e) { }
  const save = () => {
    try { localStorage.setItem(KEY, JSON.stringify(P)); } catch (e) { }
  };
  const femur = () => legGeo().l_upper;
  const tibia = () => legGeo().l_lower;
  const bodyLen = () => legGeo().body_length;
  const bodyWid = () => legGeo().body_width;
  const KNEE_BACK = true;

  const SLIDERS = {
    "sim-sliders-gait": [
      ["period", "Cycle", 0.4, 4, 0.05, v => v.toFixed(2) + " s"],
      ["stride", "Step length", 0, 100, 1, v => v + " mm"],
      ["clear", "Step height", 0, 40, 1, v => v + " mm"],
      ["centre", "Stance centre", -80, 20, 1, v => (v > 0 ? "+" : "") + v + " mm"],
      ["duty", "On the ground", 0.3, 0.95, 0.01, v => Math.round(v * 100) + "%"],
      ["stand", "Stand height", 60, 230, 1, v => v + " mm"],
    ],
  };

  let mode = "gait";
  let playing = true;
  let cycle = 0;
  let lastTs = 0;
  let state = null;
  let wired = false;
  let ikDrag = null;
  const ikTarget = {};
  LEGS.forEach(L => (ikTarget[L.id] = { x: 0, y: P.stand }));
  let ptsCycle = 0;

  function solve(fx, fy, L1, L2, back) {
    let d = Math.hypot(fx, fy);
    const dmax = L1 + L2 - 1e-3, dmin = Math.abs(L1 - L2) + 1e-3;
    let reach = "";
    if (d < 1e-6) { fx = 0; fy = dmin; d = dmin; reach = "too close"; }
    else if (d > dmax) { const s = dmax / d; fx *= s; fy *= s; d = dmax; reach = "out of reach"; }
    else if (d < dmin) { const s = dmin / d; fx *= s; fy *= s; d = dmin; reach = "too close"; }
    const a = (L1 * L1 - L2 * L2 + d * d) / (2 * d);
    const h = Math.sqrt(Math.max(0, L1 * L1 - a * a));
    const ux = fx / d, uy = fy / d;
    const s = back ? 1 : -1;
    const kx = ux * a + s * h * -uy, ky = uy * a + s * h * ux;
    const thigh = Math.atan2(kx, ky) * D;
    const v1x = -kx, v1y = -ky, v2x = fx - kx, v2y = fy - ky;
    const knee = Math.acos(clamp((v1x * v2x + v1y * v2y) /
      (Math.hypot(v1x, v1y) * Math.hypot(v2x, v2y) || 1), -1, 1)) * D;
    return { fx, fy, kx, ky, thigh, knee, reach };
  }

  function forward(thighDeg, kneeDeg, L1, L2, back) {
    const t = thighDeg / D;
    const kx = L1 * Math.sin(t), ky = L1 * Math.cos(t);
    const r = (back ? 1 : -1) * (kneeDeg / D);
    const bx = -Math.sin(t), by = -Math.cos(t);
    const dx = bx * Math.cos(r) - by * Math.sin(r);
    const dy = bx * Math.sin(r) + by * Math.cos(r);
    return { fx: kx + L2 * dx, fy: ky + L2 * dy, kx, ky,
             thigh: thighDeg, knee: kneeDeg, reach: "" };
  }

  let arcCache = {};
  function measuredArc(legId) {
    if (arcCache[legId]) return arcCache[legId];
    const t = angleSpan(legId, "thigh"), k = angleSpan(legId, "knee");
    if (!t || !k) return null;
    const L1 = femur(), L2 = tibia(), N = 22, out = [];
    const at = (th, kn) => {
      const f = forward(th, clamp(kn, 1, 179), L1, L2, KNEE_BACK);
      out.push({ x: f.fx, y: f.fy });
    };
    for (let i = 0; i <= N; i++) at(t[0] + (t[1] - t[0]) * i / N, k[0]);
    for (let i = 1; i <= N; i++) at(t[1], k[0] + (k[1] - k[0]) * i / N);
    for (let i = 1; i <= N; i++) at(t[1] - (t[1] - t[0]) * i / N, k[1]);
    for (let i = 1; i < N; i++) at(t[0], k[1] - (k[1] - k[0]) * i / N);
    if (GEO) arcCache[legId] = out;
    return out;
  }

  function inArc(legId, thighDeg, kneeDeg) {
    const t = angleSpan(legId, "thigh"), k = angleSpan(legId, "knee");
    if (!t || !k) return true;
    return thighDeg >= t[0] - 0.01 && thighDeg <= t[1] + 0.01 &&
           kneeDeg >= k[0] - 0.01 && kneeDeg <= k[1] + 0.01;
  }

  const BEZ_N = 11;
  const BEZ_C = (() => {
    const f = (n) => { let r = 1; for (let i = 2; i <= n; i++) r *= i; return r; };
    return Array.from({ length: 12 }, (_, i) => f(BEZ_N) / (f(i) * f(BEZ_N - i)));
  })();

  function swingCP(span, clear) {
    const xs = span / 100;
    return [
      [-span, 0], [-span - 0.805 * xs, 0], [-span - xs, -clear],
      [-span - xs, -clear], [-span - xs, -clear],
      [0, -clear], [0, -clear], [0, -clear * 1.29],
      [span + 1.032 * xs, -clear * 1.29], [span + 1.032 * xs, -clear * 1.29],
      [span + 0.826 * xs, 0], [span, 0],
    ];
  }

  function bezier(cp, t) {
    let x = 0, y = 0;
    for (let i = 0; i < cp.length; i++) {
      const b = BEZ_C[i] * Math.pow(1 - t, BEZ_N - i) * Math.pow(t, i);
      x += b * cp[i][0];
      y += b * cp[i][1];
    }
    return [x, y];
  }

  const AUTO = {
    wander: { label: "Wander",
              fn: t => ({ fwd: 0.6 + 0.3 * Math.sin(t * 0.31),
                          turn: 0.75 * Math.sin(t * 0.17) * Math.cos(t * 0.071) }) },
    circle: { label: "Circle", fn: () => ({ fwd: 0.85, turn: 0.45 }) },
    weave:  { label: "Weave",  fn: t => ({ fwd: 0.85, turn: 0.7 * Math.sin(t * 0.35) }) },
    spin:   { label: "Spin",   fn: () => ({ fwd: 0, turn: 0.9 }) },
  };
  let autoT = 0;

  let stick = null;
  function driveCmd() {
    if (P.driveMode === "auto") {
      const A = AUTO[P.auto] || AUTO.wander;
      const c = A.fn(autoT);
      return { fwd: clamp(c.fwd, -1, 1), turn: clamp(c.turn, -1, 1) };
    }
    if (P.driveMode === "stick" && stick) return { fwd: stick.y, turn: stick.x };
    return { fwd: 1, turn: 0 };
  }

  function legMix(legId) {
    const c = driveCmd();
    const L = LEGS.find(l => l.id === legId);
    return clamp(c.fwd - c.turn * (L ? L.side : 1), -1, 1);
  }

  const world = { x: 0, y: 0, th: 0, dist: 0, trail: [] };
  const TRAIL_MM = 6;
  const TRAIL_MAX = 500;

  function footAt(legId, c, mix) {
    const G = GAITS[P.gait] || GAITS.walk;
    const duty = clamp(P.duty, 0.05, 0.98);
    const p = ((c + (G.ph[legId] || 0)) % 1 + 1) % 1;
    const stride = P.stride * (mix == null ? 1 : mix);
    const half = stride / 2;
    if (p < duty) {
      const u = p / duty;
      return { x: P.centre + half - u * stride, y: P.stand, stance: true, p };
    }
    const u = (p - duty) / (1 - duty);
    const [bx, by] = bezier(swingCP(half, P.clear), u);
    return { x: P.centre + bx, y: P.stand + by, stance: false, p };
  }

  function livePose(legId) {
    const rep = ((state || {}).legs || {})[legId];
    if (!rep) return null;
    const rows = {};
    (state.servos || []).forEach(r => (rows[r.ch] = r));
    const t = rows[rep.thigh_ch], k = rows[rep.knee_ch];
    if (!t || !k) return null;
    const th = usToDeg(legId, "thigh", t.us), kn = usToDeg(legId, "knee", k.us);
    if (th == null || kn == null) return null;
    return { thigh: th, knee: clamp(kn, 1, 179), us: [t.us, k.us] };
  }

  function gaitPoints(legId, n) {
    if (!GEO) return [];
    const L1 = femur(), L2 = tibia();
    const N = Math.max(8, Math.min(120, n || 48));
    const out = [];
    for (let i = 0; i < N; i++) {
      const f = footAt(legId, i / N);
      const sol = solve(f.x, f.y, L1, L2, KNEE_BACK);
      let t = degToUs(legId, "thigh", sol.thigh);
      let k = degToUs(legId, "knee", sol.knee);
      if (t == null || k == null) return [];
      const over = t < 500 || t > 2500 || k < 500 || k > 2500;
      t = clamp(t, 500, 2500);
      k = clamp(k, 500, 2500);
      out.push({ thigh: t, knee: k, stance: f.stance, p: f.p,
                 degThigh: sol.thigh, degKnee: sol.knee,
                 unverified: !inArc(legId, sol.thigh, sol.knee),
                 reach: !!sol.reach, over, i });
    }
    return out;
  }

  function gaitLabel() {
    const G = GAITS[P.gait] || GAITS.walk;
    return `${G.label} · ${P.stride} mm step · ${P.clear} mm lift · ${
      Math.round(P.duty * 100)}% down · ${P.stand} mm stand · stance ${
      P.centre > 0 ? "+" : ""}${P.centre} mm`;
  }

  function taughtPath(legId) {
    if (!window.PTS || !state) return [];
    const rep = (state.legs || {})[legId];
    if (!rep) return [];
    const out = [];
    PTS.pointsFor(state, legId).forEach(p => {
      const knee = PTS.kneeAt(rep, p.thigh, p.k);
      if (knee == null) return;
      const th = usToDeg(legId, "thigh", p.thigh);
      const kn = usToDeg(legId, "knee", knee);
      if (th == null || kn == null) return;
      const f = forward(th, clamp(kn, 1, 179), femur(), tibia(), KNEE_BACK);
      out.push({ i: p.i, dwell: p.dwell, thigh: th, knee: kn,
                 us: [p.thigh, Math.round(knee)], fx: f.fx, fy: f.fy });
    });
    return out;
  }

  function pointPose(legId, c) {
    const path = taughtPath(legId);
    if (path.length < 2) return null;
    const seg = path.map(p => 1 + (p.dwell || 0) * 2);
    const total = seg.reduce((a, b) => a + b, 0);
    let u = (((c % 1) + 1) % 1) * total;
    for (let i = 0; i < path.length; i++) {
      if (u <= seg[i]) {
        const a = path[i], b = path[(i + 1) % path.length];
        const t = clamp(u / seg[i], 0, 1);
        return { thigh: a.thigh + (b.thigh - a.thigh) * t,
                 knee: a.knee + (b.knee - a.knee) * t,
                 us: a.us, index: i, path };
      }
      u -= seg[i];
    }
    return { thigh: path[0].thigh, knee: path[0].knee, us: path[0].us,
             index: 0, path };
  }

  let ptsIndex = 0;
  const ptsPathLen = (legId) => taughtPath(legId).length;

  function ptsStep(delta) {
    const n = ptsPathLen(P.ptsLeg) || 1;
    ptsIndex = ((ptsIndex + delta) % n + n) % n;
  }

  function pointAt(legId, i) {
    const path = taughtPath(legId);
    if (!path.length) return null;
    const p = path[((i % path.length) + path.length) % path.length];
    return { thigh: p.thigh, knee: p.knee, us: p.us, index: p.i, path };
  }

  function toUs(legId, thighDeg, kneeDeg) {
    const a = degToUs(legId, "thigh", thighDeg);
    const b = degToUs(legId, "knee", kneeDeg);
    if (a == null || b == null) return null;
    return [clamp(a, 500, 2500), clamp(b, 500, 2500)];
  }

  function pose() {
    const L1 = femur(), L2 = tibia(), half = bodyLen() / 2;
    return LEGS.map(L => {
      const hipX = (L.front ? 1 : -1) * half;
      let target, stance = true, p = 0, sol;
      if (mode === "live") {
        const lp = livePose(L.id);
        if (lp) {
          sol = forward(lp.thigh, lp.knee, L1, L2, KNEE_BACK);
          sol.us = lp.us;
        } else {
          sol = solve(0, P.stand, L1, L2, KNEE_BACK);
          sol.missing = true;
        }
      } else if (mode === "points") {
        let pp;
        if (P.ptsMode === "walk") {
          const G = GAITS[P.gait] || GAITS.walk;
          pp = pointPose(L.id, ptsCycle + (G.ph[L.id] || 0));
        } else if (L.id === P.ptsLeg) {
          pp = pointAt(L.id, ptsIndex);
        } else {
          pp = pointAt(L.id, 0);
        }
        if (pp) {
          sol = forward(pp.thigh, pp.knee, L1, L2, KNEE_BACK);
          sol.us = pp.us;
          sol.path = pp.path;
          sol.ptIndex = pp.index;
        } else {
          sol = solve(0, P.stand, L1, L2, KNEE_BACK);
          sol.missing = true;
        }
      } else if (mode === "ik") {
        target = ikTarget[L.id];
        sol = solve(target.x, target.y, L1, L2, KNEE_BACK);
      } else {
        const f = footAt(L.id, cycle, legMix(L.id));
        stance = f.stance; p = f.p;
        sol = solve(f.x, f.y, L1, L2, KNEE_BACK);
      }
      sol.outside = !inArc(L.id, sol.thigh, sol.knee);
      return Object.assign({ leg: L, hipX, stance, p }, sol);
    });
  }

  function fit(c) {
    const dpr = window.devicePixelRatio || 1;
    const w = c.clientWidth, h = c.clientHeight;
    if (!w || !h) return null;
    if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) {
      c.width = Math.round(w * dpr);
      c.height = Math.round(h * dpr);
    }
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.clearRect(0, 0, w, h);
    return { g, w, h };
  }

  const CSS = (n) => getComputedStyle(document.documentElement)
    .getPropertyValue(n).trim() || "#fff";

  function roundRect(g, x, y, w, h, r) {
    g.beginPath();
    g.moveTo(x + r, y);
    g.arcTo(x + w, y, x + w, y + h, r);
    g.arcTo(x + w, y + h, x, y + h, r);
    g.arcTo(x, y + h, x, y, r);
    g.arcTo(x, y, x + w, y, r);
    g.closePath();
  }

  function drawSide(legs) {
    const c = el("sim-side");
    const F = fit(c);
    const geo = sideGeom(c);
    if (!F || !geo) return;
    const { g, w } = F;
    const { X, Y, s, gy } = geo;
    const cx = w / 2;

    g.strokeStyle = CSS("--line");
    g.lineWidth = 1;
    g.beginPath(); g.moveTo(0, gy); g.lineTo(w, gy); g.stroke();
    g.globalAlpha = 0.5;
    const roll = mode === "gait"
      ? ((world.dist * s) % 14 + 14) % 14 : 0;
    for (let x = (cx % 14) - 14 - roll; x < w + 14; x += 14) {
      g.beginPath(); g.moveTo(x, gy); g.lineTo(x - 6, gy + 7); g.stroke();
    }
    g.globalAlpha = 1;

    legs.filter(L => L.leg.side > 0).forEach(L => {
      const arc = measuredArc(L.leg.id);
      if (!arc || arc.length < 4) return;
      g.beginPath();
      arc.forEach((p, i) => {
        const px = X(L.hipX + p.x), py = Y(P.stand - p.y);
        if (i) g.lineTo(px, py); else g.moveTo(px, py);
      });
      g.closePath();
      g.fillStyle = "rgba(54,211,153,.10)";
      g.strokeStyle = CSS("--good");
      g.globalAlpha = 0.45;
      g.lineWidth = 1;
      g.setLineDash([2, 3]);
      g.fill(); g.stroke();
      g.setLineDash([]);
      g.globalAlpha = 1;
    });

    poseFeet().forEach((pp, i, all) => {
      legs.filter(L => L.leg.side > 0).forEach(L => {
        const f = pp.feet[L.leg.id];
        if (!f) return;
        const px = X(L.hipX + f.x), py = Y(P.stand - f.y);
        g.globalAlpha = 0.75;
        g.fillStyle = CSS("--good");
        g.beginPath(); g.arc(px, py, 2.5, 0, 7); g.fill();
        if (i === 0 || i === all.length - 1) {
          g.globalAlpha = 0.6;
          g.fillStyle = CSS("--muted");
          g.font = "8px ui-monospace,Menlo,monospace";
          g.textAlign = i ? "left" : "right";
          g.fillText(pp.name, px + (i ? 5 : -5), py + 3);
        }
        g.globalAlpha = 1;
      });
    });

    if (P.ghost && mode === "gait") {
      g.globalAlpha = 0.55;
      g.lineWidth = 1.5;
      legs.filter(L => L.leg.side > 0).forEach(L => {
        const id = L.leg.id, mix = legMix(id);
        let prev = null;
        for (let i = 0; i <= 60; i++) {
          const f = footAt(id, i / 60, mix);
          const s = solve(f.x, f.y, femur(), tibia(), KNEE_BACK);
          const ok = !s.reach && inArc(id, s.thigh, s.knee);
          const px = X(L.hipX + f.x), py = Y(P.stand - f.y);
          if (prev) {
            g.strokeStyle = ok && prev.ok ? CSS("--accent") : CSS("--warn");
            g.setLineDash(ok && prev.ok ? [] : [3, 3]);
            g.beginPath(); g.moveTo(prev.px, prev.py); g.lineTo(px, py); g.stroke();
          }
          prev = { px, py, ok };
        }
      });
      g.setLineDash([]);
      g.globalAlpha = 1;
    }

    if (P.ghost && mode === "points") {
      legs.filter(L => L.leg.side > 0 ||
                       (P.ptsMode === "step" && L.leg.id === P.ptsLeg)).forEach(L => {
        const path = L.path;
        if (!path || path.length < 2) return;
        g.strokeStyle = CSS("--accent");
        g.globalAlpha = 0.4;
        g.setLineDash([4, 4]);
        g.lineWidth = 1.5;
        g.beginPath();
        path.forEach((p, i) => {
          const px = X(L.hipX + p.fx), py = Y(P.stand - p.fy);
          if (i) g.lineTo(px, py); else g.moveTo(px, py);
        });
        g.closePath();
        g.stroke();
        g.setLineDash([]);
        g.globalAlpha = 0.85;
        g.font = "9px system-ui, sans-serif";
        g.textAlign = "center";
        const onIt = P.ptsMode === "step" && L.leg.id === P.ptsLeg ? L.ptIndex : null;
        path.forEach(p => {
          const px = X(L.hipX + p.fx), py = Y(P.stand - p.fy);
          const cur = onIt != null && p.i === onIt;
          g.fillStyle = cur ? CSS("--accent") : CSS("--panel2");
          g.beginPath(); g.arc(px, py, cur ? 9 : 7, 0, 7); g.fill();
          g.strokeStyle = CSS("--accent");
          g.lineWidth = cur ? 2 : 1.4;
          g.stroke();
          g.fillStyle = cur ? CSS("--bg") : CSS("--text");
          g.fillText(String(p.i + 1), px, py + 3);
        });
        g.globalAlpha = 1;
      });
    }

    const paintLeg = (L, alpha) => {
      const hx = X(L.hipX), hy = Y(P.stand);
      const kx = X(L.hipX + L.kx), ky = Y(P.stand - L.ky);
      const fx = X(L.hipX + L.fx), fy = Y(P.stand - L.fy);
      const off = !L.reach && L.outside;
      g.globalAlpha = alpha;
      g.lineCap = "round";
      g.lineWidth = Math.max(4, 7 * s / 0.9);
      g.strokeStyle = L.reach ? CSS("--bad") : off ? CSS("--warn") : CSS("--accent2");
      g.beginPath(); g.moveTo(hx, hy); g.lineTo(kx, ky); g.stroke();
      g.strokeStyle = L.reach ? CSS("--bad") : off ? CSS("--warn") : CSS("--accent");
      g.beginPath(); g.moveTo(kx, ky); g.lineTo(fx, fy); g.stroke();
      g.fillStyle = CSS("--panel2");
      g.strokeStyle = CSS("--line");
      g.lineWidth = 1.5;
      g.beginPath(); g.arc(kx, ky, 5, 0, 7); g.fill(); g.stroke();
      g.fillStyle = L.stance ? CSS("--good") : CSS("--warn");
      g.beginPath(); g.arc(fx, fy, 6, 0, 7); g.fill();
      g.globalAlpha = 1;
    };

    legs.filter(L => L.leg.side < 0).forEach(L => paintLeg(L, 0.3));

    const BL = bodyLen();
    const bx = X(-BL / 2), bw = X(BL / 2) - X(-BL / 2);
    const bh = Math.max(12, 18 * s);
    g.fillStyle = CSS("--panel2");
    g.strokeStyle = CSS("--accent");
    g.lineWidth = 2;
    roundRect(g, bx, Y(P.stand) - bh / 2, bw, bh, Math.min(bh / 2, 12));
    g.fill(); g.stroke();
    g.fillStyle = CSS("--accent");
    g.beginPath();
    g.arc(X(BL / 2) + bh * 0.45, Y(P.stand) - bh * 0.55, bh * 0.42, 0, 7);
    g.fill();

    legs.filter(L => L.leg.side > 0).forEach(L => paintLeg(L, 1));

    g.strokeStyle = CSS("--muted");
    g.globalAlpha = 0.5;
    g.setLineDash([3, 3]);
    g.lineWidth = 1;
    g.beginPath(); g.moveTo(cx, Y(P.stand)); g.lineTo(cx, gy); g.stroke();
    g.setLineDash([]);
    g.globalAlpha = 1;
    g.fillStyle = CSS("--muted");
    g.font = "10px ui-monospace,Menlo,monospace";
    g.textAlign = "left";
    g.fillText(Math.round(P.stand) + " mm", cx + 5, (Y(P.stand) + gy) / 2);
    g.textAlign = "right";
    g.fillText("front →", w - 8, 14);
  }

  function hull(pts) {
    if (pts.length < 3) return pts.slice();
    const p = pts.slice().sort((a, b) => a.x - b.x || a.y - b.y);
    const cross = (o, a, b) =>
      (a.x - o.x) * (b.y - o.y) - (a.y - o.y) * (b.x - o.x);
    const lo = [], up = [];
    for (const q of p) {
      while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop();
      lo.push(q);
    }
    for (let i = p.length - 1; i >= 0; i--) {
      const q = p[i];
      while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop();
      up.push(q);
    }
    lo.pop(); up.pop();
    return lo.concat(up);
  }

  function inPoly(pt, poly) {
    if (poly.length < 3) return false;
    let sign = 0;
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length];
      const c = (b.x - a.x) * (pt.y - a.y) - (b.y - a.y) * (pt.x - a.x);
      if (Math.abs(c) < 1e-9) continue;
      const s = c > 0 ? 1 : -1;
      if (!sign) sign = s; else if (s !== sign) return false;
    }
    return true;
  }

  function drawTop(legs) {
    const F = fit(el("sim-top"));
    if (!F) return;
    const { g, w, h } = F;
    const BW = bodyWid(), BL = bodyLen();
    const spanX = BW + 80, spanY = BL + P.stride + 80;
    const s = Math.min(w * 0.85 / spanX, h * 0.88 / spanY);
    const cx = w / 2, cy = h / 2;
    const X = (lat) => cx + lat * s, Y = (fwd) => cy - fwd * s;

    const ct = Math.cos(world.th), st = Math.sin(world.th);
    const toBody = (wx, wy) => {
      const dx = wx - world.x, dy = wy - world.y;
      return [dx * ct - dy * st, dx * st + dy * ct];
    };

    if (mode === "gait") {
      const GRID = 60, reach = Math.max(spanX, spanY) * 0.9;
      const n = Math.ceil(reach / GRID);
      const gx = Math.round(world.x / GRID) * GRID, gy2 = Math.round(world.y / GRID) * GRID;
      g.fillStyle = CSS("--line");
      g.globalAlpha = 0.7;
      for (let i = -n; i <= n; i++) {
        for (let j = -n; j <= n; j++) {
          const [bx, by] = toBody(gx + i * GRID, gy2 + j * GRID);
          if (Math.abs(bx) > spanX / 2 + GRID || Math.abs(by) > spanY / 2 + GRID) continue;
          g.beginPath(); g.arc(X(bx), Y(by), 1.4, 0, 7); g.fill();
        }
      }
      g.globalAlpha = 1;

      if (P.trail && world.trail.length > 1) {
        g.strokeStyle = CSS("--accent2");
        g.globalAlpha = 0.55;
        g.lineWidth = 2;
        g.lineCap = "round";
        g.beginPath();
        world.trail.forEach((p, i) => {
          const [bx, by] = toBody(p[0], p[1]);
          if (i) g.lineTo(X(bx), Y(by)); else g.moveTo(X(bx), Y(by));
        });
        g.stroke();
        g.globalAlpha = 1;
      }
    }

    g.fillStyle = CSS("--panel2");
    g.strokeStyle = CSS("--accent");
    g.lineWidth = 2;
    roundRect(g, X(-BW / 2), Y(BL / 2),
      BW * s, BL * s, Math.min(BW * s / 3, 14));
    g.fill(); g.stroke();

    const feet = legs.map(L => ({
      x: X(L.leg.side * BW / 2), y: Y(L.hipX + L.fx),
      stance: L.stance, id: L.leg.id,
    }));
    const down = hull(feet.filter(f => f.stance));
    if (down.length >= 3) {
      const com = { x: X(0), y: Y(0) };
      const ok = inPoly(com, down);
      g.beginPath();
      down.forEach((p, i) => (i ? g.lineTo(p.x, p.y) : g.moveTo(p.x, p.y)));
      g.closePath();
      g.fillStyle = ok ? "rgba(54,211,153,.16)" : "rgba(248,114,114,.16)";
      g.strokeStyle = ok ? CSS("--good") : CSS("--bad");
      g.lineWidth = 1.5;
      g.fill(); g.stroke();
      g.fillStyle = ok ? CSS("--good") : CSS("--bad");
      g.beginPath(); g.arc(com.x, com.y, 4, 0, 7); g.fill();
    } else if (down.length === 2) {
      g.strokeStyle = CSS("--bad");
      g.setLineDash([4, 3]);
      g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(down[0].x, down[0].y); g.lineTo(down[1].x, down[1].y);
      g.stroke();
      g.setLineDash([]);
    }

    g.font = "9px ui-monospace,Menlo,monospace";
    g.textAlign = "center";
    feet.forEach(f => {
      g.fillStyle = f.stance ? CSS("--good") : CSS("--warn");
      g.beginPath(); g.arc(f.x, f.y, 6, 0, 7); g.fill();
      g.fillStyle = CSS("--muted");
      g.fillText(f.id, f.x, f.y + 18);
    });
    g.fillStyle = CSS("--muted");
    g.textAlign = "center";
    g.fillText("front", cx, 12);
    if (mode === "gait") {
      const hd = ((world.th * D) % 360 + 360) % 360;
      g.textAlign = "left";
      g.fillText((world.dist / 1000).toFixed(2) + " m", 6, h - 6);
      g.textAlign = "right";
      g.fillText(hd.toFixed(0) + "°", w - 6, h - 6);
    }
  }

  function drawDiagram() {
    const F = fit(el("sim-diag"));
    if (!F) return;
    const { g, w, h } = F;
    const G = GAITS[P.gait] || GAITS.trot;
    const duty = clamp(P.duty, 0.05, 0.98);
    const padL = 34, padR = 8, padT = 12, padB = 14;
    const iw = w - padL - padR, rows = LEGS.length;
    const rh = (h - padT - padB) / rows;

    g.font = "10px ui-monospace,Menlo,monospace";
    g.textAlign = "right";
    LEGS.forEach((L, i) => {
      const y = padT + i * rh + rh / 2;
      g.fillStyle = CSS("--muted");
      g.fillText(L.id, padL - 7, y + 3);
      g.fillStyle = CSS("--panel2");
      g.strokeStyle = CSS("--line");
      g.lineWidth = 1;
      roundRect(g, padL, y - rh * 0.28, iw, rh * 0.56, 4);
      g.fill(); g.stroke();
      const start = ((-(G.ph[L.id] || 0)) % 1 + 1) % 1;
      const segs = [[start, Math.min(1, start + duty)]];
      if (start + duty > 1) segs.push([0, start + duty - 1]);
      g.fillStyle = CSS("--accent");
      segs.forEach(([a, b]) => {
        roundRect(g, padL + a * iw, y - rh * 0.28, Math.max(2, (b - a) * iw),
          rh * 0.56, 4);
        g.fill();
      });
    });
    const px = padL + (((cycle % 1) + 1) % 1) * iw;
    g.strokeStyle = CSS("--warn");
    g.lineWidth = 1.5;
    g.beginPath(); g.moveTo(px, padT - 4); g.lineTo(px, h - padB + 2); g.stroke();
  }

  let tblSig = null;
  function drawTable(legs) {
    const t = el("sim-table");
    if (!t) return;
    const want = GEO ? "geo" : "1";
    if (tblSig !== want) {
      tblSig = want;
      t.innerHTML = `<tr><th>leg</th><th>phase</th><th>thigh</th><th>knee</th>
        <th>µs</th></tr>` + LEGS.map(L =>
        `<tr data-l="${L.id}"><td>${L.id}${provisional(L.id)
          ? ' <span class="warn" title="this leg\'s pulse-to-angle map was seeded from'
            + ' the other side, not measured">~</span>' : ""}</td>
         <td data-p="${L.id}"></td>
         <td class="mono" data-t="${L.id}"></td><td class="mono" data-k="${L.id}"></td>
         <td class="mono" data-u="${L.id}"></td></tr>`).join("");
    }
    legs.forEach(L => {
      const id = L.leg.id;
      const q = (a) => t.querySelector(`[data-${a}="${id}"]`);
      const ph = q("p");
      if (ph) {
        ph.textContent = mode === "gait"
          ? (L.stance ? "down " : "up ") + Math.round(L.p * 100) + "%"
          : mode === "live" ? (L.missing ? "no leg" : "live")
          : mode === "points" ? (L.missing ? "no points" : "taught") : "held";
        ph.className = mode === "gait" ? (L.stance ? "ok" : "warn") : "muted";
      }
      const tt = q("t"), kk = q("k"), uu = q("u");
      if (tt) tt.textContent = L.thigh.toFixed(0) + "°";
      if (kk) kk.textContent = L.knee.toFixed(0) + "°";
      if (uu) {
        const v = L.us || toUs(id, L.thigh, L.knee);
        uu.textContent = v ? v[0] + " / " + v[1] : "—";
        uu.className = "mono" + (L.us ? " ok" : "");
      }
      const tr = t.querySelector(`tr[data-l="${id}"]`);
      if (tr) tr.className = L.reach ? "bad" : L.outside ? "warn" : "";
      if (tt) tt.title = L.outside && !L.reach
        ? "outside the measured arc — this angle is the two-point map extrapolating"
        : "";
    });
  }

  const HINT = {
    gait: "An invented walk on the real legs — nothing has ever stepped this. Green"
      + " shading is the measured arc; amber is the map extrapolating.",
    ik: "Drag a foot. Red is past what 107 + 138 mm can reach; amber is reachable but"
      + " outside anything that was measured.",
    live: "The real joints, off telemetry, through the measured pulse-to-angle map.",
    points: "The taught walking points, played as a foot path on the real legs.",
  };

  function slider(key, label, lo, hi, step, fmt) {
    const id = "simr-" + key;
    return `<label class="vslider simsl"><span>${label}</span>
      <input type="range" id="${id}" min="${lo}" max="${hi}" step="${step}"
        value="${P[key]}"/>
      <span class="setval mono" id="${id}-v">${fmt(P[key])}</span></label>`;
  }

  const STAND_SLACK = 3;
  function standRange() {
    const b = standBand();
    return b ? [b[0] - STAND_SLACK, b[1] + STAND_SLACK] : null;
  }

  let standSig = null;
  function retuneStand() {
    const r = standRange();
    const sig = r ? r.join(":") : "";
    if (!r || sig === standSig) return;
    standSig = sig;
    const n = el("simr-stand");
    if (!n) return;
    n.min = r[0];
    n.max = r[1];
    n.value = P.stand = clamp(P.stand, r[0], r[1]);
    const v = el("simr-stand-v");
    if (v) v.textContent = P.stand + " mm";
    const note = el("sim-standnote");
    if (note) {
      note.textContent = `${r[0]}–${r[1]} mm — the five poses this robot has actually`
        + ` stood in, ±${STAND_SLACK} mm. Outside that there is no measurement to draw`
        + ` from.`;
    }
  }

  function buildSliders() {
    Object.keys(SLIDERS).forEach(host => {
      const n = el(host);
      if (!n) return;
      n.innerHTML = SLIDERS[host].map(s => slider(...s)).join("")
        + '<p class="small muted" id="sim-standnote"></p>';
      SLIDERS[host].forEach(([key, , , , , fmt]) => {
        const r = el("simr-" + key), v = el("simr-" + key + "-v");
        if (!r) return;
        r.addEventListener("input", () => {
          P[key] = +r.value;
          if (v) v.textContent = fmt(P[key]);
          if (key === "stand") LEGS.forEach(L => {
            if (!ikTarget[L.id].moved) ikTarget[L.id] = { x: 0, y: P.stand };
          });
          save();
        });
      });
    });
  }

  function setMode(m) {
    mode = m;
    document.querySelectorAll("#sim-mode .mbtn").forEach(b =>
      b.classList.toggle("active", b.dataset.mode === m));
    ["sim-gaitbox", "sim-diagbox", "sim-drivebox"].forEach(id => {
      const n = el(id);
      if (n) n.classList.toggle("inert", m !== "gait");
    });
    if (m !== "gait" && stick) stick.centre();
    const h = el("sim-hint");
    if (h) h.textContent = HINT[m] || "";
    const pl = el("sim-play");
    if (pl) pl.disabled = !(m === "gait" || m === "points");
    const pb = el("sim-ptsbox");
    if (pb) pb.classList.toggle("hidden", m !== "points");
  }

  function wireStepper() {
    const lp = el("sim-ptsleg");
    if (lp) {
      lp.innerHTML = LEGS.map(L =>
        `<button class="mbtn${L.id === P.ptsLeg ? " active" : ""}" data-pl="${L.id}"
          type="button">${L.id}</button>`).join("");
      lp.querySelectorAll(".mbtn").forEach(b => b.addEventListener("click", () => {
        P.ptsLeg = b.dataset.pl;
        ptsIndex = 0;
        lp.querySelectorAll(".mbtn").forEach(x => x.classList.toggle("active", x === b));
        stepSig = null;
        save();
      }));
    }
    const mp = el("sim-ptsmode");
    if (mp) {
      mp.querySelectorAll(".mbtn").forEach(b => b.addEventListener("click", () => {
        P.ptsMode = b.dataset.pm;
        mp.querySelectorAll(".mbtn").forEach(x => x.classList.toggle("active", x === b));
        stepSig = null;
        save();
      }));
      mp.querySelectorAll(".mbtn").forEach(b =>
        b.classList.toggle("active", b.dataset.pm === P.ptsMode));
    }
    const step = (d) => () => {
      if (P.ptsMode !== "step") return;
      ptsStep(d);
      stepSig = null;
    };
    const prev = el("sim-ptsprev"), next = el("sim-ptsnext");
    if (prev) prev.addEventListener("click", step(-1));
    if (next) next.addEventListener("click", step(1));
    document.addEventListener("keydown", (ev) => {
      const panel = el("tab-sim");
      if (!panel || !panel.classList.contains("active")) return;
      if (mode !== "points" || P.ptsMode !== "step") return;
      const t = ev.target || {};
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.isContentEditable) return;
      if (ev.key === "ArrowLeft") { ptsStep(-1); stepSig = null; ev.preventDefault(); }
      if (ev.key === "ArrowRight") { ptsStep(1); stepSig = null; ev.preventDefault(); }
    });
  }

  let driveSig = null;
  function drawDrive() {
    const n = el("sim-driveread");
    if (!n) return;
    const c = driveCmd();
    const top = P.period > 0 ? P.stride / P.period : 0;
    const spin = bodyWid() > 0 ? (2 * top / bodyWid()) * D : 0;
    const sig = [P.driveMode, P.auto, c.fwd.toFixed(2), c.turn.toFixed(2), P.stride,
                 P.period, Math.round(world.dist)].join("|");
    if (sig === driveSig) return;
    driveSig = sig;
    if (P.driveMode === "free") {
      n.innerHTML = `<p class="small muted">Free run — the legs cycle at the full
        <b class="mono">${P.stride} mm</b> stride and the robot goes nowhere in
        particular. Pick <b>Stick</b> or <b>Auto</b> to steer it.</p>`;
      return;
    }
    const still = !c.fwd && !c.turn;
    n.innerHTML = still
      ? `<p class="small muted">Standing. Push the stick — <b class="mono">${
          top.toFixed(0)} mm/s</b> and <b class="mono">${spin.toFixed(0)}°/s</b> is
          everything this gait has.</p>`
      : `<div class="simgeo-r"><span>speed</span><b class="mono">${
          (c.fwd * top).toFixed(0)} mm/s</b></div>
         <div class="simgeo-r"><span>turn</span><b class="mono">${
          (c.turn * spin).toFixed(0)} °/s</b></div>` +
        LEGS.map(L => {
          const m = legMix(L.id);
          return `<div class="simgeo-r"><span>${L.id} step</span><b class="mono${
            m < -0.02 ? " warn" : ""}">${(P.stride * m).toFixed(0)} mm</b></div>`;
        }).join("") +
        `<p class="small muted simgeo-w">${P.driveMode === "auto"
          ? `<b>${(AUTO[P.auto] || {}).label || "Auto"}</b> is driving — no hand needed.`
          : "A turn is one side stepping further than the other."} A <b>negative</b>
         step is that leg walking backwards, which is what the inside of a spin actually
         does.</p>`;
  }

  function wire() {
    wired = true;
    buildSliders();
    wireStepper();
    stick = STICK.make(el("sim-stick"), () => { driveSig = null; });
    const dm = el("sim-drivemode");
    if (dm) {
      dm.querySelectorAll(".mbtn").forEach(b => {
        b.classList.toggle("active", b.dataset.dm === P.driveMode);
        b.addEventListener("click", () => {
          P.driveMode = b.dataset.dm;
          if (P.driveMode !== "stick" && stick) stick.centre();
          dm.querySelectorAll(".mbtn").forEach(x => x.classList.toggle("active", x === b));
          const ab = el("sim-autobox");
          if (ab) ab.classList.toggle("hidden", P.driveMode !== "auto");
          const sp = el("sim-stick");
          if (sp) sp.classList.toggle("inert", P.driveMode !== "stick");
          driveSig = null;
          save();
        });
      });
    }
    const ab0 = el("sim-autopick");
    if (ab0) {
      ab0.innerHTML = Object.keys(AUTO).map(k =>
        `<button class="mbtn${k === P.auto ? " active" : ""}" data-au="${k}"
          type="button">${AUTO[k].label}</button>`).join("");
      ab0.querySelectorAll(".mbtn").forEach(b => b.addEventListener("click", () => {
        P.auto = b.dataset.au;
        ab0.querySelectorAll(".mbtn").forEach(x => x.classList.toggle("active", x === b));
        driveSig = null;
        save();
      }));
    }
    const abx = el("sim-autobox");
    if (abx) abx.classList.toggle("hidden", P.driveMode !== "auto");
    const spd = el("sim-stick");
    if (spd) spd.classList.toggle("inert", P.driveMode !== "stick");
    const tr = el("sim-trail");
    if (tr) {
      tr.checked = P.trail;
      tr.addEventListener("change", () => { P.trail = tr.checked; save(); });
    }

    const gs = el("sim-gait");
    if (gs) {
      gs.innerHTML = Object.keys(GAITS).map(k =>
        `<button class="mbtn${k === P.gait ? " active" : ""}" data-g="${k}"
          type="button">${GAITS[k].label}</button>`).join("");
      gs.querySelectorAll(".mbtn").forEach(b => b.addEventListener("click", () => {
        P.gait = b.dataset.g;
        P.duty = GAITS[P.gait].duty;
        const d = el("simr-duty"), dv = el("simr-duty-v");
        if (d) d.value = P.duty;
        if (dv) dv.textContent = Math.round(P.duty * 100) + "%";
        gs.querySelectorAll(".mbtn").forEach(x =>
          x.classList.toggle("active", x === b));
        save();
      }));
    }

    document.querySelectorAll("#sim-mode .mbtn").forEach(b =>
      b.addEventListener("click", () => setMode(b.dataset.mode)));

    const play = el("sim-play");
    if (play) play.addEventListener("click", () => {
      playing = !playing;
      play.textContent = playing ? "Pause" : "Play";
    });
    const reset = el("sim-reset");
    if (reset) reset.addEventListener("click", () => {
      cycle = 0;
      ptsCycle = 0;
      world.x = world.y = world.th = world.dist = 0;
      world.trail.length = 0;
      driveSig = null;
      LEGS.forEach(L => (ikTarget[L.id] = { x: 0, y: P.stand }));
    });
    const gh = el("sim-ghost");
    if (gh) {
      gh.checked = P.ghost;
      gh.addEventListener("change", () => { P.ghost = gh.checked; save(); });
    }

    const cv = el("sim-side");
    if (cv) {
      const pick = (ev) => {
        const r = cv.getBoundingClientRect();
        const legs = pose();
        const geo = sideGeom(cv);
        if (!geo) return null;
        let best = null, bd = 70 * 70;
        legs.forEach(L => {
          const dx = geo.X(L.hipX + L.fx) - (ev.clientX - r.left);
          const dy = geo.Y(P.stand - L.fy) - (ev.clientY - r.top);
          const d2 = dx * dx + dy * dy;
          if (d2 < bd) { bd = d2; best = L.leg.id; }
        });
        return best;
      };
      const move = (ev) => {
        if (!ikDrag) return;
        const r = cv.getBoundingClientRect();
        const geo = sideGeom(cv);
        if (!geo) return;
        const L = LEGS.find(l => l.id === ikDrag);
        const hipX = (L.front ? 1 : -1) * bodyLen() / 2;
        ikTarget[ikDrag] = {
          x: geo.ux(ev.clientX - r.left) - hipX,
          y: P.stand - geo.uy(ev.clientY - r.top),
          moved: true,
        };
      };
      cv.addEventListener("pointerdown", (ev) => {
        if (mode !== "ik") return;
        ikDrag = pick(ev);
        if (!ikDrag) return;
        ev.preventDefault();
        try { cv.setPointerCapture(ev.pointerId); } catch (e) { }
        move(ev);
      });
      cv.addEventListener("pointermove", move);
      ["pointerup", "pointercancel", "pointerleave"].forEach(e =>
        cv.addEventListener(e, () => (ikDrag = null)));
    }
    setMode(mode);
  }

  function sideGeom(c) {
    const w = c.clientWidth, h = c.clientHeight;
    if (!w || !h) return null;
    const reach = femur() + tibia();
    const g = mode === "gait";
    const gy = h - Math.max(20, h * (g ? 0.12 : 0.3));
    const spanX = bodyLen() + (g ? P.stride * 2 + reach * 0.5 : reach * 2.1);
    const spanY = P.stand + (g ? 55 : reach * 0.55);
    const s = Math.min(w * 0.9 / spanX, gy * 0.92 / spanY);
    const cx = w / 2;
    return { s, gy, X: v => cx + v * s, Y: v => gy - v * s,
             ux: px => (px - cx) / s, uy: py => (gy - py) / s };
  }

  function frame(ts) {
    requestAnimationFrame(frame);
    const dt = lastTs ? Math.min(0.05, (ts - lastTs) / 1000) : 0;
    lastTs = ts;
    const panel = el("tab-sim");
    if (!panel || !panel.classList.contains("active")) return;
    if (!wired) wire();
    retuneStand();
    if (playing && P.period > 0) {
      if (mode === "gait") {
        autoT += dt;
        const c = driveCmd();
        const rate = Math.max(Math.abs(c.fwd), Math.abs(c.turn));
        cycle += dt / P.period * rate;
        const top = P.stride / P.period;
        world.th += c.turn * (2 * top / Math.max(1, bodyWid())) * dt;
        const step = c.fwd * top * dt;
        world.x += step * Math.sin(world.th);
        world.y += step * Math.cos(world.th);
        world.dist += step;
        const last = world.trail[world.trail.length - 1];
        if (!last || Math.hypot(world.x - last[0], world.y - last[1]) > TRAIL_MM) {
          world.trail.push([world.x, world.y]);
          if (world.trail.length > TRAIL_MAX) world.trail.shift();
        }
      }
      else if (mode === "points" && P.ptsMode === "walk") ptsCycle += dt / P.period;
    }
    const legs = pose();
    drawSide(legs);
    drawTop(legs);
    drawDiagram();
    drawTable(legs);
    drawMeasured();
    drawReach();
    drawDrive();
    if (mode === "points") drawPointsInfo();
  }

  let geoSig = null;
  function drawMeasured() {
    const n = el("sim-geo");
    if (!n) return;
    const sig = GEO ? "geo" : "wait";
    if (sig === geoSig) return;
    geoSig = sig;
    if (!GEO) {
      n.innerHTML = '<span class="bad">/api/geometry did not answer</span> — drawing '
        + 'with the built-in fallback lengths, which are close but not read from '
        + 'config.py. Reload once the robot is up.';
      return;
    }
    const G = legGeo();
    const seeded = LEGS.filter(L => provisional(L.id)).map(L => L.id);
    n.innerHTML =
      `<div class="simgeo-r"><span>femur</span><b class="mono">${G.l_upper} mm</b></div>
       <div class="simgeo-r"><span>tibia</span><b class="mono">${G.l_lower} mm</b></div>
       <div class="simgeo-r"><span>body</span><b class="mono">${G.body_length} ×
         ${G.body_width} mm</b></div>
       <div class="simgeo-r"><span>reach</span><b class="mono">${G.l_upper + G.l_lower}
         mm</b></div>` +
      (seeded.length
        ? `<p class="warn small simgeo-w">${seeded.join(", ")} — pulse-to-angle seeded
           from the opposite leg, not measured. Marked <b>~</b> in the table.</p>`
        : "");
  }

  let reachSig = null;
  function drawReach() {
    const n = el("sim-reach");
    if (!n) return;
    const w = tightestLeg();
    const sig = (w ? w.id + "|" + w.dMin.toFixed(1) : "wait") + "|" + P.stand + "|"
      + P.centre + "|" + P.stride + "|" + P.clear;
    if (sig === reachSig) return;
    reachSig = sig;
    if (!w) {
      n.innerHTML = '<p class="muted small">waiting for a corridor off telemetry — this'
        + ' panel reads how far each knee can fold, which is the only thing that lifts a'
        + ' foot.</p>';
      return;
    }
    const rows = LEGS.map(L => {
      const r = reachOf(L.id);
      if (!r) return `<div class="simgeo-r"><span>${L.id}</span><b class="mono">—</b></div>`;
      const tight = L.id === w.id;
      return `<div class="simgeo-r"><span>${L.id} knee to ${r.kMin.toFixed(1)}°</span>
        <b class="mono${tight ? " warn" : ""}">${r.dMin.toFixed(1)} mm</b></div>`;
    }).join("");
    let worstLift = Infinity, atX = 0;
    for (let i = 0; i <= 20; i++) {
      const x = P.centre - P.stride / 2 + P.stride * i / 20;
      const l = liftAt(x, w);
      if (l != null && l < worstLift) { worstLift = l; atX = x; }
    }
    const got = isFinite(worstLift) ? worstLift : 0;
    const short = got + 0.5 < P.clear;
    n.innerHTML = rows +
      `<div class="simgeo-r"><span>asked for</span><b class="mono">${P.clear} mm</b></div>
       <div class="simgeo-r"><span>${w.id} can give</span><b class="mono${
         short ? " bad" : " ok"}">${got.toFixed(1)} mm</b></div>
       <p class="small muted simgeo-w">Shortest the leg goes, from its own corridor. A
       foot is lifted by folding the knee and by nothing else, so the leg that cannot get
       short is the one every gait has to clear the floor with — here <b>${w.id}</b>, at
       <b class="mono">${w.dMin.toFixed(1)} mm</b>. The second figure is the least
       daylight anywhere in this stroke${
         isFinite(worstLift) ? ` (at x ${Math.round(atX)} mm)` : ""}.` +
      (short ? ` <b class="warn">The step height is asking for more than exists</b> —
       stand taller, shift the stance further back, or re-spline the knee horn.` : "") +
      `</p>`;
  }

  function drawPointsInfo() {
    const n = el("sim-ptsinfo");
    if (!n) return;
    const set = (window.PTS && state && (state.walk || {}).sets || [])
      .find(s => s.id === PTS.activeId(state));
    const rows = LEGS.map(L => {
      const stored = window.PTS && state ? PTS.pointsFor(state, L.id).length : 0;
      const drawn = taughtPath(L.id).length;
      return `<div class="simgeo-r"><span>${L.id}</span><b class="mono${
        stored && drawn < stored ? " bad" : ""}">${drawn}/${stored}</b></div>`;
    }).join("");
    n.innerHTML = `<div class="simgeo-r"><span>set</span><b>${
      set ? String(set.name).replace(/[<>&]/g, "") : "—"}</b></div>` + rows +
      `<p class="small muted simgeo-w">drawn / stored. A point short of its total sits
       at a thigh with no measured corridor, so there is no knee window for its
       fraction to resolve in. Pick the set on the Calibration tab.</p>`;
    drawStepper();
  }

  let stepSig = null;
  function drawStepper() {
    const n = el("sim-stepinfo");
    if (!n) return;
    const walking = P.ptsMode === "walk";
    const path = taughtPath(P.ptsLeg);
    const total = path.length;
    const i = total ? ((ptsIndex % total) + total) % total : 0;
    const p = total ? path[i] : null;
    const sig = [P.ptsMode, P.ptsLeg, i, total, P.gait].join("|");
    if (sig === stepSig) return;
    stepSig = sig;
    const c = el("sim-ptscount");
    if (c) c.textContent = walking ? "all four" : total ? `${i + 1} / ${total}` : "—";
    ["sim-ptsprev", "sim-ptsnext"].forEach(id => {
      const b = el(id);
      if (b) b.disabled = walking || total < 2;
    });
    if (walking) {
      const G = GAITS[P.gait] || GAITS.walk;
      n.innerHTML = `<p class="small muted simgeo-w">All four legs running the taught
        set, offset by the <b>${G.label}</b> phase table — ${LEGS.map(L =>
        `${L.id} ${Math.round((G.ph[L.id] || 0) * 100)}%`).join(", ")}. The shape is
        taught; <b>which foot lifts when is the gait's</b>, borrowed from the Gait mode
        so there is only ever one answer to it.</p>`;
      return;
    }
    if (!p) {
      n.innerHTML = `<p class="small muted simgeo-w">${P.ptsLeg} has no drawable points
        in this set.</p>`;
      return;
    }
    const base = pointAt(P.ptsLeg, 0);
    const b = base ? forward(base.thigh, base.knee, femur(), tibia(), KNEE_BACK) : null;
    const lift = b ? b.fy - p.fy : null;
    n.innerHTML =
      `<div class="simgeo-r"><span>thigh</span><b class="mono">${p.us[0]} µs · ${
        p.thigh.toFixed(1)}°</b></div>
       <div class="simgeo-r"><span>knee</span><b class="mono">${p.us[1]} µs · ${
        p.knee.toFixed(1)}°</b></div>
       <div class="simgeo-r"><span>foot</span><b class="mono">${p.fx.toFixed(0)}, ${
        p.fy.toFixed(0)} mm</b></div>` +
      (lift == null ? "" :
        `<div class="simgeo-r"><span>vs point 1</span><b class="mono${
          lift > 0.5 ? " ok" : ""}">${lift > 0 ? "+" : ""}${lift.toFixed(1)} mm</b></div>`) +
      `<p class="small muted simgeo-w">Point <b>${i + 1}</b> of ${total} on <b>${
        P.ptsLeg}</b>, held still. The other three stand at their own point 1.
       <b>vs point 1</b> is how far this one lifts the foot above where this leg started
       — the number the chart cannot show.</p>`;
  }
  requestAnimationFrame(frame);

  function render(s) { state = s; }

  function angleSpan(legId, joint) {
    const pts = anglePts(legId, joint);
    if (!pts) return null;
    const d = pts.map(p => p[1]);
    return [Math.min.apply(null, d), Math.max.apply(null, d)];
  }

  function gaitOpts() {
    return { gait: P.gait, stride: P.stride, clear: P.clear, duty: P.duty,
             stand: P.stand, period: P.period, centre: P.centre,
             standRange: standRange(),
             gaits: Object.keys(GAITS).map(k => ({ id: k, label: GAITS[k].label })) };
  }

  function setGaitOpt(key, value) {
    if (!(key in P)) return false;
    if (key === "gait") {
      if (!GAITS[value]) return false;
      P.gait = value;
      P.duty = GAITS[value].duty;
      const d = el("simr-duty"), dv = el("simr-duty-v");
      if (d) d.value = P.duty;
      if (dv) dv.textContent = Math.round(P.duty * 100) + "%";
      document.querySelectorAll("#sim-gait .mbtn").forEach(b =>
        b.classList.toggle("active", b.dataset.g === value));
    } else {
      const v = +value;
      if (!isFinite(v)) return false;
      P[key] = v;
      const r = el("simr-" + key);
      if (r) r.value = v;
      const o = el("simr-" + key + "-v");
      const row = (SLIDERS["sim-sliders-gait"] || []).find(x => x[0] === key);
      if (o && row) o.textContent = row[5](v);
    }
    save();
    return true;
  }

  return { render, gaitPoints, gaitLabel, angleSpan, gaitOpts, setGaitOpt };
})();
