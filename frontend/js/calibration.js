window.CAL = (function () {
  const LEG_ORDER = ["FR", "FL", "BR", "BL"];
  const LEG_NAMES = { FR: "Front-Right", FL: "Front-Left",
                      BR: "Back-Right", BL: "Back-Left" };

  const CHART_H = 320, CHART_H_SM = 240;
  const PAD = { l: 52, r: 14, t: 28, b: 34 };
  const DEL_Y = 11;
  const AXIS_PAD = 0.05, AXIS_PAD_MIN = 20;
  const GRAB_R = 26;
  const GRAB_PT = 13;

  let leg = null;
  let last = null;
  let built = false;
  let wired = false;
  let mode = "move";
  let dragging = false;
  let dragPoint = null;
  let dragWP = null;
  let drawing = false;
  let sliderDrag = null;
  let hwDrag = null;
  let pulseHeld = false;
  let geom = null;
  let tableSig = null;
  let cardSig = null;
  let quadSig = null;

  const CAL_VIEW_KEY = "suki.calview";
  let calView = localStorage.getItem(CAL_VIEW_KEY) === "compact" ? "compact" : "list";

  const VIEW_KEY = "suki.hwview";
  let hwView = localStorage.getItem(VIEW_KEY) === "compact" ? "compact" : "list";
  const LEG_QUAD = ["FL", "FR", "BL", "BR"];
  const JOINT_ORDER = { thigh: 0, knee: 1, hip: 2 };

  let pendingPair = null, pendingPoint = null, pendingTest = {};
  setInterval(() => {
    if (pendingPair) {
      const p = pendingPair; pendingPair = null;
      RD.send(Object.assign({ type: "leg_pair" }, p));
    }
    if (pendingPoint) {
      const p = pendingPoint; pendingPoint = null;
      RD.send(Object.assign({ type: "corridor_point" }, p));
    }
    Object.keys(pendingTest).forEach(ch => {
      RD.send({ type: "servo_test", ch: +ch, us: pendingTest[ch] });
      delete pendingTest[ch];
    });
  }, 50);

  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const f1 = (n) => (Math.round(n * 10) / 10).toFixed(1);
  const jkey = (r) => `${r.leg}|${r.joint}`;

  function rowsByCh(state) {
    const m = {};
    (state.servos || []).forEach(r => (m[r.ch] = r));
    return m;
  }

  function legPair(state, which) {
    const rep = (state.legs || {})[which];
    if (!rep) return null;
    const rows = rowsByCh(state);
    return { rep, thigh: rows[rep.thigh_ch], knee: rows[rep.knee_ch] };
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

  function clampToBand(band, thigh, knee) {
    const bx = bandRun(band, thigh);
    if (bx) thigh = Math.max(bx[0], Math.min(bx[1], thigh));
    const kb = bandAt(band, thigh);
    if (kb) knee = Math.max(kb[0], Math.min(kb[1], knee));
    return [Math.round(thigh), Math.round(knee)];
  }

  function axisRange(span, live, also) {
    let lo = span[0], hi = span[1];
    if (live != null) { lo = Math.min(lo, live); hi = Math.max(hi, live); }
    if (also) { lo = Math.min(lo, also[0]); hi = Math.max(hi, also[1]); }
    if (hi <= lo) hi = lo + 1;
    const pad = Math.max(AXIS_PAD_MIN, (hi - lo) * AXIS_PAD);
    return [lo - pad, hi + pad];
  }

  function buildGeom(host, rep, thigh, knee, alsoX, alsoY) {
    const W = Math.max(320, host.clientWidth || 560);
    const H = W < 460 ? CHART_H_SM : CHART_H;
    const xr = axisRange(rep.thigh_span, thigh.us, alsoX);
    const yr = axisRange(rep.knee_span, knee.us, alsoY);
    const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
    const c01 = v => Math.max(0, Math.min(1, v));
    return {
      W, H, xr, yr, iw, ih,
      sx: v => PAD.l + c01((v - xr[0]) / (xr[1] - xr[0])) * iw,
      sy: v => PAD.t + (1 - c01((v - yr[0]) / (yr[1] - yr[0]))) * ih,
      ux: px => xr[0] + ((px - PAD.l) / iw) * (xr[1] - xr[0]),
      uy: py => yr[0] + (1 - (py - PAD.t) / ih) * (yr[1] - yr[0]),
    };
  }

  function ticks(lo, hi, n) {
    const raw = (hi - lo) / n;
    const mag = Math.pow(10, Math.floor(Math.log10(raw)));
    const step = [1, 2, 2.5, 5, 10].map(m => m * mag).find(s => s >= raw) || mag * 10;
    const out = [];
    for (let v = Math.ceil(lo / step) * step; v <= hi; v += step) out.push(v);
    return out;
  }

  function chartSVG(rep, thigh, knee, g) {
    const p = [];
    ticks(g.xr[0], g.xr[1], 5).forEach(v => {
      const x = f1(g.sx(v));
      p.push(`<line x1="${x}" y1="${PAD.t}" x2="${x}" y2="${g.H - PAD.b}"
        stroke="var(--line)" stroke-width="1" stroke-opacity="0.5"/>`);
      p.push(`<text x="${x}" y="${g.H - PAD.b + 16}" font-size="10" fill="var(--muted)"
        text-anchor="middle">${Math.round(v)}</text>`);
    });
    ticks(g.yr[0], g.yr[1], 5).forEach(v => {
      const y = f1(g.sy(v));
      p.push(`<line x1="${PAD.l}" y1="${y}" x2="${g.W - PAD.r}" y2="${y}"
        stroke="var(--line)" stroke-width="1" stroke-opacity="0.5"/>`);
      p.push(`<text x="${PAD.l - 7}" y="${f1(+y + 3.5)}" font-size="10"
        fill="var(--muted)" text-anchor="end">${Math.round(v)}</text>`);
    });
    p.push(`<text x="${PAD.l + g.iw / 2}" y="${g.H - 4}" font-size="10"
      fill="var(--muted)" text-anchor="middle">thigh µs</text>`);
    p.push(`<text x="12" y="${PAD.t + g.ih / 2}" font-size="10" fill="var(--muted)"
      text-anchor="middle" transform="rotate(-90 12 ${PAD.t + g.ih / 2})">knee µs</text>`);

    if (window.SK) p.push(window.SK.overlay(last, leg, g));

    (rep.safe_band || []).forEach(run => {
      const top = run.map(n => `${f1(g.sx(n[0]))},${f1(g.sy(n[2]))}`);
      const bot = run.slice().reverse().map(n => `${f1(g.sx(n[0]))},${f1(g.sy(n[1]))}`);
      p.push(`<polygon points="${top.concat(bot).join(" ")}" fill="var(--warn)"
        fill-opacity="0.18" stroke="var(--warn)" stroke-opacity="0.6"
        stroke-width="1"/>`);
    });

    const pts = (rep.points || []).slice().sort((a, b) => a.drive - b.drive);
    if (pts.length > 1) {
      p.push(`<polyline points="${pts.map(n => `${f1(g.sx(n.drive))},${f1(g.sy(n.max))}`)
        .join(" ")}" fill="none" stroke="var(--accent2)" stroke-width="1.4"/>`);
      p.push(`<polyline points="${pts.map(n => `${f1(g.sx(n.drive))},${f1(g.sy(n.min))}`)
        .join(" ")}" fill="none" stroke="var(--accent)" stroke-width="1.4"/>`);
    }
    const edit = mode === "edit";
    const passive = mode !== "move";
    pts.forEach((n, i) => {
      const x = f1(g.sx(n.drive));
      p.push(`<line x1="${x}" y1="${f1(g.sy(n.min))}" x2="${x}" y2="${f1(g.sy(n.max))}"
        stroke="var(--line)" stroke-width="1"/>`);
      p.push(`<circle class="cpt" data-i="${i}" data-w="max" cx="${x}"
        cy="${f1(g.sy(n.max))}" r="${edit ? 7 : 4}" fill="var(--accent2)"
        stroke="var(--bg)" stroke-width="1.5"/>`);
      p.push(`<circle class="cpt" data-i="${i}" data-w="min" cx="${x}"
        cy="${f1(g.sy(n.min))}" r="${edit ? 7 : 4}" fill="var(--accent)"
        stroke="var(--bg)" stroke-width="1.5"/>`);
      if (edit && pts.length > 2) {
        p.push(`<circle class="cdel" data-i="${i}" cx="${x}" cy="${DEL_Y}" r="8"
          fill="var(--panel)" stroke="var(--bad)" stroke-width="1"/>`);
        p.push(`<text class="cdel" data-i="${i}" x="${x}" y="${DEL_Y + 4}"
          font-size="11" fill="var(--bad)" text-anchor="middle">×</text>`);
      }
    });

    if (window.PTS) p.push(window.PTS.overlay(last, leg, g, rep, mode === "points"));

    const cx = f1(g.sx(thigh.us)), cy = f1(g.sy(knee.us));
    const inside = !(thigh.outside || knee.outside);
    const col = inside ? "var(--good)" : "var(--bad)";
    p.push(`<line class="xh" x1="${cx}" y1="${PAD.t}" x2="${cx}" y2="${g.H - PAD.b}"
      stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>`);
    p.push(`<line class="yh" x1="${PAD.l}" y1="${cy}" x2="${g.W - PAD.r}" y2="${cy}"
      stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"/>`);
    p.push(`<circle class="halo" cx="${cx}" cy="${cy}" r="15" fill="none" stroke="${col}"
      stroke-opacity="${passive ? 0 : 0.35}" stroke-width="2"/>`);
    p.push(`<circle class="dot" cx="${cx}" cy="${cy}" r="${passive ? 4 : 7}"
      fill="${passive ? "none" : col}" stroke="${passive ? col : "var(--bg)"}"
      stroke-width="2"/>`);

    return `<svg viewBox="0 0 ${g.W} ${g.H}" width="100%" height="${g.H}"
      class="cal-svg" style="touch-action:none">
      <rect x="${PAD.l}" y="${PAD.t}" width="${g.iw}" height="${g.ih}" rx="4"
        fill="var(--panel2)" stroke="var(--line)"/>${p.join("")}</svg>`;
  }

  function svgPoint(svg, ev) {
    const r = svg.getBoundingClientRect();
    if (!r.width || !r.height) return null;
    return [(ev.clientX - r.left) * (geom.W / r.width),
            (ev.clientY - r.top) * (geom.H / r.height)];
  }

  function moveDot(svg, thigh, knee) {
    const x = f1(geom.sx(thigh)), y = f1(geom.sy(knee));
    const set = (sel, attrs) => {
      const n = svg.querySelector(sel);
      if (n) Object.keys(attrs).forEach(k => n.setAttribute(k, attrs[k]));
    };
    set(".dot", { cx: x, cy: y });
    set(".halo", { cx: x, cy: y });
    set(".xh", { x1: x, x2: x });
    set(".yh", { y1: y, y2: y });
    const rd = el("readout-live");
    if (rd) rd.textContent = `${Math.round(thigh)} / ${Math.round(knee)} µs`;
  }

  function grabPoint(rep, pt) {
    let best = null, bestd = GRAB_PT;
    (rep.points || []).forEach((n, i) => {
      ["min", "max"].forEach(w => {
        const d = Math.hypot(pt[0] - geom.sx(n.drive), pt[1] - geom.sy(n[w]));
        if (d <= bestd) { bestd = d; best = { index: i, which: w, d }; }
      });
    });
    return best;
  }

  function nearestDel(rep, pt) {
    if (mode !== "edit" || (rep.points || []).length <= 2) return null;
    if (pt[1] > PAD.t) return null;
    let best = null, bestd = 14;
    rep.points.forEach((n, i) => {
      const d = Math.hypot(pt[0] - geom.sx(n.drive), pt[1] - DEL_Y);
      if (d <= bestd) { bestd = d; best = i; }
    });
    return best;
  }

  function wireChart(svg, rep) {
    const stop = () => {
      if (!dragging && !dragPoint && dragWP === null && !drawing) return;
      if (drawing && window.SK) SK.end(leg);
      drawing = false;
      dragging = false;
      dragPoint = null;
      dragWP = null;
      RD.release(stop);
      render(last);
    };
    const inPlot = (pt) => pt[0] >= PAD.l && pt[0] <= geom.W - PAD.r &&
                           pt[1] >= PAD.t && pt[1] <= geom.H - PAD.b;

    svg.addEventListener("pointerdown", (ev) => {
      const pt = svgPoint(svg, ev);
      if (!pt || !last || !rep.ok || last.test) return;
      const pair = legPair(last, leg);
      if (!pair) return;

      if (mode === "draw") {
        if (!window.SK) return;
        if (SK.tool() === "erase") {
          ev.preventDefault();
          SK.eraseAt(last, leg, geom, pt);
          return;
        }
        if (!inPlot(pt)) return;
        ev.preventDefault();
        drawing = true;
        SK.start(geom.ux(pt[0]), geom.uy(pt[1]));
      } else if (mode === "points") {
        if (!window.PTS) return;
        const del = PTS.crossAt(last, leg, geom, pt, rep, PAD.t);
        if (del !== null) {
          ev.preventDefault();
          PTS.removeAt(last, leg, del);
          return;
        }
        const hit = PTS.nearest(last, leg, geom, pt, rep);
        if (hit !== null) {
          ev.preventDefault();
          dragWP = hit;
        } else if (inPlot(pt)) {
          ev.preventDefault();
          PTS.addAt(last, leg, geom.ux(pt[0]), geom.uy(pt[1]), rep);
          return;
        } else {
          return;
        }
      } else if (mode === "edit") {
        const del = nearestDel(rep, pt);
        if (del !== null) {
          ev.preventDefault();
          RD.send({ type: "corridor_delete", leg, index: del });
          return;
        }
        const hit = grabPoint(rep, pt);
        if (hit) {
          ev.preventDefault();
          dragPoint = hit;
        } else if (pt[0] >= PAD.l && pt[0] <= geom.W - PAD.r &&
                   pt[1] >= PAD.t && pt[1] <= geom.H - PAD.b) {
          ev.preventDefault();
          RD.send({ type: "corridor_add", leg, drive: Math.round(geom.ux(pt[0])) });
          return;
        } else {
          return;
        }
      } else {
        const dDot = Math.hypot(pt[0] - geom.sx(pair.thigh.us),
                                pt[1] - geom.sy(pair.knee.us));
        if (dDot > GRAB_R) return;
        ev.preventDefault();
        dragging = true;
      }
      RD.hold(stop);
      try { svg.setPointerCapture(ev.pointerId); } catch (e) { }
    });

    svg.addEventListener("pointermove", (ev) => {
      if (!dragging && !dragPoint && dragWP === null && !drawing) return;
      const pt = svgPoint(svg, ev);
      if (!pt) return;

      if (drawing) {
        if (window.SK && SK.move(geom.ux(pt[0]), geom.uy(pt[1])))
          SK.livePath(svg, last, geom);
        return;
      }

      if (dragWP !== null) {
        const res = PTS.moveTo(last, leg, dragWP, geom.ux(pt[0]), geom.uy(pt[1]), rep);
        if (res && res[1] != null)
          PTS.ghost(svg, dragWP, geom.sx(res[0]), geom.sy(res[1]));
        return;
      }

      if (dragPoint) {
        const msg = { leg, index: dragPoint.index,
                      drive: Math.round(geom.ux(pt[0])) };
        msg[dragPoint.which] = Math.round(geom.uy(pt[1]));
        pendingPoint = msg;
        const h = svg.querySelector(
          `.cpt[data-i="${dragPoint.index}"][data-w="${dragPoint.which}"]`);
        if (h) {
          h.setAttribute("cx", f1(geom.sx(msg.drive)));
          h.setAttribute("cy", f1(geom.sy(msg[dragPoint.which])));
        }
        return;
      }

      const p = clampToBand(rep.safe_band, geom.ux(pt[0]), geom.uy(pt[1]));
      pendingPair = { leg, thigh: p[0], knee: p[1] };
      moveDot(svg, p[0], p[1]);
    });

    ["pointerup", "pointercancel", "pointerleave"].forEach(
      e => svg.addEventListener(e, stop));
  }

  function sliderRow(row, label) {
    return `<div class="srow" data-ch="${row.ch}">
      <div class="sh"><b>${esc(label)}</b>
        <span class="sv" data-v="${row.ch}">${row.us} µs</span></div>
      <input type="range" class="sr" data-ch="${row.ch}"
        min="${row.lo}" max="${row.hi}" step="1" value="${row.us}"/>
      <div class="sf">
        <span class="muted" data-w="${row.ch}">window ${row.lo}–${row.hi} µs</span>
        <label class="inv"><input type="checkbox" class="invcb" data-ch="${row.ch}"
          ${row.invert ? "checked" : ""}/> inverted</label>
      </div>
    </div>`;
  }

  function buildSliders(pair) {
    const host = el("sliders");
    host.innerHTML =
      sliderRow(pair.thigh, "Thigh · ch" + pair.thigh.ch) +
      sliderRow(pair.knee, "Knee · ch" + pair.knee.ch) +
      `<div class="readout">
         <div><span class="muted">now</span>
           <b id="readout-live">${pair.thigh.us} / ${pair.knee.us} µs</b></div>
         <div><span class="muted">thigh range</span>
           <b id="readout-t">--</b></div>
         <div><span class="muted">knee window here</span>
           <b id="readout-k">--</b></div>
       </div>`;

    host.querySelectorAll(".sr").forEach(sl => {
      const ch = +sl.dataset.ch;
      const isThigh = ch === pair.thigh.ch;
      const stop = () => {
        if (sliderDrag !== ch) return;
        sliderDrag = null;
        RD.release(stop);
      };
      sl.addEventListener("pointerdown", () => { sliderDrag = ch; RD.hold(stop); });
      ["pointerup", "pointercancel", "blur"].forEach(e => sl.addEventListener(e, stop));
      sl.addEventListener("input", () => {
        sliderDrag = ch;
        RD.hold(stop);
        const v = +sl.value;
        const msg = { leg };
        msg[isThigh ? "thigh" : "knee"] = v;
        pendingPair = msg;
        const lbl = host.querySelector(`[data-v="${ch}"]`);
        if (lbl) lbl.textContent = v + " µs";
      });
      sl.addEventListener("change", stop);
    });

    host.querySelectorAll(".invcb").forEach(cb => {
      cb.addEventListener("change", () => {
        RD.send({ type: "servo_config", ch: +cb.dataset.ch, invert: cb.checked });
      });
    });
  }

  function updateSliders(pair) {
    const host = el("sliders");
    const frozen = !!(last && last.test);
    [pair.thigh, pair.knee].forEach(row => {
      const sl = host.querySelector(`.sr[data-ch="${row.ch}"]`);
      if (!sl) return;
      sl.disabled = frozen;
      if (sliderDrag !== row.ch) {
        sl.min = row.lo; sl.max = row.hi; sl.value = row.us;
        const lbl = host.querySelector(`[data-v="${row.ch}"]`);
        if (lbl) lbl.textContent = row.us + " µs";
      }
      const w = host.querySelector(`[data-w="${row.ch}"]`);
      if (w) {
        w.textContent = `window ${row.lo}–${row.hi} µs`;
        w.classList.toggle("bad", !!row.outside);
      }
      const cb = host.querySelector(`.invcb[data-ch="${row.ch}"]`);
      if (cb && document.activeElement !== cb) cb.checked = !!row.invert;
    });
    if (!dragging) {
      const rd = el("readout-live");
      if (rd) rd.textContent = `${pair.thigh.us} / ${pair.knee.us} µs`;
    }
    const rt = el("readout-t"), rk = el("readout-k");
    if (rt) rt.textContent = pair.rep.thigh_span
      ? `${pair.rep.thigh_span[0]}–${pair.rep.thigh_span[1]} µs` : "--";
    if (rk) rk.textContent = pair.rep.knee_window
      ? `${pair.rep.knee_window[0]}–${pair.rep.knee_window[1]} µs` : "--";
  }

  function renderTable(state) {
    const t = el("stable");
    if (!t) return;
    const span = state.test_span || [500, 2500];
    const testOn = !!state.test;
    const opts = (state.channels || []).map(c =>
      `<option value="${c.ch}">ch ${c.ch}${c.name ? " · " + esc(c.name) : " · free"}` +
      `</option>`).join("");
    const sig = (state.servos || []).map(r => jkey(r)).join(",");
    if (sig !== tableSig) {
      tableSig = sig;
      t.innerHTML =
        `<tr><th>motor</th><th>channel</th><th>µs</th><th>on wire</th>
         <th>min</th><th>max</th><th>inverted</th><th>on</th>
         <th class="hwt">test ${span[0]}–${span[1]} µs</th></tr>` +
        (state.servos || []).map(r => {
          const j = jkey(r);
          return `<tr data-j="${j}">
            <td>${esc(r.name)}</td>
            <td><select class="hw-slot" data-j="${j}">${opts}</select></td>
            <td class="mono" data-us="${j}">${r.us}</td>
            <td class="mono" data-ph="${j}">${r.phys}</td>
            <td><input type="number" class="hw-min mono" data-j="${j}"
                 min="500" max="2500" step="1"/></td>
            <td><input type="number" class="hw-max mono" data-j="${j}"
                 min="500" max="2500" step="1"/></td>
            <td><input type="checkbox" class="hw-inv" data-j="${j}"/></td>
            <td><input type="checkbox" class="hw-on" data-j="${j}"/></td>
            <td class="hwt"><input type="range" class="hw-test" data-j="${j}"
                 min="${span[0]}" max="${span[1]}" step="1" disabled/></td>
          </tr>`; }).join("");
      const chOf = (n) => +n.dataset.ch;

      t.querySelectorAll(".hw-test").forEach(sl => {
        const j = sl.dataset.j;
        const stop = () => {
          if (hwDrag !== j) return;
          hwDrag = null;
          RD.release(stop);
        };
        sl.addEventListener("pointerdown", () => { hwDrag = j; RD.hold(stop); });
        ["pointerup", "pointercancel", "blur", "change"].forEach(
          e => sl.addEventListener(e, stop));
        sl.addEventListener("input", () => {
          hwDrag = j;
          RD.hold(stop);
          pendingTest[chOf(sl)] = +sl.value;
          const us = t.querySelector(`[data-us="${j}"]`);
          if (us) us.textContent = sl.value;
        });
      });
      t.querySelectorAll(".hw-slot").forEach(sel => {
        sel.addEventListener("change", () => {
          const [leg, joint] = sel.dataset.j.split("|");
          const to = sel.options[sel.selectedIndex].textContent;
          const name = sel.closest("tr").firstElementChild.textContent;
          if (!window.confirm(
                `Move ${name} to ${to}?\n\n` +
                "It swaps places with whatever is on that channel now, and takes its " +
                "min/max, inverted, position and saved poses with it.\n\n" +
                "The whole robot goes limp first — the two outputs are about to " +
                "carry each other's pulse.")) {
            sel.value = sel.dataset.ch;
            return;
          }
          RD.releaseAll();
          RD.send({ type: "channel_map", ch: +sel.value, leg, joint });
        });
      });
      t.querySelectorAll(".hw-inv").forEach(cb => cb.addEventListener("change", () =>
        RD.send({ type: "servo_config", ch: chOf(cb), invert: cb.checked })));
      t.querySelectorAll(".hw-on").forEach(cb => cb.addEventListener("change", () =>
        RD.send({ type: "servo_config", ch: chOf(cb), enabled: cb.checked })));
      [["hw-min", "min"], ["hw-max", "max"]].forEach(([cls, key]) =>
        t.querySelectorAll("." + cls).forEach(inp =>
          inp.addEventListener("change", () => {
            const v = parseInt(inp.value, 10);
            if (isFinite(v)) RD.send({ type: "servo_config", ch: chOf(inp), [key]: v });
          })));
    }
    (state.servos || []).forEach(r => {
      const j = jkey(r);
      t.querySelectorAll(`[data-j="${j}"]`).forEach(n => (n.dataset.ch = r.ch));

      const us = t.querySelector(`[data-us="${j}"]`);
      if (us && hwDrag !== j) {
        us.textContent = r.us; us.className = "mono" + (r.outside ? " bad" : "");
      }
      const ph = t.querySelector(`[data-ph="${j}"]`);
      if (ph) {
        ph.textContent = r.phys + (r.edge ? " ⚠" : "");
        ph.className = "mono" + (r.edge ? " bad" : r.edge_span ? " warn" : "");
        ph.title = r.edge
          ? "AT THE END STOP — this servo is being pushed, not held. It will stall, "
            + "heat, and drag the rail down. Pull this channel's min/max in."
          : r.edge_span
          ? "this joint's allowed range reaches the end of the servo's travel"
          : "the pulse on the wire";
      }
      [["hw-min", "min"], ["hw-max", "max"]].forEach(([cls, key]) => {
        const inp = t.querySelector(`.${cls}[data-j="${j}"]`);
        if (inp && document.activeElement !== inp) inp.value = r[key];
      });
      const inv = t.querySelector(`.hw-inv[data-j="${j}"]`);
      if (inv && document.activeElement !== inv) inv.checked = !!r.invert;
      const on = t.querySelector(`.hw-on[data-j="${j}"]`);
      if (on && document.activeElement !== on) on.checked = !!r.enabled;
      const sel = t.querySelector(`.hw-slot[data-j="${j}"]`);
      if (sel) {
        if (sel.innerHTML !== opts && document.activeElement !== sel) {
          sel.innerHTML = opts;
        }
        if (document.activeElement !== sel) sel.value = String(r.ch);
      }
      const sl = t.querySelector(`.hw-test[data-j="${j}"]`);
      if (sl) {
        sl.disabled = !(testOn && r.energised);
        sl.title = !testOn ? "arm the hardware test to move this"
          : r.energised ? "drives this channel directly — no corridor, no min/max"
          : r.enabled ? "the driver is not holding this channel"
          : "switch this channel on first";
        if (hwDrag !== j) {
          sl.min = span[0]; sl.max = span[1]; sl.value = r.us;
        }
      }
      const tr = t.querySelector(`tr[data-j="${j}"]`);
      if (tr) tr.className = r.edge ? "atedge" : r.energised ? "live" : "";
    });
  }

  function jointsOf(state, leg) {
    return (state.servos || []).filter(r => r.leg === leg)
      .sort((a, b) => (JOINT_ORDER[a.joint] === undefined ? 9 : JOINT_ORDER[a.joint]) -
                      (JOINT_ORDER[b.joint] === undefined ? 9 : JOINT_ORDER[b.joint]));
  }

  function jointHTML(r, span) {
    const j = jkey(r);
    return `<div class="jrow" data-j="${j}">
      <div class="jh">
        <b class="jn">${esc(r.joint)}</b>
        <span class="jch mono" data-chl="${j}">ch ${r.ch}</span>
        <span class="grow"></span>
        <span class="jus mono" data-us="${j}">${r.us}</span>
      </div>
      <div class="jbar"><div class="jcfg" data-cfg="${j}"></div>
        <div class="jwin" data-win="${j}"></div>
        <div class="jmark" data-mk="${j}"></div></div>
      <div class="jf">
        <span class="jw mono" data-w="${j}"></span>
        <span class="jphys mono" data-ph="${j}"></span>
        <span class="grow"></span>
        <label class="jt"><input type="checkbox" class="c-on" data-j="${j}"/> on</label>
        <label class="jt"><input type="checkbox" class="c-inv" data-j="${j}"/> inv</label>
      </div>
      <input type="range" class="jtest" data-j="${j}" min="${span[0]}" max="${span[1]}"
             step="1" disabled/>
    </div>`;
  }

  function renderCards(state) {
    const host = el("hw-cards");
    if (!host) return;
    const span = state.test_span || [500, 2500];
    const testOn = !!state.test;

    const sig = (state.servos || []).map(r => jkey(r)).join(",");
    if (sig !== cardSig) {
      cardSig = sig;
      host.innerHTML = LEG_QUAD.filter(l => jointsOf(state, l).length).map(leg =>
        `<div class="lcard" data-leg="${leg}">
          <div class="lc-h">
            <span class="lc-dot" data-dot="${leg}"></span>
            <b>${esc(LEG_NAMES[leg] || leg)}</b>
            <span class="grow"></span>
            <span class="legstate lc-state" data-st="${leg}">--</span>
          </div>
          ${jointsOf(state, leg).map(r => jointHTML(r, span)).join("")}
          <div class="lc-f muted small" data-cf="${leg}"></div>
        </div>`).join("");

      const chOf = (n) => +n.dataset.ch;
      host.querySelectorAll(".c-on").forEach(cb => cb.addEventListener("change", () =>
        RD.send({ type: "servo_config", ch: chOf(cb), enabled: cb.checked })));
      host.querySelectorAll(".c-inv").forEach(cb => cb.addEventListener("change", () =>
        RD.send({ type: "servo_config", ch: chOf(cb), invert: cb.checked })));
      host.querySelectorAll(".jtest").forEach(sl => {
        const j = sl.dataset.j;
        const stop = () => {
          if (hwDrag !== j) return;
          hwDrag = null;
          RD.release(stop);
        };
        sl.addEventListener("pointerdown", () => { hwDrag = j; RD.hold(stop); });
        ["pointerup", "pointercancel", "blur", "change"].forEach(
          e => sl.addEventListener(e, stop));
        sl.addEventListener("input", () => {
          hwDrag = j;
          RD.hold(stop);
          pendingTest[chOf(sl)] = +sl.value;
          const us = host.querySelector(`[data-us="${j}"]`);
          if (us) us.textContent = sl.value;
        });
      });
    }

    const pct = (v) => Math.max(0, Math.min(100,
      (v - span[0]) / (span[1] - span[0]) * 100));

    (state.servos || []).forEach(r => {
      const j = jkey(r);
      host.querySelectorAll(`[data-j="${j}"]`).forEach(n => (n.dataset.ch = r.ch));
      const q = (sel) => host.querySelector(sel);

      const lbl = q(`[data-chl="${j}"]`);
      if (lbl) lbl.textContent = "ch " + r.ch;
      const us = q(`[data-us="${j}"]`);
      if (us && hwDrag !== j) {
        us.textContent = r.us;
        us.className = "jus mono" + (r.outside ? " bad" : "");
      }
      const cfg = q(`[data-cfg="${j}"]`);
      if (cfg) {
        cfg.style.left = pct(r.min) + "%";
        cfg.style.width = Math.max(0, pct(r.max) - pct(r.min)) + "%";
      }
      const win = q(`[data-win="${j}"]`);
      if (win) {
        win.style.left = pct(r.lo) + "%";
        win.style.width = Math.max(0, pct(r.hi) - pct(r.lo)) + "%";
      }
      const mk = q(`[data-mk="${j}"]`);
      if (mk) mk.style.left = pct(r.us) + "%";

      const w = q(`[data-w="${j}"]`);
      if (w) {
        w.textContent = `${r.lo}–${r.hi}`;
        w.className = "jw mono" + (r.outside ? " bad" : "");
      }
      const ph = q(`[data-ph="${j}"]`);
      if (ph) {
        ph.textContent = "wire " + r.phys + (r.edge ? " ⚠" : "");
        ph.className = "jphys mono" + (r.edge ? " bad" : r.edge_span ? " warn" : "");
        ph.title = r.edge
          ? "AT THE END STOP — this servo is being pushed, not held. Pull this "
            + "channel's min/max in, in the list view."
          : "the pulse on the wire";
      }
      const on = q(`.c-on[data-j="${j}"]`);
      if (on && document.activeElement !== on) on.checked = !!r.enabled;
      const inv = q(`.c-inv[data-j="${j}"]`);
      if (inv && document.activeElement !== inv) inv.checked = !!r.invert;

      const sl = q(`.jtest[data-j="${j}"]`);
      if (sl) {
        sl.classList.toggle("hidden", !testOn);
        sl.disabled = !(testOn && r.energised);
        sl.title = !testOn ? "arm the hardware test in the list view to move this"
          : r.energised ? "drives this channel directly — no corridor, no min/max"
          : "this channel is not being held";
        if (hwDrag !== j) { sl.min = span[0]; sl.max = span[1]; sl.value = r.us; }
      }
      const blk = q(`.jrow[data-j="${j}"]`);
      if (blk) blk.className = "jrow" + (r.edge ? " atedge" : "") +
        (r.enabled ? "" : " off") + (r.energised ? " live" : "");
    });

    LEG_QUAD.forEach(leg => {
      const rows = jointsOf(state, leg);
      if (!rows.length) return;
      const rep = (state.legs || {})[leg];
      const drive = rows.filter(r => r.joint !== "hip");
      const anyEdge = rows.some(r => r.edge);
      const offs = drive.filter(r => !r.enabled).length;
      const held = drive.length && drive.every(r => r.energised);
      let txt = "limp", cls = "";
      if (state.estop) { txt = "E-STOP"; cls = "bad"; }
      else if (anyEdge) { txt = "at the end stop"; cls = "bad"; }
      else if (offs) { txt = offs + " switched off"; cls = "bad"; }
      else if (held) { txt = "holding"; cls = "ok"; }
      const st = host.querySelector(`[data-st="${leg}"]`);
      if (st) { st.textContent = txt; st.className = "legstate lc-state " + cls; }
      const dot = host.querySelector(`[data-dot="${leg}"]`);
      if (dot) dot.className = "lc-dot " + (cls || (held ? "ok" : ""));
      const cf = host.querySelector(`[data-cf="${leg}"]`);
      if (cf) {
        cf.innerHTML = !rep ? "no leg report"
          : !rep.ok ? '<span class="bad">no measured corridor</span>'
          : `corridor <b class="mono">${rep.thigh_span[0]}–${rep.thigh_span[1]}</b> thigh`
            + (rep.knee_window
               ? ` · knee here <b class="mono">${rep.knee_window[0]}–${rep.knee_window[1]}</b>`
               : "");
      }
    });
  }

  function renderHardware(state) {
    if (hwView === "compact") renderCards(state);
    else renderTable(state);
  }

  function setView(v) {
    hwView = v === "compact" ? "compact" : "list";
    localStorage.setItem(VIEW_KEY, hwView);
    RD.releaseAll();
    hwDrag = null;
    tableSig = null;
    cardSig = null;
    const tog = (id, on) => {
      const n = el(id);
      if (n) n.classList.toggle("hidden", !on);
    };
    document.querySelectorAll("#hw-view .mbtn").forEach(b =>
      b.classList.toggle("active", b.dataset.v === hwView));
    tog("hw-list", hwView === "list");
    tog("hw-help-list", hwView === "list");
    tog("hw-cards", hwView === "compact");
    tog("hw-help-cards", hwView === "compact");
    if (last) renderHardware(last);
  }

  function buildOnce(state) {
    const pick = el("leg-pick");
    const known = LEG_ORDER.filter(l => (state.legs || {})[l]);
    if (!known.length) return;
    wired = true;
    pick.innerHTML = known
      .map(l => `<option value="${l}">${LEG_NAMES[l]}</option>`).join("");
    leg = leg || pick.value || LEG_ORDER[0];
    pick.value = leg;
    pick.addEventListener("change", () => {
      leg = pick.value;
      built = false;
      render(last);
    });
    el("leg-hold").addEventListener("click", () => {
      const p = last && legPair(last, leg);
      const on = p && p.thigh.energised && p.knee.energised;
      RD.send({ type: on ? "relax" : "engage", leg });
    });

    const tbtn = el("hw-test");
    if (tbtn) tbtn.addEventListener("click", () => {
      const on = !!(last && last.test);
      if (!on && !window.confirm(
            "Arm the hardware test?\n\n" +
            "• the sliders will drive each channel across the raw 500–2500 µs range, " +
            "with NO corridor and NO min/max\n" +
            "• every switched-on channel is engaged NOW, at the position the software " +
            "thinks it is at — a limp joint will snap there\n" +
            "• the leg chart and its sliders are off until you stop the test\n\n" +
            "E-STOP and the speed limiter still apply.")) return;
      RD.releaseAll();
      RD.send({ type: "test_mode", on: !on });
    });

    const seg = el("hw-view");
    if (seg) {
      seg.innerHTML = [["list", "List"], ["compact", "Compact"]].map(([v, t]) =>
        `<button class="mbtn${v === hwView ? " active" : ""}" data-v="${v}"
          type="button">${t}</button>`).join("");
      seg.querySelectorAll(".mbtn").forEach(b =>
        b.addEventListener("click", () => setView(b.dataset.v)));
      setView(hwView);
    }

    const cv = el("cal-view");
    if (cv && !cv.children.length) {
      cv.innerHTML = [["list", "List"], ["compact", "Compact"]].map(([v, t]) =>
        `<button class="mbtn" data-v="${v}" type="button">${t}</button>`).join("");
      cv.querySelectorAll(".mbtn").forEach(b =>
        b.addEventListener("click", () => setCalView(b.dataset.v)));
      setCalView(calView);
    }

    document.querySelectorAll("#chart-mode .mbtn").forEach(b =>
      b.addEventListener("click", () => {
        mode = b.dataset.mode;
        if (window.SK) SK.cancel();
        drawing = false;
        document.querySelectorAll("#chart-mode .mbtn").forEach(x =>
          x.classList.toggle("active", x === b));
        const pen = el("sk-panel");
        if (pen) pen.classList.toggle("hidden", mode !== "draw");
        render(last);
      }));

    [["pulse-us", "us"], ["pulse-ms", "delay_ms"]].forEach(([id, key]) => {
      const s = el(id);
      s.addEventListener("pointerdown", () => (pulseHeld = true));
      ["pointerup", "pointercancel", "blur", "change"].forEach(e =>
        s.addEventListener(e, () => (pulseHeld = false)));
      s.addEventListener("input", () => {
        pulseHeld = true;
        paintPulse(+el("pulse-us").value, +el("pulse-ms").value);
        RD.send({ type: "pulse", [key]: +s.value });
      });
    });
  }

  function paintPulse(us, ms) {
    el("pulse-us-v").textContent = us > 0 ? us + " µs" : "off";
    el("pulse-ms-v").textContent = ms > 0 ? ms + " ms" : "no gap";
  }

  const HELP = {
    move: "Drag the <b>green dot</b> to move the leg. Nothing else on this chart " +
      "commands anything — a press on empty space is ignored on purpose.",
    edit: "Drag a <b>handle</b> to reshape the measured corridor, press empty space to " +
      "add a thigh position, and the <b>×</b> above a column deletes it. This rewrites " +
      "the limits the robot enforces; it does not move the leg.",
    points: "Press inside the yellow to <b>add</b> a walking point, drag one to move " +
      "it, and the <b>×</b> above it deletes it. <b>The leg does not move.</b> The " +
      "vertical position is stored as a fraction of the band, so a point can never be " +
      "dragged outside it.",
    draw: "<b>Ink.</b> Draw on the chart with a finger — lines, arrows, a circle round " +
      "the bit you want to remember. It is kept on the robot and <b>read by nothing</b>: " +
      "a stroke never becomes a walking point, and it is not clamped to the yellow.",
  };

  function render(state) {
    if (!state) return;
    last = state;
    if (!wired) buildOnce(state);
    if (!wired) return;

    const testOn = !!state.test;
    const tb = el("hw-test");
    if (tb) {
      tb.textContent = testOn ? "Stop hardware test" : "Test hardware";
      tb.className = "btn" + (testOn ? " warn" : "");
    }
    const ts = el("hw-test-state");
    if (ts) {
      ts.textContent = testOn ? "ARMED — raw range, no corridor" : "off";
      ts.className = "legstate" + (testOn ? " bad" : "");
    }
    const tn = el("hw-test-note");
    if (!tn) {
    } else if (testOn) {
      tn.innerHTML = "<b>Hardware test armed.</b> Each slider drives its channel " +
        "anywhere in 500–2500 µs — the measured corridor and the min/max on this row " +
        "are <b>not</b> being enforced. <b>on wire</b> is the pulse the servo actually " +
        "sees; flip <b>inverted</b> to swap which way the slider turns it. Stopping " +
        "the test puts the limits back, and any leg left outside its corridor is made " +
        "limp rather than dragged back into it." +
        (state.test_note ? "<br><b>" + esc(state.test_note) + "</b>" : "");
    } else if (state.test_note) {
      tn.innerHTML = "<b>Hardware test:</b> " + esc(state.test_note);
    }
    if (tn) tn.classList.toggle("hidden", !(testOn || state.test_note));

    const pair = legPair(state, leg);
    if (!pair) return;
    const { rep, thigh, knee } = pair;

    const on = thigh.energised && knee.energised;
    const st = el("leg-state");
    if (!rep.ok) {
      st.className = "legstate bad";
      st.textContent = "no measured corridor — this leg cannot be driven";
    } else if (!thigh.enabled || !knee.enabled) {
      st.className = "legstate bad";
      st.textContent = "switched off";
    } else {
      st.className = "legstate " + (on ? "ok" : "");
      st.textContent = on ? "holding" : (state.estop ? "E-STOP" : "limp");
    }
    const warn = el("limp-warn");
    const limp = rep.ok && !on && mode === "move";
    const stuck = [thigh, knee].filter(j => j.edge);
    const reach = [thigh, knee].filter(j => j.edge_span && !j.edge);
    const offs = [thigh, knee].filter(j => !j.enabled);
    warn.classList.toggle("hidden",
      !(limp || stuck.length || reach.length || testOn || offs.length));
    if (offs.length && !testOn) {
      warn.innerHTML = "<b>" + offs.map(j => esc(j.name)).join(" and ") +
        (offs.length > 1 ? "</b> are" : "</b> is") + " switched <b>off</b>. " +
        "<b>Engage will do nothing</b> — off means the channel is deliberately held " +
        "limp, so it is skipped. Tick <b>on</b> for " +
        (offs.length > 1 ? "those rows" : "that row") +
        " in <b>Hardware</b> above, then press Engage.";
    } else if (stuck.length) {
      const fix = stuck.map(j => `<b>${esc(j.name)}</b>: ${j.phys} µs on the wire — ` +
        (j.phys < 1500 ? `raise its <b>min</b> above ${j.min}`
                       : `lower its <b>max</b> below ${j.max}`)).join("; ");
      warn.innerHTML = "<b>Against the servo's end stop.</b> A servo held at 500 or " +
        "2500 µs is <b>pushing, not holding</b> — it stalls, heats, drags the rail " +
        "down, and the leg will not move however hard you drag. " + fix +
        " (Hardware table above; the wire does not move when you change it.)";
    } else if (testOn) {
      warn.innerHTML = "<b>The hardware test is armed.</b> The chart and the two " +
        "sliders below are off while it is — the corridor they are drawn from is not " +
        "being enforced, so a command checked against it would be a promise this " +
        "program is not currently keeping. Stop the test in <b>Hardware</b> above.";
    } else if (limp) {
      warn.innerHTML = state.estop
        ? "<b>E-STOP is on.</b> Nothing will move until it is released."
        : "<b>This leg is limp — it will not move.</b> Press <b>Engage</b> above, or " +
          "<b>Return to last position</b>, first.";
    } else if (reach.length) {
      warn.innerHTML = "<b>" + reach.map(j => esc(j.name)).join(" and ") +
        "</b>: the allowed range reaches the end of the servo's electrical travel " +
        "(500 / 2500 µs). Driving to that end will stall the servo.";
    }

    const p = state.pulse || {};
    if (!pulseHeld) {
      const su = el("pulse-us"), sm = el("pulse-ms");
      su.max = p.us_max || 400;
      sm.min = p.delay_min_ms != null ? p.delay_min_ms : 0;
      sm.max = p.delay_max_ms || 200;
      su.value = p.us || 0; sm.value = p.delay_ms != null ? p.delay_ms : 50;
      paintPulse(+su.value, +sm.value);
    }
    el("pulse-state").textContent = !p.us ? "continuous — the speed limit alone"
      : p.active && (!p.pending || p.pending.length < 2)
        ? `${p.active} moving on its own — continuous, nothing to take turns with`
      : p.active ? `stepping ${p.active}` + (p.pending && p.pending.length > 1
          ? `, queued: ${p.pending.filter(l => l !== p.active).join(" ")}` : "")
      : (p.pending && p.pending.length) ? `waiting — next: ${p.pending.join(" ")}`
      : "idle";

    el("chart-help").innerHTML = HELP[mode];
    const hold = el("leg-hold");
    hold.textContent = on ? "Relax" : "Engage";
    hold.className = "btn" + (on ? " warn" : "");
    hold.title = on ? "cut torque so the leg can be posed by hand"
                    : "hold this leg where it is now";
    const note = el("leg-note");
    note.textContent = rep.note || "";
    note.classList.toggle("hidden", !rep.note);

    if (!built) {
      buildSliders(pair);
      built = true;
    }
    updateSliders(pair);
    renderHardware(state);
    if (window.PTS) PTS.render(state, leg);
    if (window.SK && mode === "draw") SK.render(state, leg);

    if (calView === "compact") {
      renderQuads(state);
      return;
    }

    if (!rep.ok) {
      el("chart").innerHTML = `<p class="muted empty-tab">This leg has no measured
        corridor, so there is nothing safe to draw and nothing safe to drive.</p>`;
      return;
    }
    if (dragging || dragPoint || dragWP !== null) return;
    const host = el("chart");
    geom = buildGeom(host, rep, thigh, knee,
                     window.PTS ? PTS.thighExtent(state, leg) : null,
                     window.PTS ? PTS.kneeExtent(state, leg) : null);
    host.innerHTML = chartSVG(rep, thigh, knee, geom);
    wireChart(host.querySelector("svg"), rep);
  }

  const QUAD_H = 168;
  const QPAD = { l: 34, r: 8, t: 10, b: 20 };

  function quadSVG(state, which, w) {
    const pair = legPair(state, which);
    if (!pair || !pair.rep || !pair.thigh || !pair.knee) return "";
    const rep = pair.rep;
    if (!rep.ok) {
      return `<div class="cq-empty muted small">no measured corridor</div>`;
    }
    const alsoX = window.PTS ? PTS.thighExtent(state, which) : null;
    const alsoY = window.PTS ? PTS.kneeExtent(state, which) : null;
    const xr = axisRange(rep.thigh_span, pair.thigh.us, alsoX);
    const yr = axisRange(rep.knee_span, pair.knee.us, alsoY);
    const iw = w - QPAD.l - QPAD.r, ih = QUAD_H - QPAD.t - QPAD.b;
    const c01 = (v) => Math.max(0, Math.min(1, v));
    const g = {
      W: w, H: QUAD_H, xr, yr, iw, ih,
      sx: (v) => QPAD.l + c01((v - xr[0]) / (xr[1] - xr[0])) * iw,
      sy: (v) => QPAD.t + (1 - c01((v - yr[0]) / (yr[1] - yr[0]))) * ih,
      ux: (px) => xr[0] + ((px - QPAD.l) / iw) * (xr[1] - xr[0]),
      uy: (py) => yr[0] + (1 - (py - QPAD.t) / ih) * (yr[1] - yr[0]),
    };
    const p = [];
    ticks(xr[0], xr[1], 2).forEach(v => {
      const x = f1(g.sx(v));
      p.push(`<line x1="${x}" y1="${QPAD.t}" x2="${x}" y2="${QUAD_H - QPAD.b}"
        stroke="var(--line)" stroke-width="1" stroke-opacity="0.4"/>`);
      p.push(`<text x="${x}" y="${QUAD_H - QPAD.b + 13}" font-size="9"
        fill="var(--muted)" text-anchor="middle">${Math.round(v)}</text>`);
    });
    ticks(yr[0], yr[1], 2).forEach(v => {
      const y = f1(g.sy(v));
      p.push(`<line x1="${QPAD.l}" y1="${y}" x2="${w - QPAD.r}" y2="${y}"
        stroke="var(--line)" stroke-width="1" stroke-opacity="0.4"/>`);
      p.push(`<text x="${QPAD.l - 5}" y="${f1(+y + 3)}" font-size="9"
        fill="var(--muted)" text-anchor="end">${Math.round(v)}</text>`);
    });
    (rep.safe_band || []).forEach(run => {
      const top = run.map(n => `${f1(g.sx(n[0]))},${f1(g.sy(n[2]))}`);
      const bot = run.slice().reverse().map(n => `${f1(g.sx(n[0]))},${f1(g.sy(n[1]))}`);
      p.push(`<polygon points="${top.concat(bot).join(" ")}" fill="var(--warn)"
        fill-opacity="0.18" stroke="var(--warn)" stroke-opacity="0.6"
        stroke-width="1"/>`);
    });
    if (window.SK) p.push(window.SK.overlay(state, which, g));
    if (window.PTS) p.push(window.PTS.overlay(state, which, g, rep, false));

    const cx = f1(g.sx(pair.thigh.us)), cy = f1(g.sy(pair.knee.us));
    const col = (pair.thigh.outside || pair.knee.outside) ? "var(--bad)" : "var(--good)";
    p.push(`<circle cx="${cx}" cy="${cy}" r="5" fill="${col}" stroke="var(--bg)"
      stroke-width="1.5"/>`);
    return `<svg viewBox="0 0 ${w} ${QUAD_H}" width="100%" height="${QUAD_H}"
      class="cq-svg">
      <rect x="${QPAD.l}" y="${QPAD.t}" width="${iw}" height="${ih}" rx="3"
        fill="var(--panel2)" stroke="var(--line)"/>${p.join("")}</svg>`;
  }

  function renderQuads(state) {
    const host = el("cal-cards");
    if (!host) return;
    const sig = LEG_QUAD.filter(l => (state.legs || {})[l]).join(",");
    if (sig !== quadSig) {
      quadSig = sig;
      host.innerHTML = LEG_QUAD.filter(l => (state.legs || {})[l]).map(l =>
        `<div class="cq" data-leg="${l}">
          <div class="cq-h"><b>${esc(LEG_NAMES[l] || l)}</b>
            <span class="grow"></span>
            <span class="legstate cq-st" data-st="${l}">--</span></div>
          <div class="cq-c" data-c="${l}"></div>
          <div class="cq-f muted small" data-f="${l}"></div>
        </div>`).join("");
      host.querySelectorAll(".cq").forEach(n => n.addEventListener("click", () => {
        const pick = el("leg-pick");
        if (pick) { pick.value = n.dataset.leg; }
        leg = n.dataset.leg;
        built = false;
        setCalView("list");
      }));
    }

    LEG_QUAD.forEach(l => {
      const rep = (state.legs || {})[l];
      if (!rep) return;
      const box = host.querySelector(`[data-c="${l}"]`);
      if (box) {
        const w = Math.max(200, box.clientWidth || 280);
        box.innerHTML = quadSVG(state, l, w);
      }
      const pair = legPair(state, l);
      const st = host.querySelector(`[data-st="${l}"]`);
      if (st) {
        const bad = pair && (pair.thigh.outside || pair.knee.outside);
        st.textContent = !rep.ok ? "not measured" : bad ? "outside" : "in range";
        st.className = "legstate cq-st " + (!rep.ok || bad ? "bad" : "ok");
      }
      const f = host.querySelector(`[data-f="${l}"]`);
      if (f && pair) {
        const n = window.PTS ? PTS.pointsFor(state, l).length : 0;
        f.innerHTML = rep.ok
          ? `<span class="mono">${pair.thigh.us}</span> /
             <span class="mono">${pair.knee.us}</span> µs · ${n} point${
               n === 1 ? "" : "s"}`
          : "";
      }
      host.querySelector(`.cq[data-leg="${l}"]`)
        .classList.toggle("on", l === leg);
    });
  }

  function setCalView(v) {
    calView = v === "compact" ? "compact" : "list";
    try { localStorage.setItem(CAL_VIEW_KEY, calView); } catch (e) { }
    RD.releaseAll();
    dragging = false; dragPoint = null; dragWP = null; drawing = false;
    if (window.SK) SK.cancel();
    quadSig = null;
    document.querySelectorAll("#cal-view .mbtn").forEach(b =>
      b.classList.toggle("active", b.dataset.v === calView));
    const one = el("cal-single"), four = el("cal-cards");
    if (one) one.classList.toggle("hidden", calView !== "list");
    if (four) four.classList.toggle("hidden", calView !== "compact");
    if (last) render(last);
  }

  return { render, quadSVG, legPair, LEG_QUAD, LEG_NAMES, QUAD_H };
})();
