window.ACT = (function () {
  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const LEG_SHORT = { FR: "Front-Right", FL: "Front-Left",
                      BR: "Back-Right", BL: "Back-Left" };

  let wired = false;
  let sig = null;

  function columns(state) {
    const by = {};
    (state.servos || []).forEach(r => (by[r.ch] = r));
    return (state.action_channels || []).map(ch => ({
      ch, leg: (by[ch] || {}).leg || "?", joint: (by[ch] || {}).joint || "?",
    }));
  }

  function header(cols) {
    let top = `<tr><th></th><th>name</th>`;
    for (let i = 0; i < cols.length;) {
      let n = 1;
      while (i + n < cols.length && cols[i + n].leg === cols[i].leg) n++;
      top += `<th colspan="${n}" class="lg">${esc(LEG_SHORT[cols[i].leg] || cols[i].leg)}</th>`;
      i += n;
    }
    top += `<th></th></tr>`;
    const sub = `<tr class="sub"><th></th><th></th>` +
      cols.map(c => `<th>${esc(c.joint)}<span class="mono"> ch${c.ch}</span></th>`).join("") +
      `<th></th></tr>`;
    return top + sub;
  }

  function rowHTML(a, cols) {
    return `<tr data-id="${a.id}">
      <td><button class="btn run" data-id="${a.id}" type="button">Run</button></td>
      <td><input class="aname" data-id="${a.id}" value="${esc(a.name)}"
           maxlength="48"/></td>` +
      cols.map(c => `<td><input class="aus mono" type="number" step="1" min="500"
        max="2500" data-id="${a.id}" data-ch="${c.ch}"
        value="${a.pos[String(c.ch)] != null ? a.pos[String(c.ch)] : ""}"/></td>`).join("") +
      `<td><button class="btn del" data-id="${a.id}" type="button"
           title="delete this action">×</button></td>
    </tr>`;
  }

  function build(state, cols) {
    const t = el("atable");
    t.innerHTML = header(cols) +
      (state.actions || []).map(a => rowHTML(a, cols)).join("");

    t.querySelectorAll(".run").forEach(b => b.addEventListener("click", () => {
      if (document.activeElement && document.activeElement.blur)
        document.activeElement.blur();
      RD.send({ type: "action_run", id: +b.dataset.id });
    }));

    t.querySelectorAll(".del").forEach(b => b.addEventListener("click", () => {
      const row = b.closest("tr");
      const name = row ? (row.querySelector(".aname") || {}).value : "";
      if (!window.confirm(`Delete “${name}”?`)) return;
      RD.send({ type: "action_delete", id: +b.dataset.id });
    }));

    t.querySelectorAll(".aname").forEach(inp => inp.addEventListener("change", () =>
      RD.send({ type: "action_rename", id: +inp.dataset.id, name: inp.value })));

    t.querySelectorAll(".aus").forEach(inp => inp.addEventListener("change", () => {
      const v = parseInt(inp.value, 10);
      if (!isFinite(v)) return;
      RD.send({ type: "action_set", id: +inp.dataset.id, ch: +inp.dataset.ch, us: v });
    }));
  }

  function render(state) {
    if (!wired) {
      wired = true;
      el("act-record").addEventListener("click", () =>
        RD.send({ type: "action_record" }));
      el("act-return").addEventListener("click", () =>
        RD.send({ type: "return_to_last" }));
    }
    const cols = columns(state);
    if (!cols.length) return;

    const next = cols.map(c => c.ch).join(",") + "|" +
      (state.actions || []).map(a => a.id).join(",");
    if (next !== sig) {
      sig = next;
      build(state, cols);
    }

    const t = el("atable");
    (state.actions || []).forEach(a => {
      const n = t.querySelector(`.aname[data-id="${a.id}"]`);
      if (n && document.activeElement !== n) n.value = a.name;
      cols.forEach(c => {
        const f = t.querySelector(`.aus[data-id="${a.id}"][data-ch="${c.ch}"]`);
        if (!f || document.activeElement === f) return;
        const v = a.pos[String(c.ch)];
        f.value = v != null ? v : "";
      });
    });

    const note = el("act-note");
    note.textContent = state.action_note || "";
    note.classList.toggle("hidden", !state.action_note);
  }

  return { render };
})();
