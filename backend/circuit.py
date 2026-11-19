"""Circuit simulator (Stage 8) — Modified Nodal Analysis, pure stdlib.

A real circuit solver, not hardcoded graphs. The same algorithm
SPICE uses (MNA + Newton-Raphson for nonlinear devices), written
from scratch in pure Python so the backend has no new dependency.

Supported analyses:
  - DC operating point (Newton-Raphson, pn-junction step limiting)
  - Transient (backward Euler, companion models for C and L)
  - AC small-signal sweep (linearised at the DC operating point)

Supported components: resistor, capacitor, inductor,
voltage_source (dc / step / sine / pulse), current_source,
diode, led, npn, pnp, nmos, pmos, opamp (ideal VCVS),
switch, relay (switch; coil not modelled), ground.

Honest limits (also in docs/ELECTRICAL.md):
  - ngspice, FEMM and Elmer are NOT installed on this machine
    (checked 19 Nov 2026); this is our own MNA solver.
  - BJT is a simplified Ebers-Moll model (no Early effect, no
    saturation limiting) — valid in the active region.
  - MOSFET is a Level-1 (Shichman-Hodges) model.
  - Op-amp is an ideal voltage-controlled voltage source:
    no supply rails, no saturation, no slew rate.
  - No dependent sources other than the op-amp VCVS.
  - Max 200 nodes, 5000 transient steps, 200 AC points.
"""
import cmath
import math

MAX_NODES = 200
MAX_STEPS = 5000
MAX_AC_POINTS = 200
VT = 0.02585  # thermal voltage at ~300 K, V

# ---------------------------------------------------------------------------
# Circuit representation
# ---------------------------------------------------------------------------
# A circuit is {"components": [...], "connections": [...]}.
# Each component: {"id", "type", "nodes": [...]} where nodes are either
# net names ("0" is ground) or, when "connections" are given, terminal
# labels resolved by union-find. "params" holds type-specific values.
#
# Component types and params:
#   resistor          {value: ohm}                       (2 terminals)
#   capacitor         {value: F}                         (2 terminals)
#   inductor          {value: H}                         (2 terminals)
#   voltage_source    {value: V, waveform, amplitude, frequency,
#                      offset, phase, delay, width}      (2 terminals)
#   current_source    {value: A, ...same waveform fields} (2 terminals)
#   diode             {is: A, n}                         (2 terminals)
#   led               {is: A, n}                         (2 terminals)
#   npn / pnp         {is: A, beta}                      (3 terminals: C, B, E)
#   nmos / pmos       {kp: A/V^2, vth: V, lambda: 1/V}    (3 terminals: D, G, S)
#   opamp             {gain}                             (5 terminals: out, in+, in-, v+, v-)
#   switch / relay    {closed: bool}                     (2 terminals)
#   ground            {}                                 (1 terminal)
TERMINALS = {
    "resistor": 2, "capacitor": 2, "inductor": 2,
    "voltage_source": 2, "current_source": 2,
    "diode": 2, "led": 2, "switch": 2, "relay": 2,
    "ground": 1, "npn": 3, "pnp": 3, "nmos": 3, "pmos": 3,
    "opamp": 5,
}
LINEAR = {"resistor", "capacitor", "inductor", "voltage_source",
          "current_source", "switch", "relay"}


def _num(params, key, default=None, positive=False):
    v = params.get(key, default)
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        raise ValueError(f"{key} must be a number")
    if positive and v <= 0:
        raise ValueError(f"{key} must be > 0")
    return v


