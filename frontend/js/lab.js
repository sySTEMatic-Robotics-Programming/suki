window.LAB = (function () {
  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const PAL = ["#a855f7", "#22d3ee", "#fbbd23", "#36d399",
               "#fb7185", "#60a5fa", "#a3e635", "#fb923c"];
  const colOf = (m) => PAL.indexOf(m && m.colour) >= 0 ? m.colour : PAL[0];
  const LIGHT_COL = { red: "#f87272", amber: "#fbbd23", green: "#36d399" };
  const kb = (n) => n > 1 << 20 ? (n / (1 << 20)).toFixed(1) + " MB"
                                : Math.round(n / 1024) + " kB";

  const K_SEL = "suki.lab.sel", K_PICK = "suki.lab.models", K_OFF = "suki.lab.off";
  let sel = localStorage.getItem(K_SEL) || null;
  let picked = new Set((localStorage.getItem(K_PICK) || "").split("|").filter(Boolean));
  let off = new Set((localStorage.getItem(K_OFF) || "").split("|").filter(Boolean));
  let conf = 0.40, imgsz = 640;
  let dets = null;
  let fetchedFor = null;
  let inflight = false;
  let wired = false;
  let sigStrip = null, sigModels = null, sigRes = null;
  let last = null;
  let uploading = 0, uploadTotal = 0;

  const saveLocal = () => {
    try {
      localStorage.setItem(K_SEL, sel || "");
      localStorage.setItem(K_PICK, Array.from(picked).join("|"));
      localStorage.setItem(K_OFF, Array.from(off).join("|"));
    } catch (e) { }
  };

  const L = (state) => (state && state.lab) || {};

  async function upload(files) {
    const list = Array.from(files || []);
    if (!list.length) return;
    uploading = 0;
    uploadTotal = list.length;
    const errs = [];
    paintUpload();
    for (const f of list) {
      try {
        const r = await fetch("/api/lab/upload?name=" + encodeURIComponent(f.name),
                              { method: "POST", body: f });
        const j = await r.json();
        if (j.error) errs.push(f.name + ": " + j.error);
        else if (j.added && !sel) { sel = j.added.id; saveLocal(); }
      } catch (e) {
        errs.push(f.name + ": " + e.message);
      }
      uploading++;
      paintUpload(errs);
    }
    uploadTotal = 0;
    paintUpload(errs);
  }

  function paintUpload(errs) {
    const n = el("lab-up");
    if (!n) return;
    if (uploadTotal) {
      n.textContent = `sending ${uploading + 1} of ${uploadTotal}…`;
      n.className = "muted small";
    } else if (errs && errs.length) {
      n.innerHTML = "<b class='bad'>" + errs.map(esc).join("<br>") + "</b>";
      n.className = "small";
    } else {
      n.className = "muted small hidden";
    }
  }

  function paintStrip(state) {
    const host = el("lab-strip");
    if (!host) return;
    const imgs = L(state).images || [];
    const sum = L(state).summary || {};
    const sig = JSON.stringify([sel, imgs.map(i => [i.id, i.name]),
      Object.keys(sum).map(k => [k, Object.keys(sum[k]).length])]);
    if (sig === sigStrip) return;
    sigStrip = sig;
    if (!imgs.length) {
      host.innerHTML = `<p class="muted small">Nothing in the library yet.</p>`;
      return;
    }
    host.innerHTML = imgs.map(i => {
      const runs = Object.keys(sum[i.id] || {}).length;
      return `<div class="labthumb${i.id === sel ? " on" : ""}" data-i="${i.id}">
        <img src="/lab/${i.id}.thumb.jpg" alt="${esc(i.name)}" loading="lazy"/>
        <span class="lt-n">${esc(i.name)}</span>
        <span class="lt-m">${i.w}×${i.h}${runs ? " · " + runs + " run" +
          (runs === 1 ? "" : "s") : ""}</span>
        <button class="lt-x" data-x="${i.id}" type="button" title="delete">×</button>
      </div>`;
    }).join("");
    host.querySelectorAll(".labthumb").forEach(t =>
      t.addEventListener("click", (ev) => {
        if (ev.target.classList.contains("lt-x")) return;
        sel = t.dataset.i;
        saveLocal();
        sigStrip = null; sigRes = null; fetchedFor = null;
        if (last) render(last);
      }));
    host.querySelectorAll(".lt-x").forEach(b =>
      b.addEventListener("click", () => {
        const name = (imgs.find(i => i.id === b.dataset.x) || {}).name || "";
        if (!window.confirm(`Delete “${name}” and everything found in it?`)) return;
        RD.send({ type: "lab_delete", image: b.dataset.x });
        if (sel === b.dataset.x) { sel = null; dets = null; saveLocal(); }
      }));
  }

  function paintCanvas(state) {
    const host = el("lab-canvas");
    if (!host) return;
    const imgs = L(state).images || [];
    const img = imgs.find(i => i.id === sel);
    if (!img) {
      host.innerHTML = `<p class="muted empty-tab">Add a picture, or capture the
        camera, to start.</p>`;
      el("lab-legend").innerHTML = "";
      return;
    }
    const models = L(state).models || [];
    const runs = (dets && dets.image === sel && dets.runs) || {};
    const shown = models.filter(m => runs[m.name] && !off.has(m.name));
    const fs = Math.max(11, img.w / 45);
    let boxes = "";
    shown.forEach((m, mi) => {
      const r = runs[m.name];
      const c = colOf(m);
      const dash = mi === 0 ? "" : ` stroke-dasharray="${8 + mi * 4} ${4 + mi * 2}"`;
      (r.dets || []).forEach(d => {
        const [x, y, w, h] = d.box;
        boxes += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none"
          stroke="${c}" stroke-width="3" vector-effect="non-scaling-stroke"${dash}/>`;
        const ty = (y < 18 + mi * fs ? y + fs + mi * fs * 1.15
                                     : y - 5 - mi * fs * 1.15);
        const lit = d.light && d.light.colour !== "none" ? d.light : null;
        if (lit) {
          boxes += `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none"
            stroke="${LIGHT_COL[lit.colour]}" stroke-width="5"
            vector-effect="non-scaling-stroke" stroke-opacity="0.75"/>`;
        }
        boxes += `<text x="${x + 3}" y="${ty}" font-size="${fs}" font-weight="700"
          fill="${lit ? LIGHT_COL[lit.colour] : c}" stroke="#000" stroke-width="0.6"
          paint-order="stroke"
          >${esc(d.label)} ${d.conf.toFixed(2)}${
            lit ? " · " + lit.colour.toUpperCase() : ""}</text>`;
      });
    });
    if (host.dataset.img !== sel) {
      host.dataset.img = sel;
      host.innerHTML = `<div class="labwrap">
        <img src="/lab/${sel}.jpg" alt="${esc(img.name)}"/>
        <svg class="labsvg" viewBox="0 0 ${img.w} ${img.h}"
          preserveAspectRatio="none"></svg></div>`;
    }
    const svg = host.querySelector(".labsvg");
    if (svg) svg.innerHTML = boxes;

    el("lab-legend").innerHTML = models.map(m => {
      const r = runs[m.name];
      if (!r) return "";
      return `<button class="lab-leg${off.has(m.name) ? " off" : ""}"
        data-leg="${esc(m.name)}" type="button" style="--c:${colOf(m)}">
        <span class="lg-dot"></span>${esc(m.name)}
        <span class="lg-n">${(r.dets || []).length}</span></button>`;
    }).join("") || `<span class="muted small">No model has been run on this picture
      yet.</span>`;
    el("lab-legend").querySelectorAll(".lab-leg").forEach(b =>
      b.addEventListener("click", () => {
        const n = b.dataset.leg;
        if (off.has(n)) off.delete(n); else off.add(n);
        saveLocal();
        if (last) paintCanvas(last);
      }));
  }

  function paintModels(state) {
    const host = el("lab-models");
    if (!host) return;
    const models = L(state).models || [];
    const strays = L(state).strays || [];
    const sig = JSON.stringify([models, strays, Array.from(picked).sort()]);
    if (sig === sigModels) return;
    sigModels = sig;
    const stray = strays.length
      ? `<p class="muted small labstray"><b class="warn">Not loaded:</b>
         <span class="mono">${strays.map(esc).join(", ")}</span> — only
         <b class="mono">.pt</b> files are picked up. Rename it if it is a model.</p>`
      : "";
    if (!models.length) {
      host.innerHTML = `<p class="muted small">No <b>.pt</b> found in
        <b class="mono">backend/models</b>.</p>` + stray;
      return;
    }
    host.innerHTML = models.map(m => `<label class="labmodel" style="--c:${colOf(m)}">
      <input type="checkbox" class="lm-cb" data-m="${esc(m.name)}"
        ${picked.has(m.name) ? "checked" : ""}/>
      <span class="lm-dot"></span>
      <b class="lm-n">${esc(m.name)}</b>
      <span class="lm-s muted mono">${kb(m.bytes)}</span>
      ${m.classes ? `<span class="lm-c muted mono">${m.classes} cls</span>` : ""}
      <span class="lm-st ${m.state === "failed" ? "bad" : m.state === "loaded"
        ? "ok" : "muted"}">${esc(m.state)}</span></label>`).join("") + stray;
    host.querySelectorAll(".lm-cb").forEach(cb => cb.addEventListener("change", () => {
      if (cb.checked) picked.add(cb.dataset.m); else picked.delete(cb.dataset.m);
      saveLocal();
      sigModels = null;
    }));
  }

  function paintLight(runs, names) {
    const host = el("lab-light");
    if (!host) return;
    const found = names.map(n => ({ n, L: runs[n] && runs[n].light }))
      .filter(x => x.L && x.L.colour !== "none");
    if (!found.length) {
      const any = names.some(n => (runs[n].dets || []).some(d => d.light));
      host.innerHTML = `<p class="muted small">${
        any ? "A traffic light was found but no lamp read as lit — the crop may be too "
            + "small, too dark, or the light is off."
            : "No traffic light in the detections. Run a model that knows the class "
            + "(COCO's <b class=\"mono\">traffic light</b>) on a picture with one."
      }</p>`;
      return;
    }
    const colours = new Set(found.map(x => x.L.colour));
    host.innerHTML = found.map(x => {
      const L = x.L;
      const weak = L.margin < 0.25;
      const c = Object.entries(L.counts || {}).map(([k, v]) =>
        `${k} ${v}`).join(" · ");
      return `<div class="lightcard" style="--lc:${LIGHT_COL[L.colour]}">
        <div class="lc-lamp"></div>
        <div class="lc-body">
          <b class="lc-col">${L.colour.toUpperCase()}</b>
          <span class="muted small">${esc(x.n)}${L.n > 1 ? ` · ${L.n} lights` : ""}</span>
          <span class="mono small muted">${Math.round(L.frac * 100)}% of the box lit ·
            ${Math.round(L.margin * 100)}% ahead of the runner-up</span>
          <span class="mono small muted">${c}</span>
          ${weak ? '<span class="warn small">close call — the runner-up band is nearly'
            + ' as big, so treat this as a maybe</span>' : ""}
        </div></div>`;
    }).join("") + (colours.size > 1
      ? '<p class="note lr-err">The models do not agree on the colour. That is not a '
        + 'hue problem — the same test ran on both, so they boxed different things.</p>'
      : "");
  }

  function paintResults(state) {
    const host = el("lab-results"), agree = el("lab-agree");
    if (!host || !agree) return;
    const models = L(state).models || [];
    const runs = (dets && dets.image === sel && dets.runs) || {};
    const names = models.map(m => m.name).filter(n => runs[n]);
    const sig = JSON.stringify([sel, names.map(n => [n, (runs[n].dets || []).length,
      runs[n].ms, runs[n].error, (runs[n].light || {}).colour])]);
    if (sig === sigRes) return;
    sigRes = sig;
    paintLight(runs, names);

    if (!names.length) {
      host.innerHTML = `<p class="muted small">Pick a picture and one or more models,
        then press <b>Run on this picture</b>.</p>`;
      agree.innerHTML = "";
      return;
    }

    const saved = names.filter(n => runs[n].out).length;
    const kept = el("lab-kept");
    if (kept) {
      kept.innerHTML = `<span class="muted small">Stored on the robot:
        <a href="/lab/${sel}.jpg" target="_blank" download>the picture</a>${
        saved ? `, ${saved} annotated cop${saved === 1 ? "y" : "ies"}` : ""}, and every
        box in <b class="mono">lab_runs.json</b> — all of it survives a restart.</span>
        <a class="btn lab-exp" href="/api/lab/export?image=${encodeURIComponent(sel)}"
          download>Download the whole record</a>`;
    }

    host.innerHTML = names.map(n => {
      const r = runs[n];
      const m = models.find(x => x.name === n) || {};
      const rows = (r.dets || []).map(d => {
        const lit = d.light && d.light.colour !== "none" ? d.light : null;
        return `<tr>
        <td>${esc(d.label)}${lit ? ` <b class="lightpip" style="--lc:${
          LIGHT_COL[lit.colour]}">${lit.colour}</b>` : ""}</td>
        <td class="mono">${d.conf.toFixed(2)}</td>
        <td class="mono muted">${d.box.map(v => Math.round(v)).join(", ")}</td></tr>`;
      }).join("");
      return `<div class="labres" style="--c:${colOf(m)}">
        <div class="lr-h"><span class="lr-dot"></span><b>${esc(n)}</b>
          <span class="grow"></span>
          ${r.out ? `<a class="lr-save" href="/lab/${esc(r.out)}" target="_blank"
            download title="the picture with these boxes burned into it">saved ↗</a>` : ""}
          <span class="muted mono small">conf ${(+r.conf).toFixed(2)} · ${r.imgsz}px
            · ${r.ms} ms</span></div>
        ${r.error ? `<p class="note lr-err">${esc(r.error)}</p>`
          : rows ? `<table class="lrt"><tr><th>label</th><th>conf</th>
              <th>x, y, w, h</th></tr>${rows}</table>`
          : `<p class="muted small">nothing above this confidence</p>`}
      </div>`;
    }).join("");

    const labels = [];
    names.forEach(n => (runs[n].dets || []).forEach(d => {
      if (!labels.includes(d.label)) labels.push(d.label);
    }));
    if (!labels.length) { agree.innerHTML = ""; return; }

    const vocab = (dets && dets.vocab) || {};
    const knows = (n, label) => {
      const v = vocab[n];
      return !v || !v.length ? true : v.indexOf(label) >= 0;
    };

    const cell = (n, label) => {
      if (!knows(n, label))
        return `<td class="ag-na" title="not one of this model's classes">·</td>`;
      const hits = (runs[n].dets || []).filter(d => d.label === label);
      if (!hits.length)
        return `<td class="ag-no" title="this model knows this class and did not find it">—</td>`;
      const best = Math.max(...hits.map(d => d.conf));
      return `<td class="ag-yes"><b>${hits.length}</b>
        <span class="mono muted">${best.toFixed(2)}</span></td>`;
    };

    let solo = 0;
    const body = labels.map(l => {
      const could = names.filter(n => knows(n, l));
      const seen = could.filter(n => (runs[n].dets || []).some(d => d.label === l));
      const only = could.length <= 1;
      if (only) solo++;
      const cls = only ? "ag-solo"
        : seen.length === could.length ? "ag-all"
        : "ag-one";
      return `<tr class="${cls}">
        <td><b>${esc(l)}</b></td>${names.map(n => cell(n, l)).join("")}
        <td class="mono">${only ? "only " + could.length
          : seen.length + "/" + could.length}</td></tr>`;
    }).join("");

    agree.innerHTML = `<table class="agt">
      <tr><th>label</th>${names.map(n => {
        const m = models.find(x => x.name === n) || {};
        const v = vocab[n] || [];
        return `<th style="--c:${colOf(m)}" title="${v.length
          ? v.length + " classes" : "classes unknown"}"><span class="ag-dot"></span>${
          esc(n)}</th>`;
      }).join("")}<th>agreed</th></tr>${body}</table>
      <p class="muted small">Green = every model that <b>has</b> this class found it.
        Amber = one that has it did not. <b>·</b> means the class is not in that model's
        vocabulary at all${solo ? ` — ${solo} of these rows` : ""}, which is coverage,
        not disagreement.</p>`;
  }

  function refresh(state) {
    const rev = L(state).rev || 0;
    const want = sel ? sel + "@" + rev : null;
    if (!want || want === fetchedFor || inflight) return;
    inflight = true;
    fetch("/api/lab/dets?image=" + encodeURIComponent(sel))
      .then(r => r.json())
      .then(j => {
        dets = j;
        fetchedFor = want;
        sigRes = null;
        if (last) { paintCanvas(last); paintResults(last); }
      })
      .catch(() => { })
      .finally(() => { inflight = false; });
  }

  function wire() {
    wired = true;
    el("lab-file").addEventListener("change", (e) => {
      upload(e.target.files);
      e.target.value = "";
    });
    el("lab-grab").addEventListener("click", () =>
      RD.send({ type: "lab_capture", name: "camera" }));
    el("lab-run").addEventListener("click", () => {
      if (!sel || !picked.size) return;
      RD.send({ type: "lab_run", image: sel, models: Array.from(picked),
                conf, imgsz });
    });
    [["lab-conf", (v) => { conf = v / 100; return conf.toFixed(2); }],
     ["lab-imgsz", (v) => { imgsz = v; return String(v); }]].forEach(([id, fn]) => {
      const s = el(id), out = el(id + "-v");
      s.addEventListener("input", () => { out.textContent = fn(+s.value); });
      out.textContent = fn(+s.value);
    });
  }

  function render(state) {
    if (!el("lab-sec")) return;
    if (!wired) wire();
    last = state;
    const lab = L(state);

    const cnt = el("lab-count");
    if (cnt) cnt.textContent = (lab.images || []).length + " / " +
      (lab.max_images || 60) + " pictures";

    const busy = el("lab-busy");
    if (busy) {
      if (lab.busy) {
        busy.innerHTML = `<b>Running ${esc(lab.busy.model)}</b>
          (${lab.busy.i} of ${lab.busy.n})${lab.queued ? ` · ${lab.queued} queued` : ""}
          — this is using the same cores as the motion loop, so it may tick late until
          it finishes.`;
        busy.className = "note";
      } else {
        busy.className = "note hidden";
      }
    }
    const imgs = lab.images || [];
    if (sel && !imgs.some(i => i.id === sel)) { sel = null; dets = null; }
    if (!sel && imgs.length) { sel = imgs[0].id; saveLocal(); }

    paintStrip(state);
    paintModels(state);
    paintCanvas(state);
    paintResults(state);
    refresh(state);

    const run = el("lab-run");
    if (run) {
      run.disabled = !sel || !picked.size || !!lab.busy;
      run.textContent = lab.busy ? "Running…"
        : picked.size > 1 ? `Run ${picked.size} models on this picture`
        : "Run on this picture";
    }
  }

  return { render };
})();
