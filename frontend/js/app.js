(function () {
  const el = (id) => document.getElementById(id);

  document.querySelectorAll(".tab").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(b => b.classList.remove("active"));
      document.querySelectorAll(".panel").forEach(p => p.classList.remove("active"));
      btn.classList.add("active");
      el("tab-" + btn.dataset.tab).classList.add("active");
    });
  });

  let estopped = false;
  el("estop").addEventListener("click", () => {
    RD.releaseAll();
    RD.send({ type: estopped ? "clear_estop" : "estop" });
  });

  RD.onConn(up => {
    el("conn").className = "dot " + (up ? "on" : "off");
  });

  RD.onTelemetry(state => {
    el("mode").textContent = state.mode;
    el("mode").className = "badge " + (state.mode === "HW" ? "hw" : "sim");
    el("build").textContent = state.build || "";
    const cam = state.camera || {};
    el("fps").textContent = (cam.fps != null ? cam.fps : "--") + " fps";
    const lp = state.loop || {};
    const hz = el("hz");
    hz.textContent = (lp.hz != null ? lp.hz : "--") + " Hz";
    hz.className = "stat" + (lp.hz != null && lp.hz < 40 ? " bad" : "");

    estopped = !!state.estop;
    const b = el("estop");
    b.textContent = estopped ? "UNLOCK" : "E-STOP";
    b.className = "estop" + (estopped ? " unlock" : "");

    const p = state.pca || {};
    const fault = el("fault");
    if (p.gave_up) {
      fault.textContent = "POWER FAULT — the servo driver kept resetting, so every " +
        "output has been shut down and will stay down. The supply cannot hold the " +
        "servos. Fix the power, then restart Suki.";
      fault.className = "fault";
    } else if (!p.freq_ok) {
      fault.textContent = "The servo driver is not running at 50 Hz — nothing is " +
        "being driven until it is. This is a supply dip, not a software fault.";
      fault.className = "fault";
    } else if (p.i2c_errors) {
      fault.textContent = "The servo driver is not answering reliably — " +
        p.i2c_errors + " failed I2C transfer(s). " + (p.error || "") +
        " This is wiring or power, not software: check the PCA9685's VCC, its ground " +
        "to the Pi, and the SDA/SCL pair. Nothing on this page can be trusted while " +
        "it is happening.";
      fault.className = "fault";
    } else if (p.mismatches) {
      fault.textContent = "The chip has disagreed with what was sent " +
        p.mismatches + " time(s) — " + (p.last_mismatch || "") +
        ". If that number climbs, the fault is the supply or the I2C wiring.";
      fault.className = "fault warn";
    } else {
      fault.className = "fault hidden";
    }

    let broke = null;
    [CAL, ACT, SEQ, VIS, LAB, AUD, SIM, DRV, WT].forEach(p => {
      try { p.render(state); } catch (e) { console.error(e); broke = broke || e; }
    });
    if (broke && fault.className.indexOf("hidden") >= 0) {
      fault.textContent = "This page stopped drawing (" + broke.message + "). The " +
        "robot is unaffected — but nothing on screen is live, so no button here can " +
        "be trusted. Reload the page (hard-reload if it comes back).";
      fault.className = "fault";
    }
  });
})();