def validate_circuit(circuit):
    """Return a list of error strings (empty = valid)."""
    errors = []
    if not isinstance(circuit, dict):
        return ["circuit must be an object"]
    comps = circuit.get("components")
    if not isinstance(comps, list) or not comps:
        return ["circuit.components must be a non-empty list"]
    ids = set()
    for i, c in enumerate(comps):
        where = f"components[{i}]"
        if not isinstance(c, dict):
            errors.append(f"{where} must be an object")
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            errors.append(f"{where}.id is required")
            continue
        if cid in ids:
            errors.append(f"duplicate component id: {cid}")
        ids.add(cid)
        ctype = c.get("type")
        if ctype not in TERMINALS:
            errors.append(f"{where}.type is not a supported component: {ctype}")
            continue
        nodes = c.get("nodes")
        if not isinstance(nodes, list) or len(nodes) != TERMINALS[ctype]:
            errors.append(f"{where}.nodes must have {TERMINALS[ctype]} entries for {ctype}")
            continue
        if any(not isinstance(n, str) or not n for n in nodes):
            errors.append(f"{where}.nodes must be non-empty strings")
        p = c.get("params") or {}
        if not isinstance(p, dict):
            errors.append(f"{where}.params must be an object")
            continue
        try:
            if ctype == "resistor":
                _num(p, "value", positive=True)
            elif ctype in ("capacitor", "inductor"):
                _num(p, "value", positive=True)
            elif ctype in ("voltage_source", "current_source"):
                _num(p, "value")
            elif ctype in ("diode", "led"):
                _num(p, "is", 1e-14 if ctype == "diode" else 1e-18, positive=True)
                _num(p, "n", 1 if ctype == "diode" else 1.8, positive=True)
            elif ctype in ("npn", "pnp"):
                _num(p, "is", 1e-15, positive=True)
                _num(p, "beta", 100, positive=True)
            elif ctype in ("nmos", "pmos"):
                _num(p, "kp", 1e-3, positive=True)
                _num(p, "vth", 0.7)
                _num(p, "lambda", 0.0)
            elif ctype == "opamp":
                _num(p, "gain", 1e5, positive=True)
        except ValueError as e:
            errors.append(f"{where}.params: {e}")
    # Ground check.
    nets = set()
    for c in comps:
        if isinstance(c, dict) and isinstance(c.get("nodes"), list):
            nets.update(c["nodes"])
    if "0" not in nets and not any(c.get("type") == "ground" for c in comps if isinstance(c, dict)):
        errors.append("circuit has no ground reference (no node '0' and no ground component)")
    if len(nets) > MAX_NODES:
        errors.append(f"circuit has {len(nets)} nets; the limit is {MAX_NODES}")
    return errors


def _union_find_resolve(circuit):
    """Resolve terminal labels to nets via the connections list.

    Returns a list of components with concrete net names.
    If the circuit already uses net names and has no connections,
    the components are returned unchanged.
    """
    comps = circuit.get("components", [])
    conns = circuit.get("connections") or []
    if not conns:
        return [dict(c, nodes=list(c.get("nodes") or [])) for c in comps]
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for c in comps:
        for ti in range(len(c.get("nodes") or [])):
            find((c["id"], ti))
    for w in conns:
        a, b = w.get("a"), w.get("b")
        if isinstance(a, dict) and isinstance(b, dict):
            union((a.get("comp"), a.get("term", 0)),
                  (b.get("comp"), b.get("term", 0)))
    # Ground terminals merge into net "0".
    for c in comps:
        if c.get("type") == "ground":
            union((c["id"], 0), ("__ground__", 0))
    groups = {}
    for c in comps:
        for ti in range(len(c.get("nodes") or [])):
            r = find((c["id"], ti))
            if r == ("__ground__", 0):
                groups.setdefault(r, "0")
            else:
                groups.setdefault(r, None)
    # Name the nets n1, n2, ... in first-seen order.
    counter = [0]
    for r in groups:
        if groups[r] is None:
            counter[0] += 1
            groups[r] = f"n{counter[0]}"
    out = []
    for c in comps:
        nodes = [groups[find((c["id"], ti))] for ti in range(len(c.get("nodes") or []))]
        out.append(dict(c, nodes=nodes))
    return out


# ---------------------------------------------------------------------------
# Linear algebra (small dense systems; Gaussian elimination, partial pivot)
# ---------------------------------------------------------------------------
def solve_linear(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-14:
            raise ValueError("circuit matrix is singular — check for unconnected nodes, floating nodes, or voltage-source loops")
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            f = M[r][col] / M[col][col]
            if f:
                for k in range(col, n + 1):
                    M[r][k] -= f * M[col][k]
    x = [0.0] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))
        x[i] = s / M[i][i]
    return x


def solve_linear_c(A, b):
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for col in range(n):
        piv = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[piv][col]) < 1e-14:
            raise ValueError("circuit matrix is singular in AC analysis")
        M[col], M[piv] = M[piv], M[col]
        for r in range(col + 1, n):
            f = M[r][col] / M[col][col]
            if f:
                for k in range(col, n + 1):
                    M[r][k] -= f * M[col][k]
    x = [0j] * n
    for i in range(n - 1, -1, -1):
        s = M[i][n] - sum(M[i][j] * x[j] for j in range(i + 1, n))
        x[i] = s / M[i][i]
    return x


