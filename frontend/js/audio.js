window.AUD = (function () {
  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const WHY = {
    no_match: "no command", ambiguous: "too close to call", cooldown: "just ran",
    disabled: "disabled", dry_run: "dry run", no_target: "no target set",
    not_listening: "listening is off",
    refused: "the robot refused it", no_robot: "no robot", no_recorder: "no recorder",
    no_sequences: "no sequence player", unknown_target: "unknown target",
  };
  const why = (w) => WHY[w] || w || "";

  let wired = false;

  let modelSig = null;
  function renderModels(v, _st) {
    const host = el("stt-models");
    if (!host) return;
    const stt = v.stt || {};
    const list = stt.models || [];
    const now = el("stt-now");
    if (now) now.textContent = stt.model || "—";

    const sig = JSON.stringify([list, stt.model, stt.ms]);
    if (sig === modelSig) return;
    modelSig = sig;

    host.innerHTML = list.length
      ? list.map(m => `<button class="sttm-b${m.on ? " on" : ""}" type="button"
          data-m="${esc(m.name)}"><b>${esc(m.name.replace(/^ggml-|\.bin$/g, ""))}</b>
          <span class="mono">${m.mb} MB</span></button>`).join("")
      : `<p class="muted small">No <b>.bin</b> in <span class="mono">${
          esc(stt.dir || "the models directory")}</span>.</p>`;
    host.querySelectorAll(".sttm-b").forEach(b => b.addEventListener("click", () =>
      RD.setting("stt_model", b.dataset.m)));

    const note = el("stt-note");
    if (note) {
      note.innerHTML =
        (stt.ms ? `Last phrase took <b class="mono">${stt.ms} ms</b>. ` : "") +
        "<b>base</b> is the size this robot wants: <b>tiny</b> gets the language wrong "
        + "on two-word commands often enough to look like it is ignoring you, and "
        + "<b>small</b> is ten-plus seconds a phrase on a Pi 4. It only runs when "
        + "somebody speaks, so the cost is per phrase, never continuous. Add one with "
        + "<span class=\"mono\">download-ggml-model.sh base-q5_1</span>.";
    }
  }

  function segment(host, values, labels, current, onPick) {
    const key = values.join(",") + "|" + labels.join(",");
    if (host.dataset.built !== key) {
      host.dataset.built = key;
      host.innerHTML = "";
      values.forEach((v, i) => {
        const b = document.createElement("button");
        b.type = "button";
        b.className = "mbtn";
        b.dataset.v = v;
        b.textContent = labels[i];
        b.addEventListener("click", () => onPick(v));
        host.appendChild(b);
      });
    }
    host.querySelectorAll(".mbtn").forEach(b =>
      b.classList.toggle("active", b.dataset.v === current));
  }

  function slider(id, key, toValue, toText) {
    const s = el(id), out = el(id + "-v");
    const push = RD.throttle((v) => RD.setting(key, v), 200);
    s.addEventListener("input", () => {
      const v = toValue(+s.value);
      out.textContent = toText(v);
      push(v);
    });
    return { s, out };
  }
  let gain, thresh, fuzz;

  let devSig = "";
  function devices(v) {
    const dev = el("mic-dev");
    const list = v.mic.devices || [];
    const current = v.settings.mic_device;
    const opts = list.slice();
    if (!opts.some(d => d.device === current)) {
      opts.unshift({ device: current, label: current + " (?)" });
    }
    const sig = opts.map(d => d.device).join("|");
    if (sig !== devSig) {
      devSig = sig;
      dev.innerHTML = "";
      opts.forEach(d => {
        const o = document.createElement("option");
        o.value = d.device;
        o.textContent = d.label;
        dev.appendChild(o);
      });
    }
    if (dev !== document.activeElement) dev.value = current;
  }

  let stateSig = null;
  function liveState(v) {
    const n = el("a-state");
    if (!n) return;
    const hearing = !!v.hearing, thinking = !!v.thinking;
    const ms = thinking ? Math.round((v.think_ms || 0) / 100) / 10 : 0;
    const sig = hearing + "|" + thinking + "|" + ms + "|" + (v.last_ms || 0);
    if (sig === stateSig) return;
    stateSig = sig;
    if (thinking) {
      n.className = "a-state thinking";
      n.innerHTML = `<span class="a-dot"></span>Heard something — transcribing…
        <b class="mono">${ms.toFixed(1)}s</b>`;
    } else if (hearing) {
      n.className = "a-state hearing";
      n.innerHTML = `<span class="a-dot"></span>Listening — speech detected`;
    } else if (v.last_ms) {
      n.className = "a-state idle";
      n.innerHTML = `<span class="muted">last phrase took </span><b class="mono">${
        (v.last_ms / 1000).toFixed(1)}s</b>${v.last_ms > 6000
        ? '<span class="muted"> — a smaller recogniser model is the biggest single'
          + ' speed-up; the picker is above</span>' : ""}`;
    } else {
      n.className = "a-state hidden";
    }
  }

  let lastHeard = "";
  function transcript(entries) {
    const key = entries.length + ":" +
      (entries.length ? entries[entries.length - 1].t : 0);
    if (key === lastHeard) return;
    lastHeard = key;

    const ul = el("transcript");
    if (!entries.length) {
      ul.innerHTML = `<li class="muted">Nothing heard yet.</li>`;
      return;
    }
    ul.innerHTML = entries.slice().reverse().map(e => {
      const label = e.label ? (e.label.en || e.label.ro || e.label.zh || "") : "";
      const tag = e.ran ? esc(label) + " ✓"
        : (label ? esc(label) + " — " + esc(why(e.why)) : esc(why(e.why)));
      return `<li class="${e.ran ? "ran" : (e.id ? "held" : "")}">
        <span class="when mono">${new Date(e.t * 1000).toLocaleTimeString()}</span>
        <span class="what">${esc(e.text || "—")}</span>
        <span class="tag">${tag}</span>
        <span class="sc mono">${e.score ? e.score.toFixed(2) : ""}</span></li>`;
    }).join("");
  }

  let recSig = null;
  function recordings(rec) {
    const files = rec.files || [];
    const sig = files.map(f => f.name + ":" + f.bytes).join("|");
    if (sig === recSig) return;
    recSig = sig;
    const host = el("reclist");
    if (!files.length) {
      host.innerHTML = `<p class="muted small">Nothing recorded yet.</p>`;
      return;
    }
    host.innerHTML = files.map(f => `<div class="recrow">
      <span class="recname mono">${esc(f.name)}</span>
      <span class="muted small">${f.seconds}s · ${Math.round(f.bytes / 1024)} kB</span>
      <audio controls preload="none" src="/rec/${encodeURIComponent(f.name)}"></audio>
      </div>`).join("");
  }

  let cmdSig = "";
  function commandSignature(state) {
    const v = state.voice;
    return v.commands.map(c => c.id).join(",") + "|" +
      (state.actions || []).map(a => a.id + ":" + a.name).join(",") + "|" +
      Object.keys(v.targets || {}).join(",");
  }

  function targetOptions(state) {
    const poses = (state.actions || []).map(a =>
      `<option value="pose:${a.id}">${esc(a.name)}</option>`).join("");
    const builtins = Object.entries(state.voice.targets || {}).map(([k, v]) =>
      `<option value="${esc(k)}">${esc(v)}</option>`).join("");
    return `<option value="">— does nothing —</option>` +
      (poses ? `<optgroup label="Poses (Calibration tab)">${poses}</optgroup>` : "") +
      `<optgroup label="The robot's own buttons">${builtins}</optgroup>`;
  }

  function card(c, state) {
    const names = state.voice.lang_names || {};
    const cols = (state.voice.langs || []).map(lg => `
      <div class="langcol">
        <div class="langname">${esc(names[lg] || lg)}</div>
        <input type="text" class="txt lab" data-lang="${lg}" placeholder="Name" />
        <textarea class="txt ph" rows="4" data-lang="${lg}"
                  placeholder="Phrases — one per line"></textarea>
      </div>`).join("");
    return `<details class="section cmd" data-id="${c.id}">
      <summary>
        <input type="checkbox" class="en" />
        <span class="sec-t cmdname"></span>
        <span class="grow"></span>
        <button class="btn run" type="button">Run</button>
      </summary>
      <div class="sec-body">
        <div class="langgrid">${cols}</div>
        <div class="field">
          <div class="fieldlabel">DOES THIS</div>
          <select class="txt target">${targetOptions(state)}</select>
          <p class="muted small">A pose replays through exactly the same corridor check
            as dragging the dot on the chart — a leg that cannot get there stops at the
            limit and says so.</p>
        </div>
        <button class="btn del" type="button">Delete</button>
      </div>
    </details>`;
  }

  function buildCommands(state) {
    const host = el("vcmdlist");
    host.innerHTML = state.voice.commands.map(c => card(c, state)).join("");
    host.querySelectorAll("details.cmd").forEach(d => {
      const id = +d.dataset.id;
      const set = (field, value, lang) =>
        RD.send({ type: "vcommand_set", id, field, value, lang });

      const en = d.querySelector("input.en");
      en.addEventListener("click", (e) => e.stopPropagation());
      en.addEventListener("change", () => set("enabled", en.checked));

      d.querySelector(".run").addEventListener("click", (e) => {
        e.stopPropagation();
        e.preventDefault();
        if (document.activeElement && document.activeElement.blur)
          document.activeElement.blur();
        RD.send({ type: "vcommand_run", id });
      });
      d.querySelector(".target").addEventListener("change", (e) =>
        set("target", e.target.value));
      d.querySelector(".del").addEventListener("click", () => {
        const name = (d.querySelector(".cmdname") || {}).textContent || "";
        if (!window.confirm(`Delete “${name}”?`)) return;
        RD.send({ type: "vcommand_delete", id });
      });
      d.querySelectorAll(".lab").forEach(i => i.addEventListener("change", () =>
        set("label", i.value, i.dataset.lang)));
      d.querySelectorAll(".ph").forEach(i => i.addEventListener("change", () =>
        set("phrases", i.value, i.dataset.lang)));
    });
  }

  function put(node, value) {
    if (node && node !== document.activeElement && node.value !== value)
      node.value = value;
  }

  function commands(state) {
    const sig = commandSignature(state);
    if (sig !== cmdSig) { cmdSig = sig; buildCommands(state); }
    const host = el("vcmdlist");
    state.voice.commands.forEach(c => {
      const d = host.querySelector(`details.cmd[data-id="${c.id}"]`);
      if (!d) return;
      const box = d.querySelector("input.en");
      if (box !== document.activeElement) box.checked = c.enabled;
      d.classList.toggle("off", !c.enabled);
      d.querySelector(".cmdname").textContent =
        c.label.en || c.label.ro || c.label.zh || "(unnamed)";
      put(d.querySelector(".target"), c.target || "");
      (state.voice.langs || []).forEach(lg => {
        put(d.querySelector(`.lab[data-lang="${lg}"]`), c.label[lg] || "");
        put(d.querySelector(`.ph[data-lang="${lg}"]`),
            (c.phrases[lg] || []).join("\n"));
      });
    });
  }

  function simulate() {
    const box = el("sim-text");
    const text = box.value.trim();
    if (!text) return;
    RD.send({ type: "simulate", text });
    box.value = "";
  }

  function wire() {
    if (wired) return;
    wired = true;
    gain = slider("a-gain", "gain", v => v, v => v.toFixed(1) + "×");
    thresh = slider("a-thresh", "threshold", v => v, v => String(Math.round(v)));
    fuzz = slider("a-fuzz", "fuzz", v => v / 100, v => v.toFixed(2));

    el("t-listening").addEventListener("change", (e) =>
      RD.setting("listening", e.target.checked));
    el("t-dryrun").addEventListener("change", (e) =>
      RD.setting("dry_run", e.target.checked));
    el("micbtn").addEventListener("click", () =>
      RD.setting("listening", !el("t-listening").checked));

    el("mic-dev").addEventListener("change", (e) =>
      RD.setting("mic_device", e.target.value));
    el("mic-refresh").addEventListener("click", () =>
      RD.send({ type: "refresh_devices" }));

    el("sim-send").addEventListener("click", simulate);
    el("sim-text").addEventListener("keydown", (e) => {
      if (e.key === "Enter") simulate();
    });

    el("rec-btn").addEventListener("click", () => RD.send({ type: "record" }));
    el("vcmd-add").addEventListener("click", () => RD.send({ type: "vcommand_add" }));

    const mon = el("mon");
    el("mon-btn").addEventListener("click", () => {
      const on = !!mon.getAttribute("src");
      if (on) {
        mon.pause();
        mon.removeAttribute("src");
        mon.load();
        mon.classList.add("hidden");
      } else {
        mon.src = "/audio.wav?t=" + Date.now();
        mon.classList.remove("hidden");
        mon.play().catch(() => { });
      }
      el("mon-btn").textContent = on ? "Listen live" : "Stop listening";
    });
  }

  function render(state) {
    wire();
    const v = state.voice;
    if (!v) return;
    const st = v.settings;

    devices(v);

    const lvl = v.mic.level || 0;
    el("level-bar").style.width =
      Math.min(100, Math.sqrt(lvl / 32768) * 100).toFixed(1) + "%";
    el("level-bar").classList.toggle("hot", !!v.mic.speaking);
    el("level-mark").style.left =
      Math.min(100, Math.sqrt(st.threshold / 32768) * 100).toFixed(1) + "%";
    el("level-v").textContent = Math.round(lvl);

    const listening = !!st.listening;
    if (el("t-listening") !== document.activeElement)
      el("t-listening").checked = listening;
    el("t-dryrun").checked = !!st.dry_run;
    const mb = el("micbtn");
    mb.className = "micbtn" + (listening ? " on" : "") +
      (v.mode === "SIM" ? " sim" : "");
    mb.title = v.mode === "SIM" ? "no microphone or no whisper model (SIM)"
      : (listening ? "listening — press to stop" : "not listening — press to start");

    segment(el("seg-ch"), ["0", "1"], ["Left", "Right"],
            String(st.mic_channel), (x) => RD.setting("mic_channel", +x));
    const langs = v.langs || [];
    segment(el("seg-stt"), langs.concat(["auto"]),
            langs.map(l => (v.lang_names || {})[l] || l).concat(["auto"]),
            st.stt_lang, (x) => RD.setting("stt_lang", x));
    el("auto-hint").classList.toggle("hidden", st.stt_lang !== "auto");
    renderModels(v, st);

    if (gain.s !== document.activeElement) gain.s.value = st.gain;
    gain.out.textContent = (+st.gain).toFixed(1) + "×";
    if (thresh.s !== document.activeElement) thresh.s.value = st.threshold;
    thresh.out.textContent = Math.round(st.threshold);
    if (fuzz.s !== document.activeElement) fuzz.s.value = Math.round(st.fuzz * 100);
    fuzz.out.textContent = (+st.fuzz).toFixed(2);

    const rec = v.recorder || {};
    el("rec-btn").textContent = rec.on ? "Stop recording" : "Start recording";
    el("rec-btn").className = "btn" + (rec.on ? " warn" : "");
    const rs = el("rec-state");
    rs.textContent = rec.on
      ? `recording ${rec.file} · ${rec.seconds}s / ${rec.max_s}s`
      : (rec.error || "idle");
    rs.className = "legstate" + (rec.on ? " ok" : (rec.error ? " bad" : ""));
    recordings(rec);

    transcript(v.transcript || []);
    liveState(v);
    commands(state);

    const f = el("a-fault");
    const err = v.mic.error || v.stt.error;
    if (v.mode === "SIM") {
      f.textContent = "No microphone or no whisper model on this machine, so nothing " +
        "is being heard. Everything else works: type a phrase above and it goes " +
        "through the same matcher a real sentence would. Run ./setup_voice.sh on the " +
        "robot to fix it." + (err ? "  (" + err + ")" : "");
      f.className = "note";
    } else if (err) {
      f.textContent = err;
      f.className = "note warn";
    } else {
      f.className = "note hidden";
    }
  }

  return { render };
})();
