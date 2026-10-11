import math

from config import MIN_CORRIDOR_POINTS

GATE_STEPS = 16

MIN_WINDOW_US = 1.0


def _snap(v, lo, hi):
    i = int(round(v))
    if i < lo:
        i = int(math.ceil(lo - 1e-9))
    if i > hi:
        i = int(math.floor(hi + 1e-9))
    return i


def _snap_back(v, origin):
    return int(math.floor(v)) if v >= origin else int(math.ceil(v))


class Corridor:

    __slots__ = ("rows", "_band")

    def __init__(self, rows):
        self._band = None
        clean = []
        for r in rows or []:
            try:
                d = float(r["drive"])
                lo = float(r["min"])
                hi = float(r["max"])
            except (KeyError, TypeError, ValueError):
                continue
            if hi < lo:
                lo, hi = hi, lo
            clean.append((d, lo, hi))
        clean.sort(key=lambda a: a[0])
        rows = []
        for row in clean:
            if rows and abs(row[0] - rows[-1][0]) < 1e-9:
                continue
            rows.append(row)
        self.rows = tuple(rows)

    @property
    def ok(self) -> bool:
        return len(self.rows) >= MIN_CORRIDOR_POINTS

    def thigh_span(self):
        if not self.ok:
            return None
        return self.rows[0][0], self.rows[-1][0]

    def knee_span(self):
        if not self.rows:
            return None
        return (min(r[1] for r in self.rows), max(r[2] for r in self.rows))

    def points(self):
        return [{"drive": int(round(d)), "min": int(round(lo)), "max": int(round(hi))}
                for d, lo, hi in self.rows]

    def window(self, thigh):
        rows = self.rows
        if not rows:
            return None
        t = float(thigh)
        if t <= rows[0][0]:
            return rows[0][1], rows[0][2]
        if t >= rows[-1][0]:
            return rows[-1][1], rows[-1][2]
        for i in range(1, len(rows)):
            a, b = rows[i - 1], rows[i]
            if t <= b[0]:
                span = b[0] - a[0]
                if span <= 0:
                    return b[1], b[2]
                u = (t - a[0]) / span
                return (a[1] + u * (b[1] - a[1]), a[2] + u * (b[2] - a[2]))
        return rows[-1][1], rows[-1][2]

    def width(self, thigh):
        w = self.window(thigh)
        return 0.0 if w is None else (w[1] - w[0])

    def contains(self, thigh, knee) -> bool:
        span = self.thigh_span()
        if span is None or not (span[0] - 1e-6 <= thigh <= span[1] + 1e-6):
            return False
        w = self.window(thigh)
        return bool(w) and (w[0] - 1e-6) <= knee <= (w[1] + 1e-6)

    def clamp_thigh(self, thigh):
        span = self.thigh_span()
        if span is None:
            return float(thigh)
        return max(span[0], min(span[1], float(thigh)))

    def clamp_knee(self, thigh, knee):
        w = self.window(thigh)
        if not w:
            return float(knee)
        return max(w[0], min(w[1], float(knee)))

    def knots(self, t0, t1):
        lo, hi = (t0, t1) if t0 <= t1 else (t1, t0)
        ks = {float(t0), float(t1)}
        for d, _lo, _hi in self.rows:
            if lo < d < hi:
                ks.add(float(d))
        out = sorted(ks)
        return out if t0 <= t1 else list(reversed(out))

    def first_pinch(self, t0, t1):
        ks = self.knots(t0, t1)
        if not ks:
            return None
        wa = self.width(ks[0])
        if wa <= MIN_WINDOW_US:
            return float(ks[0])
        for i in range(1, len(ks)):
            a, b = ks[i - 1], ks[i]
            wb = self.width(b)
            if wb > MIN_WINDOW_US:
                wa = wb
                continue
            denom = wa - wb
            if abs(denom) < 1e-12:
                return float(b)
            u = (wa - MIN_WINDOW_US) / denom
            u = max(0.0, min(1.0, u))
            return float(a + (b - a) * u)
        return None


def _pair_on_path(corr, t0, k0, t_end, k_end, t):
    span = t_end - t0
    u = 1.0 if abs(span) < 1e-9 else (t - t0) / span
    u = max(0.0, min(1.0, u))
    return corr.clamp_knee(t, k0 + u * (k_end - k0))