# ---------------------------------------------------------------------------
# MNA stamping
# ---------------------------------------------------------------------------
class _MNA:
    """Assembles G*x = I for one linearised circuit state."""

    def __init__(self, nodes, extra_branches):
        self.nodes = nodes  # non-ground nets, in order
        self.idx = {n: i for i, n in enumerate(nodes)}
        self.n = len(nodes)
        self.nb = extra_branches
        self.size = self.n + self.nb
        self.G = [[0.0] * self.size for _ in range(self.size)]
        self.I = [0.0] * self.size
        # SPICE-style gmin: a tiny conductance from every node to
        # ground so nodes with no DC path (e.g. behind a capacitor)
        # do not make the matrix singular. 1e-12 S changes results
        # far below the solver tolerance.
        for i in range(self.n):
            self.G[i][i] += 1e-12

    def _g(self, a, b, v):
        ia = self.idx.get(a)
        ib = self.idx.get(b)
        if ia is not None:
            self.G[ia][ia] += v
        if ib is not None:
            self.G[ib][ib] += v
        if ia is not None and ib is not None:
            self.G[ia][ib] -= v
            self.G[ib][ia] -= v

    def _i(self, a, b, j):
        """Current source J flowing from node a to node b."""
        ia = self.idx.get(a)
        ib = self.idx.get(b)
        if ia is not None:
            self.I[ia] -= j
        if ib is not None:
            self.I[ib] += j

    def _vsrc(self, branch, a, b, value):
        """Ideal voltage source: V(a) - V(b) = value, branch current unknown."""
        row = self.n + branch
        ia = self.idx.get(a)
        ib = self.idx.get(b)
        if ia is not None:
            self.G[row][ia] += 1
            self.G[ia][row] += 1
        if ib is not None:
            self.G[row][ib] -= 1
            self.G[ib][row] -= 1
        self.I[row] += value

    def _vcvs(self, branch, out, p, n, gain):
        """Op-amp: V(out) - gain*(V(p) - V(n)) = 0."""
        row = self.n + branch
        io = self.idx.get(out)
        ip = self.idx.get(p)
        inm = self.idx.get(n)
        if io is not None:
            self.G[row][io] += 1
            self.G[io][row] += 1
        if ip is not None:
            self.G[row][ip] -= gain
        if inm is not None:
            self.G[row][inm] += gain


def _source_value(comp, t):
    """Voltage/current source value at time t (transient waveforms)."""
    p = comp.get("params") or {}
    wave = p.get("waveform", "dc")
    v = p.get("value", 0.0)
    if wave == "dc" or t is None:
        return v
    if wave == "step":
        return p.get("amplitude", v) if t >= p.get("delay", 0.0) else p.get("offset", 0.0)
    if wave == "sine":
        return p.get("offset", 0.0) + p.get("amplitude", v) * math.sin(
            2 * math.pi * p.get("frequency", 50.0) * t + p.get("phase", 0.0))
    if wave == "pulse":
        d, w = p.get("delay", 0.0), p.get("width", 0.001)
        return p.get("amplitude", v) if d <= t < d + w else p.get("offset", 0.0)
    return v


def _diode_current(v, is_, n):
    """Shockley diode current. The exponential argument is clamped
    (SPICE-style junction limiting): above ~0.9 V the diode is
    effectively a short, and letting exp() run to 1e43 would make
    the Newton matrix unusable. The clamp is inactive near the
    real solution (a silicon diode settles near 0.6-0.7 V)."""
    arg = v / (n * VT)
    if arg > 35:
        arg = 35
    elif arg < -50:
        arg = -50
    return is_ * (math.exp(arg) - 1)


def _diode_g(v, is_, n):
    arg = v / (n * VT)
    if arg > 35:
        arg = 35
    elif arg < -50:
        arg = -50
    return is_ / (n * VT) * math.exp(arg)


# ---------------------------------------------------------------------------
# DC operating point
# ---------------------------------------------------------------------------
def _prepare(circuit, dt=None, ac=False):
    comps = _union_find_resolve(circuit)
    nodes = []
    for c in comps:
        for n in c["nodes"]:
            if n != "0" and n not in nodes:
                nodes.append(n)
    # Extra branches: one per voltage source and op-amp, plus one per
    # inductor in DC (an inductor is a short at DC; in transient and AC
    # it uses a companion model / admittance instead and needs no branch).
    branches = []
    for c in comps:
        if c["type"] in ("voltage_source", "opamp"):
            branches.append(c["id"])
        elif c["type"] == "inductor" and dt is None and not ac:
            branches.append(c["id"])
    return comps, nodes, branches


