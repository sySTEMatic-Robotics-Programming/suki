const fs = require("fs");
const src = fs.readFileSync(
  require("path").join(__dirname, "..", "frontend", "js", "sim.js"), "utf8");

const grab = (name) => {
  const i = src.indexOf("function " + name + "(");
  if (i < 0) throw new Error("no " + name);
  let d = 0, j = src.indexOf("{", i);
  for (let k = j; k < src.length; k++) {
    if (src[k] === "{") d++;
    else if (src[k] === "}" && --d === 0) return src.slice(i, k + 1);
  }
  throw new Error("unbalanced " + name);
};

const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const BEZ_N = 11;
const BEZ_C = (() => {
  const f = (n) => { let r = 1; for (let i = 2; i <= n; i++) r *= i; return r; };
  return Array.from({ length: 12 }, (_, i) => f(BEZ_N) / (f(i) * f(BEZ_N - i)));
})();
const GAITS = { walk: { label: "Crawl", duty: 0.75,
  ph: { FL: 0, BR: 0.25, FR: 0.5, BL: 0.75 } } };
const P = { gait: "walk", duty: 0.75, stride: 44, clear: 6, centre: -32, stand: 180 };

eval(grab("swingCP") + "\n" + grab("bezier") + "\n" + grab("footAt"));

function sample(mix, N = 720) {
  const pts = [];
  for (let i = 0; i < N; i++) pts.push(footAt("FL", i / N, mix));
  const xs = pts.map(p => p.x), ys = pts.map(p => p.y);
  const st = pts.filter(p => p.stance).map(p => p.x);
  const sw = pts.filter(p => !p.stance);
  return {
    x: [Math.min(...xs), Math.max(...xs)],
    stanceSpan: Math.max(...st) - Math.min(...st),
    swingSpan: Math.max(...sw.map(p => p.x)) - Math.min(...sw.map(p => p.x)),
    lift: P.stand - Math.min(...ys),
    below: pts.filter(p => p.y > P.stand + 1e-6).length,
    gapAtHandover: Math.abs(pts[0].x - pts[N - 1].x),
  };
}

const f = sample(1), b = sample(-1);
const row = (n, o) => console.log(
  `${n.padEnd(9)} x ${o.x[0].toFixed(1)}..${o.x[1].toFixed(1)}  ` +
  `stance ${o.stanceSpan.toFixed(1)}mm  swing ${o.swingSpan.toFixed(1)}mm  ` +
  `lift ${o.lift.toFixed(1)}mm  through-floor ${o.below}`);
row("forward", f);
row("backward", b);

let bad = 0;
const ck = (c, m) => { if (!c) { bad++; console.log("  FAIL  " + m); } };
ck(Math.abs(f.stanceSpan - P.stride) < 0.5,
   `forward stance is ${f.stanceSpan.toFixed(1)}mm, not the ${P.stride}mm stride`);
ck(Math.abs(b.stanceSpan - P.stride) < 0.5,
   `BACKWARD stance is only ${b.stanceSpan.toFixed(1)}mm, not the ${P.stride}mm stride`);
ck(Math.abs(f.lift - b.lift) < 0.5,
   `lift differs: forward ${f.lift.toFixed(1)}mm vs backward ${b.lift.toFixed(1)}mm`);
ck(f.below === 0, `forward puts the foot through the floor on ${f.below} samples`);
ck(b.below === 0, `BACKWARD puts the foot through the floor on ${b.below} samples`);
ck(Math.abs(f.x[1] - f.x[0] - (b.x[1] - b.x[0])) < 0.5,
   `total sweep differs: ${(f.x[1]-f.x[0]).toFixed(1)} vs ${(b.x[1]-b.x[0]).toFixed(1)}`);
console.log(bad ? `\nFAILED: ${bad} problem(s)` : "\nforward and backward are the same step");
process.exit(bad ? 1 : 0);