def reach(corr, t0, k0, thigh_want, knee_want):
    if not corr.ok:
        return int(round(t0)), int(round(k0)), True, "this leg has no measured corridor"

    span = corr.thigh_span()
    t_end = corr.clamp_thigh(thigh_want)
    clipped = abs(t_end - float(thigh_want)) > 0.5
    reason = ("thigh %d is outside the measured corridor %d..%d"
              % (int(thigh_want), int(span[0]), int(span[1]))) if clipped else None

    if corr.width(t0) <= MIN_WINDOW_US:
        return (int(round(t0)), int(round(k0)), True,
                "the corridor is closed at thigh %d" % int(t0))

    pinch = corr.first_pinch(t0, t_end)
    if pinch is not None:
        back = 1.0 if t_end >= t0 else -1.0
        stopped = pinch - back
        if (t_end >= t0 and stopped < t0) or (t_end < t0 and stopped > t0):
            stopped = t0
        t_end = stopped
        clipped = True
        reason = ("the corridor closes at thigh %d - stopped at %d"
                  % (int(round(pinch)), int(round(t_end))))

    t_int = _snap_back(t_end, t0)
    t_int = max(int(math.ceil(span[0])), min(int(math.floor(span[1])), t_int))
    w = corr.window(t_int)
    knee_end = _snap(corr.clamp_knee(t_int, knee_want), w[0], w[1])
    if abs(knee_end - float(knee_want)) > 1.0 and not clipped:
        clipped = True
        reason = ("knee %d is outside its window %d..%d at thigh %d"
                  % (int(knee_want), int(math.ceil(w[0])), int(math.floor(w[1])), t_int))
    return t_int, knee_end, clipped, reason


def _gate_thigh(corr, t0, t_full, k0, s, knee_follows):
    if abs(t_full - t0) < 1e-9:
        return t0
    best = t0
    for i in range(1, GATE_STEPS + 1):
        d = t0 + (t_full - t0) * i / GATE_STEPS
        w = corr.window(d)
        if not w:
            break
        lo, hi = w
        if hi - lo <= 0:
            break
        if knee_follows:
            reachable = min(hi, k0 + s) >= max(lo, k0 - s)
        else:
            reachable = lo <= k0 <= hi
        if not reachable:
            break
        best = d
    return best


def step(corr, t0, k0, thigh_target, knee_target, max_step, knee_follows=True):
    t0 = float(t0)
    k0 = float(k0)
    s = float(max_step)
    if not corr.ok or s <= 0:
        return int(round(t0)), int(round(k0))

    tT = corr.clamp_thigh(thigh_target)

    t_full = t0 + max(-s, min(s, tT - t0))
    t = _gate_thigh(corr, t0, t_full, k0, s, knee_follows)
    span = corr.thigh_span()
    t_i = max(int(math.ceil(span[0])), min(int(math.floor(span[1])),
                                           _snap_back(t, t0)))

    if not knee_follows:
        return t_i, int(round(k0))

    k_want = _pair_on_path(corr, t0, k0, tT, corr.clamp_knee(tT, knee_target), t_i)

    w = corr.window(t_i)
    lo, hi = (k_want, k_want) if not w else w
    alo, ahi = max(lo, k0 - s), min(hi, k0 + s)
    if alo > ahi:
        edge = max(lo, min(hi, k0))
        k = k0 + max(-s, min(s, edge - k0))
        k_i = int(round(k))
        return t_i, (_snap(k_i, lo, hi) if lo <= k_i <= hi else k_i)
    return t_i, _snap(max(alo, min(ahi, k_want)), lo, hi)


def safe_band(corr):
    if corr._band is not None:
        return corr._band
    if not corr.ok:
        corr._band = []
        return corr._band
    nodes = []
    for d, lo, hi in corr.rows:
        nodes.append([float(d), float(lo), float(hi)])
    runs, cur = [], []
    for i, n in enumerate(nodes):
        if n[2] - n[1] > MIN_WINDOW_US:
            cur.append(n)
        if i + 1 < len(nodes):
            a, b = n, nodes[i + 1]
            wa, wb = a[2] - a[1], b[2] - b[1]
            open_a, open_b = wa > MIN_WINDOW_US, wb > MIN_WINDOW_US
            if open_a != open_b and abs(wa - wb) > 1e-12:
                u = (wa - MIN_WINDOW_US) / (wa - wb)
                x = a[0] + (b[0] - a[0]) * max(0.0, min(1.0, u))
                w = corr.window(x)
                cur.append([x, w[0], w[1]])
                if open_a:
                    runs.append(cur)
                    cur = []
    if len(cur) > 1:
        runs.append(cur)
    corr._band = [[[int(round(n[0])), int(math.ceil(n[1])), int(math.floor(n[2]))]
                   for n in run] for run in runs if len(run) > 1]
    return corr._band


def path_points(corr, t0, k0, t1, k1, n=64):
    out = []
    for i in range(n + 1):
        t = t0 + (t1 - t0) * i / n
        out.append((t, _pair_on_path(corr, t0, k0, t1, k1, t)))
    return out


def path_clear(corr, t0, k0, t1, k1, n=256) -> bool:
    return all(corr.contains(t, k) for t, k in path_points(corr, t0, k0, t1, k1, n))