def _stamp_linear(mna, comps, branches, voltages, t, dt, prev, initial=False):
    """Stamp linear elements and companion models. `prev` maps component
    id -> (capacitor voltage | inductor current) from the previous step.
    Returns nothing; fills mna. Nonlinear devices are stamped separately
    by _stamp_nonlinear using the same voltages."""
    bidx = {bid: i for i, bid in enumerate(branches)}
    for c in comps:
        typ = c["type"]
        p = c.get("params") or {}
        ns = c["nodes"]
        if typ == "resistor":
            mna._g(ns[0], ns[1], 1.0 / p["value"])
        elif typ in ("switch", "relay"):
            r = 1e-3 if p.get("closed", True) else 1e9
            mna._g(ns[0], ns[1], 1.0 / r)
        elif typ == "capacitor":
            if initial:
                mna._g(ns[0], ns[1], 1e9)  # uncharged: a short at t=0
                continue
            if dt is None:
                continue  # DC: open circuit
            g = p["value"] / dt
            mna._g(ns[0], ns[1], g)
            vprev = prev.get(c["id"], 0.0)
            mna._i(ns[0], ns[1], -g * vprev)  # _i subtracts; see derivation
            # NOTE: _i(a, b, j) injects -j at a and +j at b; the companion
            # model needs +g*vprev injected at a, so pass -g*vprev.
        elif typ == "inductor":
            if initial:
                continue  # no current at t=0: open circuit
            if dt is None:
                mna._vsrc(bidx[c["id"]], ns[0], ns[1], 0.0)
            else:
                g = dt / p["value"]
                mna._g(ns[0], ns[1], g)
                iprev = prev.get(c["id"], 0.0)
                mna._i(ns[0], ns[1], iprev)
        elif typ == "voltage_source":
            mna._vsrc(bidx[c["id"]], ns[0], ns[1], _source_value(c, t))
        elif typ == "current_source":
            mna._i(ns[0], ns[1], _source_value(c, t))
        elif typ == "opamp":
            mna._vcvs(bidx[c["id"]], ns[0], ns[1], ns[2], p.get("gain", 1e5))


def _limit_junction(junc, cid, vd):
    """SPICE-style junction-voltage limiting for the STAMP: the
    voltage a diode is linearised at may rise at most 0.1 V per
    iteration (the explosive direction) and fall at most 1.0 V.
    `junc` holds the last stamped junction voltage per component."""
    prev = junc.get(cid, 0.0)
    if vd - prev > 0.1:
        vd = prev + 0.1
    elif vd - prev < -1.0:
        vd = prev - 1.0
    junc[cid] = vd
    return vd


def _junction_voltage(comp, voltages):
    """Forward voltage of a diode / BE junction, or None."""
    ns = comp["nodes"]
    typ = comp["type"]
    if typ in ("diode", "led"):
        return voltages.get(ns[0], 0.0) - voltages.get(ns[1], 0.0)
    if typ == "npn":
        return voltages.get(ns[1], 0.0) - voltages.get(ns[2], 0.0)
    if typ == "pnp":
        return voltages.get(ns[2], 0.0) - voltages.get(ns[1], 0.0)
    return None


