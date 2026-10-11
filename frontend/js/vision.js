window.VIS = (function () {
  const el = (id) => document.getElementById(id);
  const esc = (s) => String(s).replace(/[&<>"']/g, c =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let confHeld = false;
  let wired = false;

  function wire() {
    if (wired) return;
    wired = true;
    el("t-camera").addEventListener("change", (e) =>
      RD.setting("camera", e.target.checked));
    el("t-traffic").addEventListener("change", (e) =>
      RD.send({ type: "vision", traffic: e.target.checked }));
    el("t-objects").addEventListener("change", (e) =>
      RD.send({ type: "vision", objects: e.target.checked }));
    const c = el("yolo-conf");
    c.addEventListener("pointerdown", () => (confHeld = true));
    ["pointerup", "pointercancel", "change"].forEach(e =>
      c.addEventListener(e, () => (confHeld = false)));
    c.addEventListener("input", () => {
      confHeld = true;
      el("yolo-conf-v").textContent = (c.value / 100).toFixed(2);
      RD.send({ type: "vision", conf: c.value / 100 });
    });
  }

  function render(state) {
    wire();
    const v = state.vision || {}, cam = state.camera || {};

    el("v-detector").textContent = v.detector_status || "--";
    el("v-detector").className = "vval " +
      (v.detector_status === "ready" ? "ok"
        : v.detector_status === "failed" ? "bad" : "");
    const vm = el("v-model");
    if (vm) vm.textContent = v.model || "—";
    el("v-light").textContent = v.traffic_light || "none";
    el("v-light").className = "vval " +
      (v.traffic_light === "red" ? "bad" : v.traffic_light === "green" ? "ok" : "");
    const off = cam.enabled === false;
    el("v-cam").textContent = off ? "off" : (cam.connected ? "connected" : "none");
    el("v-cam").className = "vval " + (off ? "" : (cam.connected ? "ok" : "bad"));
    el("v-fps").textContent = (cam.fps != null ? cam.fps : "--") + "";

    if (document.activeElement !== el("t-camera"))
      el("t-camera").checked = !off;
    el("t-traffic").disabled = off;
    el("t-objects").disabled = off;
    el("yolo-conf").disabled = off;

    if (document.activeElement !== el("t-traffic"))
      el("t-traffic").checked = !!v.traffic_enabled;
    if (document.activeElement !== el("t-objects"))
      el("t-objects").checked = !!v.objects_enabled || v.detector_status === "loading";
    if (!confHeld && v.conf != null) {
      el("yolo-conf").value = Math.round(v.conf * 100);
      el("yolo-conf-v").textContent = (+v.conf).toFixed(2);
    }

    const objs = v.objects || [];
    el("detections").innerHTML = objs.length
      ? objs.map(o => `<li class="${o.alert ? "alert" : ""}">
          <b>${esc(o.label)}</b><span class="mono">${o.conf}</span></li>`).join("")
      : `<li class="muted">no detections</li>`;

    const light = el("light");
    if (v.traffic_light && v.traffic_light !== "none") {
      light.textContent = v.traffic_light.toUpperCase();
      light.className = "chip " + v.traffic_light;
    } else {
      light.className = "chip hidden";
    }
    const alerts = objs.filter(o => o.alert);
    const alert = el("alert");
    if (alerts.length) {
      alert.textContent = alerts.map(o => o.label).slice(0, 3).join(", ");
      alert.className = "chip alert";
    } else {
      alert.className = "chip alert hidden";
    }
  }

  return { render };
})();
