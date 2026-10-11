window.SEQ = (function () {
  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const KEY = "suki.seq.active";
  const KEY_EDIT = "suki.seq.edit";
  let active = +(localStorage.getItem(KEY) || 0) || null;
  let editing = localStorage.getItem(KEY_EDIT) === "1";
  let sig = null;
  let lastState = null;

  const S = (state) => (state && state.seq) || {};
  const seqs = (state) => S(state).seqs || [];

  function activeSeq(state) {
    const all = seqs(state);
    if (!all.length) return null;
    return all.find(s => s.id === active) || all[0];
  }

  function render(state) {
    const host = el("seq-panel");
    if (!host) return;
    lastState = state;
    const all = seqs(state);
    const run = S(state).run || null;
    const acts = state.actions || [];
    const cur = activeSeq(state);
    const note = S(state).note;
    const busy = !!run;

    const next = JSON.stringify([all, run, note, active, editing,
                                 acts.map(a => [a.id, a.name]), !!state.estop]);
    if (next === sig) return;
    sig = next;

    if (!all.length) {
      host.innerHTML = `<p class="muted small">No sequences yet.
        <button class="btn sq-new" type="button">+ sequence</button></p>`;
      wire(host, null, false);
      return;
    }

    const nameOf = (id) => (acts.find(a => a.id === id) || {}).name || "?";

    const fwd = cur.steps.map(nameOf);
    const back = cur.reverse && fwd.length > 2;
    const lap = back ? fwd.concat(fwd.slice(1, -1).reverse()) : fwd;
    let plan = [];
    for (let r = 0; r < cur.repeat; r++) plan = plan.concat(lap);
    if (back && fwd.length) plan.push(fwd[0]);

    const planHTML = plan.map((n, i) => `<span class="sq-p${
      run ? (i < run.i ? " done" : i === run.i ? " now" : "") : ""}">${esc(n)}</span>`)
      .join('<i class="sq-arrow">→</i>');

    const chips = all.map(s => `<button class="sq-chip${s.id === cur.id ? " on" : ""}${
      run && run.seq === s.id ? " live" : ""}" data-pick="${s.id}" type="button"
      ${busy ? "disabled" : ""}>${esc(s.name)}</button>`).join("");

    const editHTML = !editing ? "" : `
      <div class="sq-edit">
        <div class="sq-row">
          <input class="sq-name txt" value="${esc(cur.name)}" maxlength="48"
            ${busy ? "disabled" : ""} title="name"/>
          <button class="btn sq-del" type="button" ${busy ? "disabled" : ""}>Delete</button>
        </div>
        <div class="sq-row">
          <span class="sq-lbl">Steps</span>
          ${cur.steps.length
            ? cur.steps.map((aid, i) => `<span class="sq-step">${esc(nameOf(aid))}
                <button class="sq-x" data-del="${i}" type="button" title="remove"
                  ${busy ? "disabled" : ""}>×</button></span>`).join("")
            : `<span class="muted small">none yet — tap a pose below</span>`}
        </div>
        <div class="sq-row">
          <span class="sq-lbl">Add</span>
          ${acts.map(a => `<button class="sq-add" data-add="${a.id}" type="button"
            ${busy ? "disabled" : ""}>${esc(a.name)}</button>`).join("")}
        </div>
        <div class="sq-row">
          <label class="switch"><input type="checkbox" class="sq-reverse"
            ${cur.reverse ? "checked" : ""} ${busy ? "disabled" : ""}/> and back</label>
          <label class="sq-lbl2">repeat ×<input class="sq-repeat mono" type="number"
            min="1" max="${S(state).repeat_max || 50}" value="${cur.repeat}"
            ${busy ? "disabled" : ""}/></label>
          <label class="sq-lbl2">hold <input class="sq-hold mono" type="number"
            min="0" max="${S(state).hold_max || 10}" step="0.1" value="${cur.hold}"
            ${busy ? "disabled" : ""}/>s</label>
          <span class="grow"></span>
          <button class="btn sq-new" type="button" ${busy ||
            all.length >= (S(state).max || 12) ? "disabled" : ""}>+ sequence</button>
        </div>
      </div>`;

    host.innerHTML = `
      <div class="sq-row sq-top">${chips}<span class="grow"></span>
        <button class="sq-editbtn${editing ? " on" : ""}" type="button">
          ${editing ? "Done" : "Edit"}</button></div>

      <div class="sq-plan">${planHTML || '<span class="muted">no steps yet</span>'}</div>

      <div class="sq-go">
        ${run ? `<button class="sq-stop" type="button">STOP</button>`
              : `<button class="btn sq-run" type="button" ${state.estop ||
                  cur.length < 2 ? "disabled" : ""}>Run ${cur.length} poses</button>`}
        <span class="sq-state${run ? " live" : ""}">${run
          ? `<b>${run.i + 1}/${run.n}</b> ${esc(run.action || "")} <i>${
              run.phase === "holding" ? "holding" : "moving"}</i> · ${run.elapsed}s`
          : state.estop ? "E-STOP is on"
          : esc(note || "the robot moves on its own until it finishes or you stop it")}
        </span>
      </div>
      ${editHTML}`;

    wire(host, cur, busy);
  }

  function wire(host, cur, busy) {
    const q = (s) => host.querySelector(s);
    const all = (s) => host.querySelectorAll(s);
    const send = (m) => RD.send(m);
    const repaint = () => { sig = null; render(lastState); };

    const eb = q(".sq-editbtn");
    if (eb) eb.addEventListener("click", () => {
      editing = !editing;
      try { localStorage.setItem(KEY_EDIT, editing ? "1" : "0"); } catch (e) { }
      repaint();
    });
    all(".sq-new").forEach(b => b.addEventListener("click", () =>
      send({ type: "seq_add" })));
    if (!cur) return;

    all("[data-pick]").forEach(b => b.addEventListener("click", () => {
      active = +b.dataset.pick;
      try { localStorage.setItem(KEY, String(active)); } catch (e) { }
      repaint();
    }));

    const runb = q(".sq-run");
    if (runb) runb.addEventListener("click", () => {
      if (!window.confirm(`Run “${cur.name}” — ${cur.length} poses.\n\n`
        + "The robot moves on its own until it finishes or you press STOP.")) return;
      send({ type: "seq_run", id: cur.id });
    });
    const stopb = q(".sq-stop");
    if (stopb) stopb.addEventListener("click", () => send({ type: "seq_stop" }));

    if (busy) return;

    const nm = q(".sq-name");
    if (nm) nm.addEventListener("change", () =>
      send({ type: "seq_rename", id: cur.id, name: nm.value }));
    const del = q(".sq-del");
    if (del) del.addEventListener("click", () => {
      if (!window.confirm(`Delete the sequence “${cur.name}”?`)) return;
      send({ type: "seq_delete", id: cur.id });
    });
    all("[data-add]").forEach(b => b.addEventListener("click", () =>
      send({ type: "seq_step_add", id: cur.id, action: +b.dataset.add })));
    all("[data-del]").forEach(b => b.addEventListener("click", () =>
      send({ type: "seq_step_del", id: cur.id, index: +b.dataset.del })));
    const rev = q(".sq-reverse");
    if (rev) rev.addEventListener("change", () =>
      send({ type: "seq_opts", id: cur.id, reverse: rev.checked }));
    const rep = q(".sq-repeat");
    if (rep) rep.addEventListener("change", () =>
      send({ type: "seq_opts", id: cur.id, repeat: +rep.value }));
    const hold = q(".sq-hold");
    if (hold) hold.addEventListener("change", () =>
      send({ type: "seq_opts", id: cur.id, hold: +hold.value }));
  }

  function busyEditing(host) {
    const a = document.activeElement;
    return !!(a && host && host.contains(a) && !a.disabled &&
      (a.tagName === "INPUT" || a.tagName === "SELECT"));
  }

  return {
    render: (state) => {
      const host = el("seq-panel");
      if (!busyEditing(host) || (state.seq && state.seq.run)) render(state);
    },
  };
})();