def _stamp_nonlinear(mna, comps, voltages, junc):
    """Stamp diodes, BJTs and MOSFETs linearised at `voltages`.
    Junction voltages are limited through `junc` (see above)."""
    for c in comps:
        typ = c["type"]
        p = c.get("params") or {}
        ns = c["nodes"]

        def v(node):
            return voltages.get(node, 0.0)

        if typ in ("diode", "led"):
            is_ = p.get("is", 1e-14 if typ == "diode" else 1e-18)
            n = p.get("n", 1 if typ == "diode" else 1.8)
            vd = _limit_junction(junc, c["id"], v(ns[0]) - v(ns[1]))
            g = _diode_g(vd, is_, n)
            i0 = _diode_current(vd, is_, n)
            mna._g(ns[0], ns[1], g)
            mna._i(ns[0], ns[1], i0 - g * vd)
        elif typ in ("npn", "pnp"):
            s = 1 if typ == "npn" else -1
            # BE diode between B and E; controlled source C -> E (npn) or E -> C (pnp).
            is_ = p.get("is", 1e-15)
            beta = p.get("beta", 100)
            if typ == "npn":
                pnode, nnode, cnode, enode = ns[1], ns[2], ns[0], ns[2]
            else:
                pnode, nnode, cnode, enode = ns[2], ns[1], ns[2], ns[0]
            # vd is the forward voltage of the BE junction in both cases.
            vd = _limit_junction(junc, c["id"],
                                 (v(ns[1]) - v(ns[2])) if typ == "npn" else (v(ns[2]) - v(ns[1])))
            g = _diode_g(vd, is_, 1.0)
            i0 = _diode_current(vd, is_, 1.0)
            mna._g(pnode, nnode, g)
            mna._i(pnode, nnode, i0 - g * vd)
            # Controlled source: Ic = beta * Ibe, linearised.
            gm = beta * g
            j0 = beta * i0 - gm * vd
            # Transconductance: current gm*(Vb-Ve) [npn] flows C -> E.
            # Stamp gm into the G matrix between the controlling nodes
            # and the controlled nodes.
            if typ == "npn":
                ctrl_p, ctrl_n, flow_p, flow_n = ns[1], ns[2], ns[0], ns[2]
            else:
                ctrl_p, ctrl_n, flow_p, flow_n = ns[2], ns[1], ns[2], ns[0]
            for (a, sgn_a) in ((flow_p, 1), (flow_n, -1)):
                for (b, sgn_b) in ((ctrl_p, 1), (ctrl_n, -1)):
                    ia = mna.idx.get(a)
                    ib = mna.idx.get(b)
                    if ia is not None and ib is not None:
                        mna.G[ia][ib] += sgn_a * sgn_b * gm
            mna._i(flow_p, flow_n, j0)
        elif typ in ("nmos", "pmos"):
            kp = p.get("kp", 1e-3)
            vth = p.get("vth", 0.7)
            lam = p.get("lambda", 0.0)
            # dnode/snode are the (from, to) nodes of the drain current:
            # NMOS: D -> S, PMOS: S -> D. ctrl is the (positive, negative)
            # pair of the controlling voltage Vgs (NMOS) / Vsg (PMOS).
            if typ == "nmos":
                dnode, snode, gnode = ns[0], ns[2], ns[1]
                ctrl_p, ctrl_n = ns[1], ns[2]
                vgs = v(ns[1]) - v(ns[2])
                vds = v(ns[0]) - v(ns[2])
            else:
                dnode, snode, gnode = ns[2], ns[0], ns[1]
                ctrl_p, ctrl_n = ns[2], ns[1]
                vgs = v(ns[2]) - v(ns[1])
                vds = v(ns[2]) - v(ns[0])
            # Level-1 model on the effective (positive) voltages.
            if vgs <= vth:
                id0, gm, gds = 0.0, 0.0, 0.0
            elif vds < vgs - vth:
                id0 = kp * ((vgs - vth) * vds - vds * vds / 2) * (1 + lam * vds)
                gm = kp * vds * (1 + lam * vds)
                gds = kp * ((vgs - vth) - vds) * (1 + lam * vds) + kp * ((vgs - vth) * vds - vds * vds / 2) * lam
            else:
                id0 = kp / 2 * (vgs - vth) ** 2 * (1 + lam * vds)
                gm = kp * (vgs - vth) * (1 + lam * vds)
                gds = kp / 2 * (vgs - vth) ** 2 * lam
            # Linearised: Id = id0 + gm*(Vgs-Vgs0) + gds*(Vds-Vds0).
            mna._g(dnode, snode, gds)
            for (a, sgn_a) in ((dnode, 1), (snode, -1)):
                for (b, sgn_b) in ((ctrl_p, 1), (ctrl_n, -1)):
                    ia = mna.idx.get(a)
                    ib = mna.idx.get(b)
                    if ia is not None and ib is not None:
                        mna.G[ia][ib] += sgn_a * sgn_b * gm
            j0 = id0 - gm * vgs - gds * vds
            mna._i(dnode, snode, j0)


