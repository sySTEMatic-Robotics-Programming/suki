window.RD = (function () {
  let ws = null, connected = false;
  const telemetry = [], connWatchers = [];

  function url() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${location.host}/ws`;
  }

  function connect() {
    ws = new WebSocket(url());
    ws.onopen = () => { connected = true; connWatchers.forEach(f => f(true)); };
    ws.onclose = () => {
      connected = false;
      connWatchers.forEach(f => f(false));
      setTimeout(connect, 1000);
    };
    ws.onerror = () => { try { ws.close(); } catch (e) { } };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.type !== "telemetry") return;
      telemetry.forEach(f => { try { f(msg); } catch (e) { console.error(e); } });
    };
  }

  function send(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(obj));
  }

  function throttle(fn, ms) {
    let last = 0, timer = null, pending = null;
    return function (...args) {
      pending = args;
      const now = Date.now();
      if (now - last >= ms) { last = now; fn(...pending); pending = null; return; }
      if (timer) return;
      timer = setTimeout(() => {
        timer = null;
        if (pending) { last = Date.now(); fn(...pending); pending = null; }
      }, ms - (now - last));
    };
  }

  const held = new Set();
  function releaseAll() {
    for (const stop of Array.from(held)) {
      try { stop(); } catch (e) { console.error(e); }
    }
  }
  window.addEventListener("blur", releaseAll);
  window.addEventListener("pagehide", releaseAll);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) releaseAll();
  });
  connWatchers.push((up) => { if (!up) releaseAll(); });

  connect();
  setInterval(() => send({ type: "ping" }), 4000);

  return {
    send,
    throttle,
    setting: (key, value) => send({ type: "setting", key, value }),
    onTelemetry: (f) => telemetry.push(f),
    onConn: (f) => connWatchers.push(f),
    isConnected: () => connected,
    hold: (stop) => held.add(stop),
    release: (stop) => held.delete(stop),
    releaseAll,
  };
})();
