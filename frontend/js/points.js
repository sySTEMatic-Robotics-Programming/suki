window.PTS = (function () {
  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const f1 = (n) => (Math.round(n * 10) / 10).toFixed(1);
  const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

  const KEY_ACT = "suki.pts.active";
  const KEY_HIDE = "suki.pts.hidden";
  const KEY_ACTS = "suki.pts.actions";
  const KEY_GAIT = "suki.pts.gait";
  const FALLBACK = "#a855f7";
  const GAIT_COL = "#38bdf8";

  let active = +(localStorage.getItem(KEY_ACT) || 0) || null;
  let hidden = new Set((localStorage.getItem(KEY_HIDE) || "").split(",")
    .map(n => +n).filter(Boolean));
  let showActions = localStorage.getItem(KEY_ACTS) === "1";
  let showGait = localStorage.getItem(KEY_GAIT) === "1";
  let sig = null;
  let lastState = null, lastLeg = null;
  let dnd = null;

  const saveLocal = () => {
    try {
      localStorage.setItem(KEY_ACT, String(active || ""));
      localStorage.setItem(KEY_HIDE, Array.from(hidden).join(","));
      localStorage.setItem(KEY_ACTS, showActions ? "1" : "0");
      localStorage.setItem(KEY_GAIT, showGait ? "1" : "0");
    } catch (e) { }
  };

  const pending = {};
  setInterval(() => {
    for (const k in pending) {
      const m = pending[k];
      delete pending[k];
      RD.send(m);
    }
  }, 50);

  const walk = (state) => (state && state.walk) || {};
  const sets = (state) => walk(state).sets || [];
  const palette = (state) => walk(state).palette || [FALLBACK];

  const colourOf = (state, s) =>
    palette(state).indexOf(s && s.colour) >= 0 ? s.colour : FALLBACK;

  function activeSet(state) {
    const all = sets(state);
    if (!all.length) return null;
    return all.find(s => s.id === active) || all[0];
  }
  function activeId(state) {
    const s = activeSet(state || lastState);
    return s ? s.id : null;
  }

  function bandAt(band, thigh) {
    let best = null;
    (band || []).forEach(run => {
      for (let i = 0; i < run.length - 1; i++) {
        const a = run[i], b = run[i + 1];
        if (thigh < Math.min(a[0], b[0]) || thigh > Math.max(a[0], b[0])) continue;
        const t = b[0] === a[0] ? 0 : (thigh - a[0]) / (b[0] - a[0]);
        best = [a[1] + t * (b[1] - a[1]), a[2] + t * (b[2] - a[2])];
      }
      if (!best && run.length === 1) best = [run[0][1], run[0][2]];
    });
    return best;
  }

  function kneeAt(rep, thigh, k) {
    const w = bandAt(rep && rep.safe_band, thigh);
    if (!w) return null;
    const lo = Math.min(w[0], w[1]), hi = Math.max(w[0], w[1]);
    return lo + clamp(k, 0, 1) * (hi - lo);
  }

  function kOf(rep, thigh, kneeUs) {
    const w = bandAt(rep && rep.safe_band, thigh);
    if (!w) return 0.5;
    const lo = Math.min(w[0], w[1]), hi = Math.max(w[0], w[1]);
    return hi - lo > 1e-6 ? clamp((kneeUs - lo) / (hi - lo), 0, 1) : 0.5;
  }

  function bandRun(band, thigh) {
    const runs = band || [];
    if (!runs.length) return null;
    let best = null, bestd = null;
    runs.forEach(run => {
      const lo = run[0][0], hi = run[run.length - 1][0];
      const d = thigh < lo ? lo - thigh : thigh > hi ? thigh - hi : 0;
      if (bestd === null || d < bestd) { best = [lo, hi]; bestd = d; }
    });
    return best;
  }

  function pointsFor(state, leg, setId) {
    const s = setId == null ? activeSet(state) : sets(state).find(x => x.id === setId);
    if (!s) return [];
    return ((s.legs || {})[leg] || []).map((p, i) => ({
      i, thigh: p.thigh, k: p.k, dwell: p.dwell || 0,
    }));
  }

  function actionPoints(state, leg) {
    const rep = ((state || {}).legs || {})[leg];
    if (!rep) return [];
    const tc = String(rep.thigh_ch), kc = String(rep.knee_ch);
    const out = [];
    (state.actions || []).forEach(a => {
      const pos = a.pos || {};
      if (pos[tc] == null || pos[kc] == null) return;
      out.push({ id: a.id, name: a.name, thigh: +pos[tc], knee: +pos[kc], i: out.length });
    });
    return out;
  }

  function fittedGait(state, leg, rep, n) {
    if (!window.SIM || !rep || !rep.thigh_span) return [];
    const raw = SIM.gaitPoints(leg, n || 48);
    if (raw.length < 2) return [];
    const ts = raw.map(q => q.thigh), ks = raw.map(q => q.knee);
    const tlo = Math.min.apply(null, ts), thi = Math.max.apply(null, ts);
    const klo = Math.min.apply(null, ks), khi = Math.max.apply(null, ks);
    const tspan = thi - tlo, kspan = khi - klo;
    const [clo, chi] = rep.thigh_span;
    return raw.map(q => {
      const tn = tspan > 1e-6 ? (q.thigh - tlo) / tspan : 0.5;
      const thigh = clo + tn * (chi - clo);
      const w = bandAt(rep.safe_band, thigh);
      const kn = kspan > 1e-6 ? (q.knee - klo) / kspan : 0.5;
      const knee = w ? Math.min(w[0], w[1]) + kn * Math.abs(w[1] - w[0]) : null;
      return { ...q, thigh, knee, k: kn };
    }).filter(q => q.knee != null);
  }

  function kneeExtent() { return null; }

  function thighExtent(state, leg) {
    let lo = null, hi = null;
    const act = activeSet(state);
    sets(state).forEach(s => {
      if (hidden.has(s.id) && !(act && s.id === act.id)) return;
      pointsFor(state, leg, s.id).forEach(p => {
        lo = lo == null ? p.thigh : Math.min(lo, p.thigh);
        hi = hi == null ? p.thigh : Math.max(hi, p.thigh);
      });
    });
    if (showActions) {
      actionPoints(state, leg).forEach(p => {
        lo = lo == null ? p.thigh : Math.min(lo, p.thigh);
        hi = hi == null ? p.thigh : Math.max(hi, p.thigh);
      });
    }
    return lo == null ? null : [lo, hi];
  }

  function nearest(state, leg, g, pt, rep) {
    let best = null, bestd = 24 * 24;
    pointsFor(state, leg).forEach(p => {
      const knee = kneeAt(rep, p.thigh, p.k);
      if (knee == null) return;
      const dx = g.sx(p.thigh) - pt[0], dy = g.sy(knee) - pt[1];
      const d2 = dx * dx + dy * dy;
      if (d2 <= bestd) { bestd = d2; best = p.i; }
    });
    return best;
  }

  function overlay(state, leg, g, rep, editing) {
    if (!g) return "";
    let out = '<g class="pts-layer" pointer-events="none">';
    const act = activeSet(state);

    const order = sets(state).filter(s => !hidden.has(s.id) || (act && s.id === act.id))
      .sort((a, b) => (act && a.id === act.id ? 1 : 0) - (act && b.id === act.id ? 1 : 0));

    order.forEach(s => {
      const isActive = !!(act && s.id === act.id);
      const col = colourOf(state, s);
      const pts = pointsFor(state, leg, s.id).map(p => {
        const knee = kneeAt(rep, p.thigh, p.k);
        return { ...p, knee, x: g.sx(p.thigh), y: knee == null ? null : g.sy(knee) };
      });
      const drawn = pts.filter(p => p.y != null);
      if (!pts.length) return;

      if (drawn.length > 1) {
        out += `<path d="M${drawn.map(p => `${f1(p.x)},${f1(p.y)}`).join(" L")} Z"
          fill="none" stroke="${col}" stroke-width="${isActive ? 2.4 : 1.6}"
          stroke-opacity="${isActive ? 0.85 : 0.45}" stroke-linejoin="round"/>`;
        for (let i = 0; i < drawn.length; i++) {
          const a = drawn[i], b = drawn[(i + 1) % drawn.length];
          const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
          const L = Math.hypot(b.x - a.x, b.y - a.y) || 1;
          const dx = (b.x - a.x) / L * 6, dy = (b.y - a.y) / L * 6;
          out += `<path d="M${f1(mx - dx - dy * 0.5)},${f1(my - dy + dx * 0.5)}
            L${f1(mx + dx)},${f1(my + dy)}
            L${f1(mx - dx + dy * 0.5)},${f1(my - dy - dx * 0.5)}" fill="none"
            stroke="${col}" stroke-width="1.5"
            stroke-opacity="${isActive ? 0.95 : 0.5}"/>`;
        }
      }

      pts.forEach((p, n) => {
        const ramp = pts.length > 1 ? 0.45 + 0.55 * (n / (pts.length - 1)) : 1;
        const dim = isActive ? ramp : ramp * 0.5;
        if (p.y == null) {
          out += `<path d="M${f1(p.x)},${f1(g.sy(g.yr[0]))}
            l-5,10 l10,0 Z" fill="var(--bad)" fill-opacity="${dim}"/>`;
          return;
        }
        if (p.dwell > 0) {
          out += `<circle cx="${f1(p.x)}" cy="${f1(p.y)}" r="15" fill="none"
            stroke="var(--warn)" stroke-width="1.4" stroke-dasharray="3 2"
            stroke-opacity="${dim}"/>`;
        }
        const r = isActive ? 11 : 8;
        out += `<circle class="wp-dot" data-i="${p.i}" cx="${f1(p.x)}" cy="${f1(p.y)}"
          r="${r}" fill="var(--panel2)" fill-opacity="0.92" stroke="${col}"
          stroke-width="${isActive ? 2.6 : 1.6}" stroke-opacity="${dim}"/>`;
        out += `<text class="wp-n" data-i="${p.i}" x="${f1(p.x)}" y="${f1(p.y + 4)}"
          text-anchor="middle" font-size="${isActive ? 11 : 9}" font-weight="700"
          fill="var(--text)" fill-opacity="${dim}">${p.i + 1}</text>`;
        if (isActive && editing) {
          out += `<circle class="wp-x" data-i="${p.i}" cx="${f1(p.x)}" cy="11" r="8"
            fill="var(--panel)" stroke="var(--bad)" stroke-width="1"/>`;
          out += `<text class="wp-x" data-i="${p.i}" x="${f1(p.x)}" y="15"
            font-size="11" fill="var(--bad)" text-anchor="middle">&times;</text>`;
        }
      });
    });

    if (showGait && window.SIM) {
      const gp = fittedGait(state, leg, rep, 56);
      if (gp.length > 1) {
        const xy = gp.map(q => ({ ...q, x: g.sx(q.thigh), y: g.sy(q.knee) }));
        [["stance", "none"], ["swing", "5 4"]].forEach(([which, dash]) => {
          let d = "";
          xy.forEach((q, n) => {
            const prev = n > 0 ? xy[n - 1] : null;
            const isOn = (p) => which === "stance" ? p.stance : !p.stance;
            if (!isOn(q)) return;
            d += (prev && isOn(prev) ? " L" : " M") + `${f1(q.x)},${f1(q.y)}`;
          });
          if (d) out += `<path d="${d.trim()}" fill="none" stroke="${GAIT_COL}"
            stroke-width="${which === "stance" ? 2.4 : 1.8}" stroke-opacity="0.9"
            stroke-linecap="round" stroke-linejoin="round"
            stroke-dasharray="${dash}"/>`;
        });
        out += `<path d="M${f1(xy[xy.length - 1].x)},${f1(xy[xy.length - 1].y)}
          L${f1(xy[0].x)},${f1(xy[0].y)}" fill="none" stroke="${GAIT_COL}"
          stroke-width="1.8" stroke-opacity="0.55"/>`;
        for (let n = 0; n < xy.length; n += 7) {
          const p0 = xy[n], p1 = xy[(n + 3) % xy.length];
          const L = Math.hypot(p1.x - p0.x, p1.y - p0.y) || 1;
          const dx = (p1.x - p0.x) / L * 5, dy = (p1.y - p0.y) / L * 5;
          out += `<path d="M${f1(p0.x - dy * 0.5)},${f1(p0.y + dx * 0.5)}
            L${f1(p0.x + dx)},${f1(p0.y + dy)}
            L${f1(p0.x + dy * 0.5)},${f1(p0.y - dx * 0.5)}" fill="none"
            stroke="${GAIT_COL}" stroke-width="1.4" stroke-opacity="0.9"/>`;
        }
        const td = xy.find((q, n) =>
          q.stance && !xy[(n - 1 + xy.length) % xy.length].stance);
        if (td) out += `<circle cx="${f1(td.x)}" cy="${f1(td.y)}" r="4.5"
          fill="${GAIT_COL}" stroke="var(--bg)" stroke-width="1.5"/>`;
      }
    }

    if (showActions) {
      actionPoints(state, leg).forEach(p => {
        const x = g.sx(p.thigh), y = g.sy(p.knee);
        out += `<rect x="${f1(x - 7)}" y="${f1(y - 7)}" width="14" height="14" rx="3"
          fill="var(--panel2)" fill-opacity="0.9" stroke="var(--good)"
          stroke-width="1.8" stroke-dasharray="3 2"/>`;
        out += `<text x="${f1(x)}" y="${f1(y + 3.5)}" text-anchor="middle" font-size="9"
          font-weight="700" fill="var(--good)">${p.i + 1}</text>`;
      });
    }
    return out + "</g>";
  }


  function ghost(svg, i, x, y) {
    const dot = svg.querySelector(`.wp-dot[data-i="${i}"]`);
    if (dot) { dot.setAttribute("cx", f1(x)); dot.setAttribute("cy", f1(y)); }
    const n = svg.querySelector(`.wp-n[data-i="${i}"]`);
    if (n) { n.setAttribute("x", f1(x)); n.setAttribute("y", f1(y + 4)); }
    const d = svg.querySelectorAll(`.wp-x[data-i="${i}"]`);
    d.forEach(e => e.setAttribute(e.tagName === "text" ? "x" : "cx", f1(x)));
  }

  function moveTo(state, leg, index, thigh, kneeUs, rep) {
    const bx = bandRun(rep && rep.safe_band, thigh);
    if (bx) thigh = clamp(thigh, bx[0], bx[1]);
    const sid = activeId(state);
    if (sid == null) return null;
    const k = kOf(rep, thigh, kneeUs);
    pending[leg + ":" + index] = { type: "walk_set_point", set: sid, leg, index,
                                   thigh: Math.round(thigh), k };
    return [Math.round(thigh), kneeAt(rep, Math.round(thigh), k)];
  }

  function addAt(state, leg, thigh, kneeUs, rep) {
    const sid = activeId(state);
    if (sid == null) return;
    const bx = bandRun(rep && rep.safe_band, thigh);
    if (bx) thigh = clamp(thigh, bx[0], bx[1]);
    RD.send({ type: "walk_add", set: sid, leg, thigh: Math.round(thigh),
              k: kOf(rep, thigh, kneeUs) });
  }

  function removeAt(state, leg, index) {
    const sid = activeId(state);
    if (sid == null) return;
    RD.send({ type: "walk_delete", set: sid, leg, index });
  }

  function crossAt(state, leg, g, pt, rep, topPad) {
    if (pt[1] > topPad) return null;
    let best = null, bestd = 14;
    pointsFor(state, leg).forEach(p => {
      if (kneeAt(rep, p.thigh, p.k) == null) return;
      const d = Math.hypot(pt[0] - g.sx(p.thigh), pt[1] - 11);
      if (d <= bestd) { bestd = d; best = p.i; }
    });
    return best;
  }

  function gaitNote(state, leg) {
    if (!window.SIM) return "";
    if (!showGait) return '<span class="muted">— its shape, fitted to this leg\'s ' +
      'measured travel</span>';
    const gp = SIM.gaitPoints(leg, 48);
    if (!gp.length) return '<span class="bad">— this leg has no measured ' +
      'pulse-to-angle map, so there is nothing honest to draw</span>';

    const rep = ((state || {}).legs || {})[leg];
    let fits = 0;
    gp.forEach(q => {
      const w = bandAt(rep && rep.safe_band, q.thigh);
      if (!w || q.over) return;
      const lo = Math.min(w[0], w[1]), hi = Math.max(w[0], w[1]);
      if (q.knee >= lo - 1 && q.knee <= hi + 1) fits++;
    });
    const guessed = gp.filter(q => q.unverified).length;
    const caveat = guessed
      ? ` <b class="warn">${guessed} of ${gp.length} points are outside the measured `
        + `arc</b> — legal microseconds, but worked out past the end of the calibration.`
      : "";
    if (fits === gp.length) {
      return '<span class="muted">— <b class="ok">fits at true scale</b>, so this is ' +
        'the real cycle and not only its shape.' + caveat +
        ' <b>A preview — nothing is saved.</b></span>';
    }
    const deg = (v) => String(Math.round(v)).replace("-", "\u2212") + "°";
    const rng = (a) => deg(Math.min.apply(null, a)) + " to " + deg(Math.max.apply(null, a));
    const span = (v) => v ? deg(v[0]) + " to " + deg(v[1]) : "—";
    const ks = SIM.angleSpan(leg, "knee");
    return '<span class="muted">— drawn as its <b>shape scaled into this leg\'s ' +
      'travel</b>, because at true scale it ' +
      `<b class="bad">fits ${fits}/${gp.length}</b>: it wants knee ` +
      `<b class="mono">${rng(gp.map(q => q.degKnee))}</b> and this leg was only ` +
      `measured across <b class="mono">${span(ks)}</b>. ` +
      '<b>A preview — nothing is saved.</b></span>';
  }

  function gaitBar() {
    if (!window.SIM || !SIM.gaitOpts) return "";
    const o = SIM.gaitOpts();
    return `<div class="wp-gaitbar">
      <div class="seg wp-gseg">${o.gaits.map(g =>
        `<button class="mbtn${g.id === o.gait ? " active" : ""}" data-gait="${g.id}"
          type="button">${esc(g.label)}</button>`).join("")}</div>
      <label class="wp-gsl">step <input type="range" data-gopt="stride" min="0" max="100"
        step="1" value="${o.stride}"/><b class="mono">${o.stride} mm</b></label>
      <label class="wp-gsl">lift <input type="range" data-gopt="clear" min="0" max="40"
        step="1" value="${o.clear}"/><b class="mono">${o.clear} mm</b></label>
      <!-- STANCE CENTRE, and it belongs here more than anywhere. Every verified pose
           puts the foot 13 to 56 mm BEHIND the hip, so where the stroke is centred is
           what decides whether the cycle sits in the middle of this leg's corridor or
           hangs off one end of it - and this is the chart that shows that. -->
      <label class="wp-gsl">stance <input type="range" data-gopt="centre" min="-80"
        max="20" step="1" value="${o.centre}"/><b class="mono">${
          o.centre > 0 ? "+" : ""}${o.centre} mm</b></label>
      <label class="wp-gsl">down <input type="range" data-gopt="duty" min="0.3" max="0.95"
        step="0.01" value="${o.duty}"/><b class="mono">${Math.round(o.duty * 100)}%</b></label>
      <!-- The stand height is NOT here. Its range is re-read from the five verified
           poses every frame on the Simulator tab; a second slider with a second range
           is exactly the kind of copy that goes stale. -->
    </div>`;
  }

  function render(state, leg) {
    const host = el("pts-panel");
    if (!host) return;
    lastState = state; lastLeg = leg;
    const rep = ((state || {}).legs || {})[leg];
    const all = sets(state);
    if (!all.length) { host.innerHTML = ""; sig = null; return; }
    const act = activeSet(state);
    const pts = pointsFor(state, leg, act.id);
    const acts = actionPoints(state, leg);
    const pal = palette(state);
    const maxPts = walk(state).max_points || 64;
    const maxSets = walk(state).max_sets || 12;
    const dmax = walk(state).dwell_max || 10;

    const resolved = pts.map(p => ({ ...p, knee: kneeAt(rep, p.thigh, p.k) }));
    const orphans = resolved.filter(p => p.knee == null).length;

    const next = JSON.stringify([leg, act.id, showActions, showGait,
      showGait && window.SIM ? SIM.gaitLabel() : "", Array.from(hidden).sort(),
      acts.length, all.map(s => [s.id, s.name, s.colour,
        (s.legs[leg] || []).map(p => [p.thigh, p.k, p.dwell])])]);
    if (next === sig) return;
    sig = next;

    const chips = all.map(s => `<span class="wp-chip${s.id === act.id ? " on" : ""}"
      data-s="${s.id}">
        <button class="wp-eye${hidden.has(s.id) ? " off" : ""}" data-eye="${s.id}"
          type="button" title="show this set on the chart"
          style="--c:${colourOf(state, s)}"></button>
        <button class="wp-pick" data-pick="${s.id}" type="button">${esc(s.name)}</button>
        <span class="wp-n2">${(s.legs[leg] || []).length}</span>
      </span>`).join("");

    const swatches = pal.map(c =>
      `<button class="wp-sw${c === act.colour ? " on" : ""}" data-col="${esc(c)}"
        type="button" style="--c:${esc(c)}" title="${esc(c)}"></button>`).join("");

    const legOpts = ["FR", "FL", "BR", "BL"].filter(l => l !== leg)
      .map(l => `<option value="${l}">${l}</option>`).join("");

    const rows = resolved.map(p => `<tr data-i="${p.i}">
      <td class="wp-grip" data-i="${p.i}" title="drag to change the order">&#9776;</td>
      <td class="wp-i">${p.i + 1}</td>
      <td><input class="wp-th mono" type="number" data-i="${p.i}" step="1"
           min="500" max="2500" value="${p.thigh}"/></td>
      <td class="mono ${p.knee == null ? "bad" : ""}">${p.knee == null ? "—"
        : Math.round(p.knee)}</td>
      <td class="mono muted">${p.k.toFixed(2)}</td>
      <td><input class="wp-dw mono" type="number" data-i="${p.i}" step="0.05" min="0"
           max="${dmax}" value="${p.dwell}"/></td>
      <td><button class="wp-rm" data-i="${p.i}" type="button" title="delete">×</button></td>
    </tr>`).join("");

    host.innerHTML = `
      <div class="wp-sets">${chips}
        <button class="wp-add" type="button" ${all.length >= maxSets ? "disabled" : ""}
          title="a new, empty set">+ set</button>
      </div>

      <div class="wp-bar">
        <input class="wp-name txt" value="${esc(act.name)}" maxlength="32"
          title="rename this set"/>
        <span class="wp-sws">${swatches}</span>
      </div>
      <div class="wp-bar">
        <button class="btn wp-dup" type="button"
          ${all.length >= maxSets ? "disabled" : ""}>Duplicate set</button>
        <button class="btn wp-clear" type="button">Clear ${esc(leg)}</button>
        <label class="wp-copy">Copy ${esc(leg)} to
          <select class="wp-to">${legOpts}</select>
          <button class="btn wp-go" type="button">go</button></label>
        <span class="grow"></span>
        <button class="btn wp-del" type="button">Delete set</button>
      </div>

      ${pts.length ? `<table class="wp-tbl"><thead><tr><th></th><th>#</th>
        <th>thigh µs</th><th>knee µs</th><th>k</th><th>dwell s</th><th></th></tr></thead>
        <tbody>${rows}</tbody></table>`
      : `<p class="muted small pts-empty">Nothing for ${esc(leg)} yet — pick
          <b>Draw points</b> above the chart and tap inside the yellow.</p>`}

      <label class="wp-actl"><input type="checkbox" class="wp-acts"
        ${showActions ? "checked" : ""}/> also draw the <b>${acts.length} recorded
        pose${acts.length === 1 ? "" : "s"}</b></label>
      <label class="wp-actl"><input type="checkbox" class="wp-gait"
        ${showGait ? "checked" : ""}/> also draw the <b class="wp-gc">Simulator's
        gait</b> ${gaitNote(state, leg)}</label>
      ${showGait ? gaitBar() : ""}

      <small class="muted pts-hint">
        ${pts.length >= maxPts ? `<b class="bad">Full at ${maxPts} points.</b> ` : ""}
        ${orphans ? `<b class="bad">${orphans} point${orphans === 1 ? "" : "s"} outside
          this leg's measured corridor</b> — the red marks on the bottom rule. Drag
          ${orphans === 1 ? "it" : "them"} into the yellow. ` : ""}
        <b>k</b> is the height as a fraction of the yellow band, so re-measuring the
        corridor carries the shape with it.</small>`;

    wire(host, leg, act);
  }

  function wire(host, leg, act) {
    const q = (s) => host.querySelector(s);
    const all = (s) => host.querySelectorAll(s);
    const repaint = () => { sig = null; render(lastState, lastLeg); };

    all(".wp-pick").forEach(b => b.addEventListener("click", () => {
      active = +b.dataset.pick;
      hidden.delete(active);
      saveLocal();
      repaint();
    }));
    all(".wp-eye").forEach(b => b.addEventListener("click", () => {
      const id = +b.dataset.eye;
      if (hidden.has(id)) hidden.delete(id); else hidden.add(id);
      saveLocal();
      repaint();
    }));
    const add = q(".wp-add");
    if (add) add.addEventListener("click", () => RD.send({ type: "walk_set_add" }));
    const dup = q(".wp-dup");
    if (dup) dup.addEventListener("click", () =>
      RD.send({ type: "walk_set_add", copy_of: act.id }));

    const name = q(".wp-name");
    if (name) name.addEventListener("change", () =>
      RD.send({ type: "walk_set_rename", id: act.id, name: name.value }));
    all(".wp-sw").forEach(b => b.addEventListener("click", () =>
      RD.send({ type: "walk_set_colour", id: act.id, colour: b.dataset.col })));

    const clear = q(".wp-clear");
    if (clear) clear.addEventListener("click", () => {
      if (!window.confirm(`Clear every ${leg} point in “${act.name}”?`)) return;
      RD.send({ type: "walk_clear", set: act.id, leg });
    });
    const del = q(".wp-del");
    if (del) del.addEventListener("click", () => {
      const last = sets(lastState).length <= 1;
      if (!window.confirm(last
        ? `“${act.name}” is the only set, so it will be emptied rather than removed. `
          + "Every leg's points in it are lost. Continue?"
        : `Delete the set “${act.name}” and all four legs' points in it?`)) return;
      RD.send({ type: "walk_set_delete", id: act.id });
    });
    const go = q(".wp-go"), to = q(".wp-to");
    if (go && to) go.addEventListener("click", () => {
      if (!window.confirm(`Replace every ${to.value} point in “${act.name}” with a copy `
        + `of ${leg}'s?`)) return;
      RD.send({ type: "walk_copy_leg", set: act.id, from: leg, to: to.value });
    });

    all(".wp-rm").forEach(b => b.addEventListener("click", () =>
      RD.send({ type: "walk_delete", set: act.id, leg, index: +b.dataset.i })));
    all(".wp-th").forEach(inp => inp.addEventListener("change", () => {
      const v = parseInt(inp.value, 10);
      if (isFinite(v)) RD.send({ type: "walk_set_point", set: act.id, leg,
                                 index: +inp.dataset.i, thigh: v });
    }));
    all(".wp-dw").forEach(inp => inp.addEventListener("change", () => {
      const v = parseFloat(inp.value);
      if (isFinite(v)) RD.send({ type: "walk_set_point", set: act.id, leg,
                                 index: +inp.dataset.i, dwell: v });
    }));

    const acb = q(".wp-acts");
    if (acb) acb.addEventListener("change", () => {
      showActions = acb.checked;
      saveLocal();
      repaint();
    });
    const gcb = q(".wp-gait");
    if (gcb) gcb.addEventListener("change", () => {
      showGait = gcb.checked;
      saveLocal();
      repaint();
    });
    all("[data-gait]").forEach(b => b.addEventListener("click", () => {
      if (window.SIM) SIM.setGaitOpt("gait", b.dataset.gait);
      repaint();
    }));
    all("[data-gopt]").forEach(r => r.addEventListener("input", () => {
      if (window.SIM) SIM.setGaitOpt(r.dataset.gopt, r.value);
      const b = r.parentElement.querySelector("b");
      if (b) b.textContent = r.dataset.gopt === "duty"
        ? Math.round(+r.value * 100) + "%" : Math.round(+r.value) + " mm";
      sig = null;
    }));

    wireReorder(host, act, leg);
  }

  function wireReorder(host, act, leg) {
    const tbody = host.querySelector(".wp-tbl tbody");
    if (!tbody) return;
    const rows = () => Array.from(tbody.querySelectorAll("tr"));
    host.querySelectorAll(".wp-grip").forEach(h => {
      h.addEventListener("pointerdown", ev => {
        ev.preventDefault();
        const tr = h.closest("tr");
        if (!tr) return;
        const from = +tr.dataset.i;
        dnd = { from, to: from };
        tr.classList.add("dragrow");
        try { h.setPointerCapture(ev.pointerId); } catch (e) { }
        const paint = () => {
          const others = rows().filter(r => +r.dataset.i !== from);
          rows().forEach(r => r.classList.remove("droprow", "droprow-end"));
          if (dnd.to === from) return;
          if (others[dnd.to]) others[dnd.to].classList.add("droprow");
          else if (others.length) others[others.length - 1].classList.add("droprow-end");
        };
        const move = e => {
          if (!dnd) return;
          let to = 0;
          rows().forEach(r => {
            if (+r.dataset.i === from) return;
            const b = r.getBoundingClientRect();
            if (e.clientY > b.top + b.height / 2) to++;
          });
          if (to === dnd.to) return;
          dnd.to = to;
          paint();
        };
        const up = () => {
          h.removeEventListener("pointermove", move);
          h.removeEventListener("pointerup", up);
          h.removeEventListener("pointercancel", up);
          const d = dnd;
          dnd = null;
          if (d && d.to !== d.from)
            RD.send({ type: "walk_move", set: act.id, leg, index: d.from,
                      delta: d.to - d.from });
          sig = null;
          render(lastState, lastLeg);
        };
        h.addEventListener("pointermove", move);
        h.addEventListener("pointerup", up);
        h.addEventListener("pointercancel", up);
      });
    });
  }

  function busy(host) {
    if (dnd) return true;
    const a = document.activeElement;
    return !!(a && host && host.contains(a) &&
      (a.tagName === "INPUT" || a.tagName === "SELECT"));
  }

  return {
    render: (state, leg) => { if (!busy(el("pts-panel"))) render(state, leg); },
    overlay, ghost, nearest, crossAt, moveTo, addAt, removeAt,
    kneeAt, kOf, bandRun, pointsFor, activeId, thighExtent, kneeExtent,
  };
})();