def _solve_dc(circuit, t=None, dt=None, prev=None, initial=False):
    """DC (or one transient step) operating point. Returns
    (voltages dict, branch currents dict, converged bool).
    initial=True solves the t=0 state: capacitors are shorts
    (uncharged) and inductors are opens (no current)."""
    comps, nodes, branches = _prepare(circuit, dt=None if not initial else 1.0)
    if len(nodes) > MAX_NODES:
        raise ValueError(f"circuit has {len(nodes)} nodes; the limit is {MAX_NODES}")
    voltages = {n: 0.0 for n in nodes}
    prev = prev or {}
    junc = {}  # component id -> last stamped junction voltage
    converged = False
    for _ in range(100):
        mna = _MNA(nodes, len(branches))
        _stamp_linear(mna, comps, branches, voltages, t, dt, prev, initial=initial)
        _stamp_nonlinear(mna, comps, voltages, junc)
        try:
            x = solve_linear(mna.G, mna.I)
        except ValueError:
            raise
        new_v = {nodes[i]: x[i] for i in range(len(nodes))}
        # Damp the whole update so no junction voltage moves more
        # than 0.1 V forward (1.0 V reverse) in one iteration.
        # Without this the linearised diode overshoots and the
        # iteration oscillates between "diode on" and "diode off".
        scale = 1.0
        for c in comps:
            vd_old = _junction_voltage(c, voltages)
            vd_new = _junction_voltage(c, new_v)
            if vd_old is None or vd_new is None:
                continue
            d = vd_new - vd_old
            if d > 0.1:
                scale = min(scale, 0.1 / d)
            elif d < -1.0:
                scale = min(scale, -1.0 / d)
        if scale < 1.0:
            for n in nodes:
                new_v[n] = voltages[n] + (new_v[n] - voltages[n]) * scale
        delta = max((abs(new_v[n] - voltages[n]) for n in nodes), default=0.0)
        voltages = new_v
        if delta < 1e-6:
            converged = True
            break
    if not converged:
        raise ValueError("DC operating point did not converge in 100 iterations — check the circuit (e.g. a diode with no current path, or a floating node)")
    # Re-stamp once at the solution to read branch currents.
    mna = _MNA(nodes, len(branches))
    _stamp_linear(mna, comps, branches, voltages, t, dt, prev, initial=initial)
    _stamp_nonlinear(mna, comps, voltages, junc)
    x = solve_linear(mna.G, mna.I)
    voltages = {nodes[i]: x[i] for i in range(len(nodes))}
    branch_currents = {}
    for i, bid in enumerate(branches):
        branch_currents[bid] = x[len(nodes) + i]
    return voltages, branch_currents, converged


def _branch_current(comp, voltages, branch_currents, prev, dt):
    """Current through a component at the operating point, flowing
    from nodes[0] to nodes[1] (for 2-terminal parts)."""
    typ = comp["type"]
    p = comp.get("params") or {}
    ns = comp["nodes"]

    def v(node):
        return voltages.get(node, 0.0)

    if typ == "voltage_source" or typ == "inductor":
        return branch_currents.get(comp["id"], 0.0)
    if typ == "resistor":
        return (v(ns[0]) - v(ns[1])) / p["value"]
    if typ in ("switch", "relay"):
        r = 1e-3 if p.get("closed", True) else 1e9
        return (v(ns[0]) - v(ns[1])) / r
    if typ == "capacitor":
        if dt is None:
            return 0.0
        return p["value"] / dt * ((v(ns[0]) - v(ns[1])) - prev.get(comp["id"], 0.0))
    if typ == "current_source":
        return _source_value(comp, None)
    if typ in ("diode", "led"):
        is_ = p.get("is", 1e-14 if typ == "diode" else 1e-18)
        n = p.get("n", 1 if typ == "diode" else 1.8)
        return _diode_current(v(ns[0]) - v(ns[1]), is_, n)
    if typ == "opamp":
        return branch_currents.get(comp["id"], 0.0)
    return 0.0


def _power_summary(circuit, comps, voltages, branch_currents, prev, dt):
    power = {}
    for c in comps:
        typ = c["type"]
        ns = c["nodes"]
        if typ in ("npn", "pnp", "nmos", "pmos"):
            # Power = sum over terminals of V * I; approximate with the
            # main current path only (C-E / D-S) plus the control current.
            power[c["id"]] = None
            continue
        if typ == "opamp":
            power[c["id"]] = None
            continue
        if typ == "ground":
            power[c["id"]] = 0.0
            continue
        i = _branch_current(c, voltages, branch_currents, prev, dt)
        dv = voltages.get(ns[0], 0.0) - voltages.get(ns[1], 0.0)
        power[c["id"]] = dv * i
    return power


# ---------------------------------------------------------------------------
# Public analyses
# ---------------------------------------------------------------------------
def simulate_dc(circuit):
    errors = validate_circuit(circuit)
    if errors:
        raise ValueError("; ".join(errors))
    comps, nodes, branches = _prepare(circuit)
    voltages, branch_currents, _ = _solve_dc(circuit)
    power = _power_summary(circuit, comps, voltages, branch_currents, {}, None)
    warnings = _safety_warnings(circuit, comps, voltages, power)
    return {
        "analysis": "dc",
        "nodes": nodes,
        "voltages": {n: round(voltages[n], 6) for n in nodes},
        "branch_currents": {k: round(v, 6) for k, v in branch_currents.items()},
        "power": {k: (round(v, 6) if v is not None else None) for k, v in power.items()},
        "warnings": warnings,
    }


def simulate_transient(circuit, duration, steps, output_nodes=None):
    errors = validate_circuit(circuit)
    if errors:
        raise ValueError("; ".join(errors))
    if not (duration > 0):
        raise ValueError("duration must be > 0")
    if not (1 <= steps <= MAX_STEPS):
        raise ValueError(f"steps must be between 1 and {MAX_STEPS}")
    comps, nodes, branches = _prepare(circuit)
    dt = duration / steps
    prev = {}  # component id -> capacitor voltage / inductor current
    t_series = []
    v_series = {n: [] for n in nodes}
    i_series = {}
    for step in range(steps + 1):
        t = step * dt
        if step == 0:
            voltages, branch_currents, _ = _solve_dc(circuit, t=0.0, initial=True)
        else:
            voltages, branch_currents, _ = _solve_dc(circuit, t=t, dt=dt, prev=prev)
        t_series.append(round(t, 9))
        for n in nodes:
            v_series[n].append(round(voltages[n], 6))
        # Update companion-model state from this step's solution.
        for c in comps:
            if c["type"] == "capacitor":
                prev[c["id"]] = voltages.get(c["nodes"][0], 0.0) - voltages.get(c["nodes"][1], 0.0)
            elif c["type"] == "inductor":
                prev[c["id"]] = _branch_current(c, voltages, branch_currents, prev, dt)
        if step == 0:
            for bid in branches:
                i_series[bid] = []
        for bid in branches:
            i_series[bid].append(round(branch_currents.get(bid, 0.0), 6))
    if output_nodes:
        v_series = {n: v_series[n] for n in output_nodes if n in v_series}
    power = _power_summary(circuit, comps,
                           {n: v_series[n][-1] for n in nodes},
                           {k: v[-1] for k, v in i_series.items()}, prev, dt)
    warnings = _safety_warnings(circuit, comps,
                                {n: v_series[n][-1] for n in nodes}, power)
    return {
        "analysis": "transient",
        "nodes": nodes,
        "t": t_series,
        "voltages": v_series,
        "branch_currents": i_series,
        "power": {k: (round(v, 6) if v is not None else None) for k, v in power.items()},
        "dt": dt,
        "warnings": warnings,
    }


def simulate_ac(circuit, f_start, f_stop, points, output_node=None):
    errors = validate_circuit(circuit)
    if errors:
        raise ValueError("; ".join(errors))
    if not (f_start > 0 and f_stop > f_start):
        raise ValueError("need 0 < f_start < f_stop")
    if not (2 <= points <= MAX_AC_POINTS):
        raise ValueError(f"points must be between 2 and {MAX_AC_POINTS}")
    comps, nodes, branches = _prepare(circuit, ac=True)
    # DC operating point first (sources at their DC/offset value).
    op_voltages, _, _ = _solve_dc(circuit)
    freqs = [f_start * (f_stop / f_start) ** (i / (points - 1)) for i in range(points)]
    mag = {n: [] for n in nodes}
    phase = {n: [] for n in nodes}
    for f in freqs:
        w = 2 * math.pi * f
        n = len(nodes)
        size = n + len(branches)
        idx = {node: i for i, node in enumerate(nodes)}
        A = [[0j] * size for _ in range(size)]
        b = [0j] * size
        bidx = {bid: i for i, bid in enumerate(branches)}
        for i in range(n):
            A[i][i] += 1e-12  # gmin, as in the real solver

        def add_g(a, bb, val):
            ia, ib = idx.get(a), idx.get(bb)
            if ia is not None:
                A[ia][ia] += val
            if ib is not None:
                A[ib][ib] += val
            if ia is not None and ib is not None:
                A[ia][ib] -= val
                A[ib][ia] -= val

        def add_i(a, bb, j):
            ia, ib = idx.get(a), idx.get(bb)
            if ia is not None:
                b[ia] -= j
            if ib is not None:
                b[ib] += j

        for c in comps:
            typ = c["type"]
            p = c.get("params") or {}
            ns = c["nodes"]
            if typ == "resistor":
                add_g(ns[0], ns[1], 1.0 / p["value"])
            elif typ in ("switch", "relay"):
                r = 1e-3 if p.get("closed", True) else 1e9
                add_g(ns[0], ns[1], 1.0 / r)
            elif typ == "capacitor":
                add_g(ns[0], ns[1], 1j * w * p["value"])
            elif typ == "inductor":
                add_g(ns[0], ns[1], 1.0 / (1j * w * p["value"]))
            elif typ == "voltage_source":
                row = n + bidx[c["id"]]
                ia, ib = idx.get(ns[0]), idx.get(ns[1])
                if ia is not None:
                    A[row][ia] += 1
                    A[ia][row] += 1
                if ib is not None:
                    A[row][ib] -= 1
                    A[ib][row] -= 1
                amp = p.get("amplitude", p.get("value", 0.0))
                ph = p.get("phase", 0.0)
                b[row] += amp * cmath.exp(1j * ph)
            elif typ == "current_source":
                amp = p.get("amplitude", p.get("value", 0.0))
                ph = p.get("phase", 0.0)
                add_i(ns[0], ns[1], amp * cmath.exp(1j * ph))
            elif typ in ("diode", "led"):
                is_ = p.get("is", 1e-14 if typ == "diode" else 1e-18)
                nn = p.get("n", 1 if typ == "diode" else 1.8)
                vd = op_voltages.get(ns[0], 0.0) - op_voltages.get(ns[1], 0.0)
                add_g(ns[0], ns[1], _diode_g(vd, is_, nn))
            elif typ == "opamp":
                row = n + bidx[c["id"]]
                gain = p.get("gain", 1e5)
                io, ip, inm = idx.get(ns[0]), idx.get(ns[1]), idx.get(ns[2])
                if io is not None:
                    A[row][io] += 1
                    A[io][row] += 1
                if ip is not None:
                    A[row][ip] -= gain
                if inm is not None:
                    A[row][inm] += gain
        x = solve_linear_c(A, b)
        for i, node in enumerate(nodes):
            mag[node].append(round(abs(x[i]), 6))
            phase[node].append(round(math.degrees(cmath.phase(x[i])), 3))
    if output_node:
        mag = {output_node: mag[output_node]} if output_node in mag else mag
        phase = {output_node: phase[output_node]} if output_node in phase else phase
    return {
        "analysis": "ac",
        "nodes": nodes,
        "frequencies_hz": [round(f, 3) for f in freqs],
        "magnitude_v": mag,
        "phase_deg": phase,
        "dc_operating_point": {n: round(v, 6) for n, v in op_voltages.items()},
        "warnings": ["Small-signal AC analysis: nonlinear devices are linearised at the DC operating point."],
    }


def _safety_warnings(circuit, comps, voltages, power):
    warnings = []
    for node, v in voltages.items():
        if abs(v) > 50:
            warnings.append(f"Hazardous voltage: node {node} reaches {abs(v):.1f} V — treat as dangerous, do not touch a live circuit.")
    for c in comps:
        p = (c.get("params") or {}).get("rating_W", 0.25 if c["type"] == "resistor" else None)
        pw = (power or {}).get(c["id"])
        if p is not None and pw is not None and pw > p:
            warnings.append(f"{c['id']} dissipates {pw:.2f} W, above its {p} W rating — it will overheat.")
    return warnings


CIRCUIT_SCHEMA = {
    "components": "list of {id, type, nodes, params}",
    "connections": "optional list of {a: {comp, term}, b: {comp, term}}",
    "component_types": sorted(TERMINALS),
    "notes": [
        "Node '0' is ground. A ground component connects its net to '0'.",
        "Voltage/current sources support waveforms: dc, step, sine, pulse.",
        "BJT is a simplified Ebers-Moll model (active region); MOSFET is Level-1; op-amp is an ideal VCVS.",
    ],
}
