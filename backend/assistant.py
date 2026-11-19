"""AI Engineering Assistant — Stage 11.

A lightweight, modular assistant that integrates with the engineering
capabilities already built (Stages 1-10). It does NOT train or host
a large language model, it does NOT duplicate any engineering engine,
and it is NOT an autonomous agent.

Architecture
-------------
- Provider layer: a built-in local engine (deterministic intent
  parsing + the real solvers) is the default. External AI model
  APIs are supported through a provider interface, configured
  server-side only (env vars, never in frontend code), and are
  used ONLY to draft free-text explanations — never for tool
  selection, tool arguments, or numbers. Every number in a reply
  comes from a real solver, the materials database, or is labelled
  as an estimate. If the provider fails, the local engine answers
  and the failure is recorded.
- Tool layer: a registry of tools, each a thin wrapper around an
  existing solver or module. The intent engine picks a tool from
  the user's words, extracts parameters with a unit-aware parser,
  validates them, and executes. Missing parameters are asked for —
  never invented.
- Isolation: every conversation, message, proposal and usage row
  carries user_id, and every query filters by it. Project access
  is verified against ownership on the backend for every call.
  Another user's conversation or project behaves as if it does
  not exist (404).
- Proposals: the assistant may PROPOSE a project change, but it
  is only applied after the user explicitly approves it.
- Safety: tool arguments come only from the structured parser
  (numbers + whitelisted enum values), never from raw message
  text passed through. Provider responses are untrusted prose
  and can never trigger a tool call. No eval, no shell, no
  frontend-provided user IDs or ownership claims are trusted.
"""

import json
import math
import os
import re
import time
import urllib.error
import urllib.request

# ------------------------------------------------------------------ providers
# Cost rates are CONFIGURED estimates (USD per 1k tokens). Verify
# against the provider's current pricing before relying on them.
PROVIDER_RATES = {
    "local": {"label": "Local engineering engine (built-in)",
              "prompt_per_1k": 0.0, "completion_per_1k": 0.0},
    "openai": {"label": "OpenAI (chat completions API)",
               "prompt_per_1k": 0.0025, "completion_per_1k": 0.010},
    "anthropic": {"label": "Anthropic (messages API)",
                  "prompt_per_1k": 0.003, "completion_per_1k": 0.015},
    "gemini": {"label": "Google Gemini (generative API)",
               "prompt_per_1k": 0.00125, "completion_per_1k": 0.005},
    "custom": {"label": "Custom OpenAI-compatible endpoint",
               "prompt_per_1k": 0.0, "completion_per_1k": 0.0},
}

# In-memory per-user rate limits (per process; documented limit).
RATE_LIMIT_PER_MINUTE = 30
RATE_LIMIT_PER_HOUR = 200
_rate_log = {}  # user_id -> [timestamps]


def get_provider_config():
    """Provider configuration from the server environment only.
    The API key itself is never returned, logged, or sent to the
    frontend — only whether one is set."""
    name = (os.environ.get("AIELAB_AI_PROVIDER") or "local").strip().lower()
    if name not in PROVIDER_RATES:
        name = "local"
    return {
        "provider": name,
        "label": PROVIDER_RATES[name]["label"],
        "model": os.environ.get("AIELAB_AI_MODEL") or (
            "local-engine" if name == "local" else ""),
        "endpoint": os.environ.get("AIELAB_AI_ENDPOINT") or "",
        "api_key_set": bool(os.environ.get("AIELAB_AI_API_KEY")),
        "configured": name == "local" or bool(os.environ.get("AIELAB_AI_API_KEY")),
    }


def estimate_tokens(text):
    return max(1, len(str(text or "")) // 4)


def cost_usd(provider, prompt_tokens, completion_tokens):
    rates = PROVIDER_RATES.get(provider, PROVIDER_RATES["local"])
    return (prompt_tokens / 1000.0 * rates["prompt_per_1k"]
            + completion_tokens / 1000.0 * rates["completion_per_1k"])


class ProviderError(Exception):
    pass


def provider_explain(prompt, system="You are a concise engineering assistant."):
    """Ask the configured external provider for a free-text
    explanation. Used ONLY for prose — never for numbers, tool
    selection, or tool arguments. Raises ProviderError on any
    failure (the caller falls back to the local engine)."""
    cfg = get_provider_config()
    if cfg["provider"] == "local":
        raise ProviderError("no external provider configured (local engine only)")
    if not cfg["api_key_set"]:
        raise ProviderError(f"provider {cfg['provider']} has no API key configured")
    key = os.environ["AIELAB_AI_API_KEY"]
    endpoint = cfg["endpoint"] or {
        "openai": "https://api.openai.com/v1/chat/completions",
        "anthropic": "https://api.anthropic.com/v1/messages",
        "gemini": "https://generativelanguage.googleapis.com/v1beta/models/"
                  + (cfg["model"] or "gemini-1.5-flash") + ":generateContent",
    }.get(cfg["provider"])
    if not endpoint:
        raise ProviderError(f"provider {cfg['provider']} needs AIELAB_AI_ENDPOINT")
    model = cfg["model"] or "default"
    if cfg["provider"] == "anthropic":
        body = {"model": model, "max_tokens": 800,
                "messages": [{"role": "user", "content": prompt}],
                "system": system}
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    elif cfg["provider"] == "gemini":
        body = {"contents": [{"parts": [{"text": system + "\n\n" + prompt}]}]}
        headers = {"x-goog-api-key": key}
    else:  # openai-compatible
        body = {"model": model,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": prompt}],
                "max_tokens": 800}
        headers = {"Authorization": "Bearer " + key}
    data = json.dumps(body).encode()
    req = urllib.request.Request(endpoint, data=data, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            payload = json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        raise ProviderError(f"provider returned HTTP {e.code}")
    except Exception as e:
        raise ProviderError(f"provider request failed: {e}")
    try:
        if cfg["provider"] == "anthropic":
            return payload["content"][0]["text"]
        if cfg["provider"] == "gemini":
            return payload["candidates"][0]["content"]["parts"][0]["text"]
        return payload["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ProviderError("provider returned an unexpected response shape")


def check_rate_limit(user_id):
    """Returns None when the request is allowed, else a message."""
    now = time.time()
    log = _rate_log.setdefault(user_id, [])
    log[:] = [t for t in log if now - t < 3600]
    if len([t for t in log if now - t < 60]) >= RATE_LIMIT_PER_MINUTE:
        return "Rate limit: 30 messages per minute. Please wait a moment."
    if len(log) >= RATE_LIMIT_PER_HOUR:
        return "Rate limit: 200 messages per hour. Please try again later."
    log.append(now)
    return None


# ------------------------------------------------------------------ units
# (suffix, multiplier to SI, unit kind)
UNIT_TABLE = [
    ("km/h", 1 / 3.6, "speed"), ("m/s", 1.0, "speed"),
    ("kN", 1000.0, "force"), ("N", 1.0, "force"),
    ("N·m", 1.0, "torque"), ("Nm", 1.0, "torque"),
    ("GPa", 1e9, "pressure"), ("MPa", 1e6, "pressure"),
    ("kPa", 1000.0, "pressure"), ("Pa", 1.0, "pressure"),
    ("mm", 0.001, "length"), ("cm", 0.01, "length"),
    ("km", 1000.0, "length"), ("m", 1.0, "length"),
    ("kg", 1.0, "mass"), ("g", 0.001, "mass"),
    ("kW", 1000.0, "power"), ("W", 1.0, "power"),
    ("rpm", 2 * math.pi / 60, "angular_velocity"),
    ("rad/s", 1.0, "angular_velocity"), ("deg", math.pi / 180, "angle"),
    ("°", math.pi / 180, "angle"),
    ("kWh", 3.6e6, "energy"), ("Wh", 3600.0, "energy"),
    ("kV", 1000.0, "voltage"), ("V", 1.0, "voltage"),
    ("mA", 0.001, "current"), ("A", 1.0, "current"),
    ("kΩ", 1000.0, "resistance"), ("ohm", 1.0, "resistance"),
    ("Ω", 1.0, "resistance"), ("kohm", 1000.0, "resistance"),
    ("uF", 1e-6, "capacitance"), ("µF", 1e-6, "capacitance"),
    ("nF", 1e-9, "capacitance"), ("pF", 1e-12, "capacitance"),
    ("mF", 1e-3, "capacitance"), ("F", 1.0, "capacitance"),
    ("mH", 1e-3, "inductance"), ("uH", 1e-6, "inductance"),
    ("H", 1.0, "inductance"),
    ("m2", 1.0, "area"), ("m²", 1.0, "area"),
    ("cm2", 1e-4, "area"), ("mm2", 1e-6, "area"),
    ("k", 1000.0, None),  # bare "1k" = 1000 (electronics shorthand)
    ("ms", 0.001, "time"), ("s", 1.0, "time"),
    ("Hz", 1.0, "frequency"),
]
# Longest suffixes first so "km/h" beats "m" and "kN" beats "N".
UNIT_TABLE.sort(key=lambda u: -len(u[0]))
_NUM_RE = re.compile(r"(-?\d+(?:\.\d+)?)\s*([a-zA-Z°Ωµ·²]+[0-9]?(?:/[a-zA-Z]+)?)?")


def parse_numbers(text):
    """Extract (value_si, unit_kind, raw_unit, position) for every
    number in the text. A bare number has unit_kind None."""
    out = []
    for m in _NUM_RE.finditer(text):
        raw = m.group(2) or ""
        value = float(m.group(1))
        # A lone "x" between two numbers is a dimension separator
        # ("0.1x0.2 m"), not a unit.
        if raw.lower() == "x":
            raw = ""
        kind, mult, converted = None, 1.0, False
        for suffix, mult_i, kind_i in UNIT_TABLE:
            if raw.lower() == suffix.lower():
                kind, mult, converted = kind_i, mult_i, True
                break
        out.append({"value": value * mult, "raw": value, "unit": raw,
                    "kind": kind, "pos": m.start(),
                    "converted": converted,
                    "num_end": m.start(2) if m.group(2) else m.end()})
    return out


# ------------------------------------------------------------------ knowledge
# Short general explanations. Labelled as guidance, never as a
# calculation. No numbers are invented here beyond well-known
# constants and definitions.
KNOWLEDGE = {
    "torque": "Torque is the turning effect of a force: torque = force × distance from the pivot (N·m). In a gearbox the output torque is roughly the input torque × gear ratio × efficiency. Ask me to calculate it — for example 'gear train with 20 and 40 teeth, input 1000 rpm, 10 N·m'.",
    "stress": "Stress is force per unit area (Pa). Axial stress is F/A; bending stress is M·c/I. A part is usually checked by comparing the maximum stress with the material's yield strength (the safety factor). Ask me to calculate it — for example 'cantilever beam 2 m, 5 kN tip load'.",
    "buckling": "Buckling is a stability failure: a slender column under compression can bend sideways well below its crushing strength. The Euler critical load is π²·E·I/(K·L)²; short columns follow the Johnson parabola instead. Ask me — for example 'column buckling 3 m, 100x100 mm steel'.",
    "ohm": "Ohm's law: V = I·R. In a series circuit the same current flows through every part; in parallel the voltage is the same across each branch. Ask me to calculate a circuit — for example 'voltage divider 10 V, R1 1k, R2 1k'.",
    "lift": "Lift is ½·ρ·v²·S·Cl. The lift coefficient rises with angle of attack (thin-airfoil theory: Cl ≈ 2π(α − α₀)) until the wing stalls at Clmax. Ask me for a number — for example 'stall speed for a 10 kg aircraft, wing area 1 m², Clmax 1.4'.",
    "delta-v": "Delta-v is the change in velocity a rocket can achieve: Δv = Isp·g₀·ln(m₀/mf) (Tsiolkovsky). Staging helps because each stage drops its empty tank. Ask me — for example 'rocket delta-v, Isp 300 s, 1000 kg to 200 kg'.",
    "pid": "A PID controller drives an error to zero: proportional (reacts to the present error), integral (removes steady-state error), derivative (damps overshoot). Too much Kp oscillates; too much Ki winds up; Kd adds damping. Ask me to simulate one — for example 'PID step response, Kp 2, Ki 0.5, Kd 1.5'.",
    "gear": "A gear train changes speed and torque: ratio = teeth_out/teeth_in. Output speed = input speed / ratio; output torque ≈ input torque × ratio × efficiency. Ask me to calculate one.",
    "material": "I can look up any material in the database with its real recorded properties, source and confidence — for example 'properties of steel S355' or 'compare steel S355 and aluminium 6061'.",
    "help": "I can calculate, look up materials, analyse your projects, and explain engineering concepts. Try: 'gear train 20 and 40 teeth, 1000 rpm, 10 Nm', 'voltage divider 10 V, R1 1k, R2 1k', 'column buckling 3 m', 'properties of titanium Ti-6Al-4V', or 'inspect my project' (with a project attached).",
}


def explain_topic(text):
    low = text.lower()
    for key, body in KNOWLEDGE.items():
        if key in low or key + "s" in low:
            return body
    if "help" in low or "what can you do" in low or "capabilit" in low:
        return KNOWLEDGE["help"]
    return None


# ------------------------------------------------------------------ tools
class ToolInputError(Exception):
    def __init__(self, missing, message=None):
        super().__init__(message or "missing parameters")
        self.missing = missing  # list of {key, label, unit}


def _param_spec(key, label, kind=None, aliases=(), optional=False,
                default=None, unit=None, cast=float):
    return {"key": key, "label": label, "kind": kind, "aliases": aliases,
            "optional": optional, "default": default, "unit": unit, "cast": cast}


# SI multiplier for a unit name: the solver-facing unit for a param.
UNIT_TO_SI = {"rpm": 2 * math.pi / 60, "mm": 0.001, "cm": 0.01, "m": 1.0,
              "N": 1.0, "N·m": 1.0, "V": 1.0, "A": 1.0, "Ω": 1.0, "W": 1.0,
              "kg": 1.0, "deg": math.pi / 180, "s": 1.0, "m/s": 1.0,
              "m²": 1.0, "m2": 1.0, "F": 1.0, "H": 1.0, "N/m": 1.0, "Ah": 1.0}


def _to_param_unit(spec, n):
    """Convert a parsed number to the unit the solver expects.
    Only numbers whose unit was recognised (SI-converted) go
    through the conversion; a bare number, or one with an
    unrecognised unit word such as "degrees", is taken as-is in
    the param's own unit. Values written as key=value are already
    in the param's unit and never pass through here."""
    if not n.get("converted"):
        return spec["cast"](n["raw"])
    mult = UNIT_TO_SI.get(spec.get("unit") or "", 1.0)
    value = spec["cast"](n["value"] / mult)
    if isinstance(value, float):
        value = float(f"{value:.10g}")  # drop rpm round-trip noise
    return value


def _extract_params(text, specs):
    """Fill params from the text. Returns (inputs, missing)."""
    numbers = parse_numbers(text)
    used = set()
    inputs = {}
    missing = []
    low = text.lower()
    # 1. explicit key=value / key: value
    for spec in specs:
        for alias in (spec["key"],) + tuple(spec["aliases"]):
            m = re.search(re.escape(alias) + r"\s*[=:]\s*(-?\d+(?:\.\d+)?)", low)
            if m:
                inputs[spec["key"]] = spec["cast"](m.group(1))
                break
    # 2. alias keyword + nearest number after it. A number whose
    #    unit kind matches the param is preferred over a bare number,
    #    so a dimension like "0.1x0.2 m" never steals a load or a
    #    torque.
    for spec in specs:
        if spec["key"] in inputs:
            continue
        best = None
        for alias in spec["aliases"]:
            for m in re.finditer(re.escape(alias), low):
                cands = []
                for i, n in enumerate(numbers):
                    if i in used:
                        continue
                    after = 0 <= n["pos"] - m.end() <= 30
                    before = 0 <= m.start() - n["num_end"] <= 15
                    if after or before:
                        # Distance from the alias word, either side.
                        dist = (n["pos"] - m.end()) if after else (m.start() - n["num_end"])
                        cands.append((dist, n))
                kind_match = [c for c in cands if spec["kind"] is not None
                              and c[1]["kind"] == spec["kind"]]
                pool = kind_match or [c for c in cands if c[1]["kind"] is None]
                if pool:
                    cand = min(pool, key=lambda c: c[0])[1]
                    if best is None or cand["pos"] < best["pos"]:
                        best = cand
                if best is not None:
                    break
        if best is not None:
            inputs[spec["key"]] = _to_param_unit(spec, best)
            used.add(numbers.index(best))
    # 3. remaining numbers in order, matched by unit kind.
    # Optional params that already have a default are skipped here
    # so they cannot steal a number meant for a required param.
    for spec in specs:
        if spec["key"] in inputs:
            continue
        if spec["optional"] and spec["default"] is not None:
            continue
        for i, n in enumerate(numbers):
            if i in used:
                continue
            if spec["kind"] is None or n["kind"] is None or n["kind"] == spec["kind"]:
                inputs[spec["key"]] = _to_param_unit(spec, n)
                used.add(i)
                break
    # 4. defaults and missing
    for spec in specs:
        if spec["key"] not in inputs:
            if spec["optional"]:
                inputs[spec["key"]] = spec["default"]
            else:
                missing.append({"key": spec["key"], "label": spec["label"],
                                "unit": spec["unit"]})
    return inputs, missing


# Each tool: name, label, lab, patterns, params, executor key.
# Executors live in the executor dispatch below and call the existing
# solvers/modules — nothing is re-implemented here.
TOOL_DEFS = [
    {"name": "material_lookup", "label": "Material lookup", "lab": "materials",
     "patterns": [r"propert\w* of", r"material", r"steel", r"aluminium", r"aluminum",
                  r"titanium", r"copper", r"timber", r"concrete", r"carbon"],
     "params": [_param_spec("query", "material name or id", aliases=("material", "of"), cast=str)],
     "executor": "material_lookup"},
    {"name": "material_compare", "label": "Material comparison", "lab": "materials",
     "patterns": [r"compare .* and ", r"compare .* vs ", r"which is (stronger|lighter|better)"],
     "params": [_param_spec("ids", "material ids (comma separated)", aliases=("compare",), cast=str)],
     "executor": "material_compare"},
    {"name": "cantilever_beam", "label": "Cantilever beam", "lab": "structural",
     "patterns": [r"cantilever"],
     "params": [_param_spec("length_m", "length", kind="length", aliases=("length", "long", "beam"), unit="m"),
                _param_spec("load_N", "tip load", kind="force", aliases=("load", "force", "tip"), unit="N"),
                _param_spec("section", "section (e.g. rectangle 0.1x0.2 m)", aliases=("section",), cast=str, optional=True, default=None),
                _param_spec("material_id", "material id", aliases=("material",), cast=str, optional=True, default="steel-s355")],
     "executor": "solver"},
    {"name": "simply_supported_beam", "label": "Simply supported beam", "lab": "structural",
     "patterns": [r"simply supported", r"ss beam"],
     "params": [_param_spec("length_m", "length", kind="length", aliases=("length", "span"), unit="m"),
                _param_spec("load_N", "centre load", kind="force", aliases=("load", "force"), unit="N"),
                _param_spec("section", "section", aliases=("section",), cast=str, optional=True, default=None),
                _param_spec("material_id", "material id", aliases=("material",), cast=str, optional=True, default="steel-s355")],
     "executor": "solver"},
    {"name": "column_buckling", "label": "Column buckling", "lab": "structural",
     "patterns": [r"buckl", r"column"],
     "params": [_param_spec("length_m", "length", kind="length", aliases=("length", "height"), unit="m"),
                _param_spec("section", "section (e.g. 100x100 mm square)", aliases=("section",), cast=str, optional=True, default=None),
                _param_spec("material_id", "material id", aliases=("material",), cast=str, optional=True, default="steel-s355"),
                _param_spec("load_N", "applied load", kind="force", aliases=("load",), unit="N", optional=True, default=100000.0)],
     "executor": "solver"},
    {"name": "gear_train", "label": "Gear train", "lab": "mechanical",
     "patterns": [r"gear", r"gearbox"],
     "params": [_param_spec("z1", "teeth on input gear", aliases=("z1", "input teeth", "pinion teeth"), cast=int),
                _param_spec("z2", "teeth on output gear", aliases=("z2", "output teeth"), cast=int),
                _param_spec("module_mm", "module (mm)", aliases=("module",), unit="mm", optional=True, default=2.0),
                _param_spec("input_speed_rpm", "input speed (rpm)", kind="angular_velocity", aliases=("input speed", "speed", "rpm"), unit="rpm"),
                _param_spec("input_torque_Nm", "input torque (N·m)", kind="torque", aliases=("input torque", "torque"), unit="N·m"),
                _param_spec("efficiency", "efficiency (0-1)", aliases=("efficiency",), optional=True, default=0.95)],
     "executor": "solver"},
    {"name": "shaft_combined", "label": "Shaft (combined bending + torsion)", "lab": "mechanical",
     "patterns": [r"shaft"],
     "params": [_param_spec("diameter_m", "diameter", kind="length", aliases=("diameter", "dia"), unit="m"),
                _param_spec("length_m", "length", kind="length", aliases=("length",), unit="m"),
                _param_spec("torque_Nm", "torque (N·m)", kind="torque", aliases=("torque",), unit="N·m"),
                _param_spec("bending_moment_Nm", "bending moment (N·m)", kind="torque", aliases=("bending", "moment"), unit="N·m"),
                _param_spec("material_id", "material id", aliases=("material",), cast=str, optional=True, default="steel-s355")],
     "executor": "solver"},
    {"name": "belt_drive", "label": "Belt drive", "lab": "mechanical",
     "patterns": [r"belt"],
     "params": [_param_spec("d1_m", "driver pulley diameter", kind="length", aliases=("driver", "d1"), unit="m"),
                _param_spec("d2_m", "driven pulley diameter", kind="length", aliases=("driven", "d2"), unit="m"),
                _param_spec("centre_m", "centre distance", kind="length", aliases=("centre", "center"), unit="m"),
                _param_spec("input_speed_rpm", "input speed (rpm)", kind="angular_velocity", aliases=("speed", "rpm"), unit="rpm"),
                _param_spec("power_W", "power (W)", kind="power", aliases=("power",), unit="W")],
     "executor": "solver"},
    {"name": "spring_helical", "label": "Helical spring", "lab": "mechanical",
     "patterns": [r"spring"],
     "params": [_param_spec("wire_d_m", "wire diameter", kind="length", aliases=("wire",), unit="m"),
                _param_spec("coil_d_m", "coil diameter", kind="length", aliases=("coil",), unit="m"),
                _param_spec("coils", "number of coils", aliases=("coils",), cast=int),
                _param_spec("load_N", "load", kind="force", aliases=("load", "force"), unit="N"),
                _param_spec("material_id", "material id", aliases=("material",), cast=str, optional=True, default="steel-s355")],
     "executor": "solver"},
    {"name": "vibration_1dof", "label": "Vibration (1 DOF)", "lab": "mechanical",
     "patterns": [r"vibrat", r"natural frequen", r"resonan"],
     "params": [_param_spec("stiffness_N_m", "stiffness (N/m)", aliases=("stiffness", "k"), unit="N/m"),
                _param_spec("mass_kg", "mass (kg)", kind="mass", aliases=("mass",), unit="kg")],
     "executor": "solver"},
    {"name": "power_transmission", "label": "Power transmission", "lab": "mechanical",
     "patterns": [r"power.*torque", r"torque.*power", r"how much power"],
     "params": [_param_spec("torque_Nm", "torque (N·m)", kind="torque", aliases=("torque",), unit="N·m"),
                _param_spec("speed_rpm", "speed (rpm)", kind="angular_velocity", aliases=("speed", "rpm"), unit="rpm")],
     "executor": "solver"},
    {"name": "ohm_law", "label": "Ohm's law", "lab": "electrical",
     "patterns": [r"ohm", r"voltage.*current", r"current.*resistan"],
     "params": [_param_spec("voltage_V", "voltage (V)", kind="voltage", aliases=("voltage", "volts"), unit="V", optional=True, default=None),
                _param_spec("current_A", "current (A)", kind="current", aliases=("current", "amps"), unit="A", optional=True, default=None),
                _param_spec("resistance_ohm", "resistance (Ω)", kind="resistance", aliases=("resistance", "resistor"), unit="Ω", optional=True, default=None)],
     "executor": "ohm_law"},
    {"name": "rc_time_constant", "label": "RC time constant", "lab": "electrical",
     "patterns": [r"rc time", r"time constant"],
     "params": [_param_spec("resistance_ohm", "resistance (Ω)", kind="resistance", aliases=("resistance", "resistor"), unit="Ω"),
                _param_spec("capacitance_F", "capacitance (F)", kind="capacitance", aliases=("capacitance", "capacitor"), cast=float, unit="F"),
                _param_spec("voltage_V", "supply voltage (V)", kind="voltage", aliases=("voltage", "volts"), unit="V", optional=True, default=1.0)],
     "executor": "solver"},
    {"name": "rlc_resonance", "label": "RLC resonance", "lab": "electrical",
     "patterns": [r"rlc", r"resonant frequen"],
     "params": [_param_spec("resistance_ohm", "resistance (Ω)", kind="resistance", aliases=("resistance",), unit="Ω"),
                _param_spec("inductance_H", "inductance (H)", kind="inductance", aliases=("inductance", "inductor"), cast=float, unit="H"),
                _param_spec("capacitance_F", "capacitance (F)", kind="capacitance", aliases=("capacitance", "capacitor"), cast=float)],
     "executor": "solver"},
    {"name": "dc_motor", "label": "DC motor (steady state)", "lab": "electrical",
     "patterns": [r"dc motor", r"motor.*speed", r"motor.*torque"],
     "params": [_param_spec("voltage_V", "voltage (V)", kind="voltage", aliases=("voltage", "volts"), unit="V"),
                _param_spec("resistance_ohm", "resistance (Ω)", kind="resistance", aliases=("resistance",), unit="Ω"),
                _param_spec("kt_Nm_per_A", "torque constant Kt", aliases=("kt",), optional=True, default=0.05),
                _param_spec("ke_V_per_rad_s", "back-EMF constant Ke", aliases=("ke",), optional=True, default=0.05),
                _param_spec("load_torque_Nm", "load torque (N·m)", kind="torque", aliases=("load", "torque"), unit="N·m", optional=True, default=0.0)],
     "executor": "solver"},
    {"name": "battery_config", "label": "Battery configuration", "lab": "electrical",
     "patterns": [r"battery"],
     "params": [_param_spec("cell_voltage_V", "cell voltage (V)", kind="voltage", aliases=("cell voltage", "voltage"), unit="V"),
                _param_spec("cell_capacity_Ah", "cell capacity (Ah)", aliases=("capacity", "ah"), cast=float),
                _param_spec("series", "cells in series", aliases=("series",), cast=int),
                _param_spec("parallel", "cells in parallel", aliases=("parallel",), cast=int),
                _param_spec("load_current_A", "load current (A)", kind="current", aliases=("load", "current"), unit="A", optional=True, default=0.0)],
     "executor": "solver"},
    {"name": "circuit_voltage_divider", "label": "Voltage divider circuit", "lab": "electrical",
     "patterns": [r"voltage divider"],
     "params": [_param_spec("voltage_V", "supply voltage (V)", kind="voltage", aliases=("supply", "voltage", "volts"), unit="V"),
                _param_spec("r1_ohm", "R1 (Ω)", kind="resistance", aliases=("r1",), unit="Ω"),
                _param_spec("r2_ohm", "R2 (Ω)", kind="resistance", aliases=("r2",), unit="Ω")],
     "executor": "voltage_divider"},
    {"name": "airfoil_lift", "label": "Airfoil lift", "lab": "aerospace",
     "patterns": [r"airfoil", r"lift coefficient", r"\bcl\b"],
     "params": [_param_spec("airfoil_code", "airfoil code (e.g. naca2412)", aliases=("airfoil", "naca"), cast=str, optional=True, default="naca2412"),
                _param_spec("alpha_deg", "angle of attack (deg)", kind="angle", aliases=("angle", "alpha", "aoa"), unit="deg")],
     "executor": "solver"},
    {"name": "stall_speed", "label": "Stall speed", "lab": "aerospace",
     "patterns": [r"stall speed", r"stall"],
     "params": [_param_spec("mass_kg", "mass (kg)", kind="mass", aliases=("mass",), unit="kg"),
                _param_spec("wing_area_m2", "wing area (m²)", kind="area", aliases=("wing area", "area"), cast=float, unit="m²"),
                _param_spec("cl_max", "Clmax", aliases=("clmax", "cl max"), cast=float)],
     "executor": "solver"},
    {"name": "rocket_delta_v", "label": "Rocket delta-v", "lab": "aerospace",
     "patterns": [r"delta-v", r"delta v", r"rocket"],
     "params": [_param_spec("isp_s", "specific impulse (s)", aliases=("isp",), cast=float),
                _param_spec("m0_kg", "initial mass (kg)", kind="mass", aliases=("initial mass", "m0"), unit="kg"),
                _param_spec("mf_kg", "final mass (kg)", kind="mass", aliases=("final mass", "mf"), unit="kg")],
     "executor": "rocket_delta_v"},
    {"name": "multirotor_hover", "label": "Multirotor hover", "lab": "aerospace",
     "patterns": [r"multirotor", r"quadcopter", r"drone.*hover", r"hover"],
     "params": [_param_spec("mass_kg", "mass (kg)", kind="mass", aliases=("mass",), unit="kg"),
                _param_spec("n_rotors", "number of rotors", aliases=("rotors",), cast=int, optional=True, default=4),
                _param_spec("rotor_diameter_m", "rotor diameter (m)", kind="length", aliases=("rotor", "diameter"), unit="m")],
     "executor": "solver"},
    {"name": "forward_kinematics", "label": "Robot forward kinematics", "lab": "robotics",
     "patterns": [r"forward kinematics", r"\bfk\b"],
     "params": [_param_spec("dh", "DH table (JSON)", aliases=("dh",), cast=str),
                _param_spec("joints", "joint angles (deg, comma separated)", aliases=("joints",), cast=str)],
     "executor": "forward_kinematics"},
    {"name": "ik_2r", "label": "Inverse kinematics (2R arm)", "lab": "robotics",
     "patterns": [r"inverse kinematics", r"\bik\b"],
     "params": [_param_spec("l1", "link 1 length (m)", kind="length", aliases=("l1", "link 1"), unit="m"),
                _param_spec("l2", "link 2 length (m)", kind="length", aliases=("l2", "link 2"), unit="m"),
                _param_spec("target", "target (x, y in m)", aliases=("target", "to"), cast=str)],
     "executor": "ik_2r"},
    {"name": "pid_control", "label": "PID step response", "lab": "robotics",
     "patterns": [r"pid", r"step response"],
     "params": [_param_spec("kp", "Kp", aliases=("kp",), cast=float),
                _param_spec("ki", "Ki", aliases=("ki",), cast=float, optional=True, default=0.0),
                _param_spec("kd", "Kd", aliases=("kd",), cast=float, optional=True, default=0.0),
                _param_spec("setpoint_rad", "setpoint (rad)", aliases=("setpoint",), cast=float, optional=True, default=1.0)],
     "executor": "pid_control"},
    {"name": "wind_load_is875", "label": "Wind load (IS 875)", "lab": "structural",
     "patterns": [r"wind load", r"wind.*pressure"],
     "params": [_param_spec("basic_wind_speed_m_s", "basic wind speed (m/s)", kind="speed", aliases=("wind speed",), unit="m/s"),
                _param_spec("area_m2", "area (m²)", kind="area", aliases=("area",), cast=float, unit="m²"),
                _param_spec("force_coefficient", "force coefficient", aliases=("coefficient", "cf"), cast=float, optional=True, default=1.0)],
     "executor": "solver"},
    {"name": "project_inspect", "label": "Inspect my project", "lab": "general",
     "patterns": [r"inspect .*project", r"my project", r"what.*in my project",
                  r"show.*project", r"explain (my|the|this) (project|design)",
                  r"explain.*design of my project"],
     "params": [],
     "executor": "project_inspect"},
    {"name": "project_propose", "label": "Propose a project change", "lab": "general",
     "patterns": [r"change .* in my project", r"modify .*project", r"update .*project",
                  r"change the .* (beam|section|material|spar|joint)", r"make the .* (bigger|smaller|stronger|longer)"],
     "params": [_param_spec("change", "what to change (plain words)", aliases=("change", "modify"), cast=str)],
     "executor": "project_propose"},
]

# Suggested defaults offered when a parameter is missing (the user
# must confirm them — they are never applied silently).
SUGGESTED_DEFAULTS = {
    "circuit_voltage_divider": {"r1_ohm": 1000.0, "r2_ohm": 1000.0},
}


def select_tool(text):
    """Pick the best tool for the text. Returns (tool_def, score).
    Returns (None, 0) when nothing matches well enough."""
    low = text.lower()
    best, best_score = None, 0
    for tool in TOOL_DEFS:
        score = 0
        for pat in tool["patterns"]:
            if re.search(pat, low):
                score += 2 if len(pat) > 6 else 1
        # The tool's own name words appearing in the request.
        for word in tool["name"].split("_"):
            if len(word) > 1 and word in low:
                score += 1
        if score > best_score:
            best, best_score = tool, score
    if best is not None and best_score >= 2:
        return best, best_score
    return None, 0


def parse_section(text):
    """Parse a section description like 'rectangle 0.1x0.2 m' or
    '100x100 mm square' into a Stage 9 section dict. Returns None
    when nothing recognisable is present (caller falls back to a
    default and says so)."""
    low = text.lower()
    m = re.search(r"(\d+(?:\.\d+)?)\s*[x×]\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)?", low)
    if m:
        a, b = float(m.group(1)), float(m.group(2))
        unit = {"mm": 0.001, "cm": 0.01, "m": 1.0}.get(m.group(3) or "m", 1.0)
        # First number is width (b), second is height (h) by convention.
        return {"type": "rectangle", "b_m": a * unit, "h_m": b * unit}
    m = re.search(r"(?:diameter|dia|d|ø)\s*(\d+(?:\.\d+)?)\s*(mm|cm|m)?", low)
    if m:
        unit = {"mm": 0.001, "cm": 0.01, "m": 1.0}.get(m.group(2) or "m", 1.0)
        return {"type": "circle", "d_m": float(m.group(1)) * unit}
    return None


def _parse_target_xy(text):
    m = re.search(r"\(\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*\)", text)
    if m:
        return [float(m.group(1)), float(m.group(2))]
    nums = parse_numbers(text)
    vals = [n["value"] for n in nums if n["kind"] in ("length", None)]
    if len(vals) >= 2:
        return vals[:2]
    return None


def _parse_list_floats(text):
    return [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", text)]


# ------------------------------------------------------------------ execution
# ctx is a dict supplied by the API layer:
#   {"conn": db connection, "user_id": str,
#    "project": project row dict or None (owner-verified),
#    "project_payload": project payload dict or None}
DEFAULT_BEAM_SECTION = {"type": "rectangle", "b_m": 0.1, "h_m": 0.2}
DEFAULT_COLUMN_SECTION = {"type": "rectangle", "b_m": 0.1, "h_m": 0.1}
# The validated Stage 10 test motor, used for PID demonstrations.
PID_MOTOR = {"R_ohm": 1.5, "L_H": 0.001, "Kt_Nm_per_A": 0.05,
             "Ke_V_per_rad_s": 0.05, "J_kg_m2": 0.01, "b_Nm_s": 0.001,
             "voltage_limit_V": 12.0, "load_torque_Nm": 0.0}
# Human-readable labels for solver outputs, used in replies.
VALUE_LABELS = {
    "gear_ratio": ("Gear ratio", ""), "output_speed_rpm": ("Output speed", "rpm"),
    "output_torque_Nm": ("Output torque", "N·m"), "power_in_W": ("Power in", "W"),
    "power_out_W": ("Power out", "W"), "centre_distance_m": ("Centre distance", "m"),
    "tangential_force_N": ("Tangential force", "N"),
    "deflection_m": ("Deflection", "m"), "slope_rad": ("Slope", "rad"),
    "bending_moment_Nm": ("Bending moment", "N·m"), "max_stress_Pa": ("Max stress", "Pa"),
    "safety_factor": ("Safety factor", ""), "critical_load_N": ("Critical load", "N"),
    "critical_stress_Pa": ("Critical stress", "Pa"), "slenderness": ("Slenderness", ""),
    "utilization": ("Utilisation", ""), "stall_speed_m_s": ("Stall speed", "m/s"),
    "stall_speed_kmh": ("Stall speed", "km/h"), "tau_s": ("Time constant τ", "s"),
    "cutoff_hz": ("Cutoff frequency", "Hz"), "settle_5tau_s": ("Settle time (5τ)", "s"),
    "total_voltage_V": ("Total voltage", "V"), "total_capacity_Ah": ("Total capacity", "Ah"),
    "energy_Wh": ("Energy", "Wh"), "runtime_h": ("Runtime", "h"),
    "bending_stress_Pa": ("Bending stress", "Pa"), "shear_stress_Pa": ("Shear stress", "Pa"),
    "von_mises_stress_Pa": ("Von Mises stress", "Pa"), "angle_of_twist_rad": ("Angle of twist", "rad"),
    "spring_rate_N_m": ("Spring rate", "N/m"), "wahl_factor": ("Wahl factor", ""),
    "solid_length_m": ("Solid length", "m"), "resonant_freq_hz": ("Resonant frequency", "Hz"),
    "quality_factor": ("Quality factor", ""), "bandwidth_hz": ("Bandwidth", "Hz"),
    "stall_current_A": ("Stall current", "A"), "stall_torque_Nm": ("Stall torque", "N·m"),
    "no_load_speed_rpm": ("No-load speed", "rpm"), "current_A": ("Current", "A"),
    "speed_rpm": ("Speed", "rpm"), "power_W": ("Power", "W"), "efficiency": ("Efficiency", ""),
    "natural_freq_hz": ("Natural frequency", "Hz"), "natural_freq_rad_s": ("Natural frequency", "rad/s"),
    "period_s": ("Period", "s"), "output_power_W": ("Output power", "W"),
    "output_torque": ("Output torque", "N·m"),
    "delta_v_m_s": ("Delta-v", "m/s"), "thrust_N": ("Thrust", "N"),
    "hover_power_W": ("Hover power", "W"), "endurance_min": ("Endurance", "min"),
    "thrust_per_rotor_N": ("Thrust per rotor", "N"),
    "overshoot_pct": ("Overshoot", "%"), "final_error_rad": ("Final error", "rad"),
    "final_theta_rad": ("Final angle", "rad"),
    "steady_state_error_rad": ("Steady-state error", "rad"),
    "overshoot_percent": ("Overshoot", "%"),
    "delta_v_km_s": ("Delta-v", "km/s"), "mass_ratio": ("Mass ratio", ""),
    "propellant_kg": ("Propellant", "kg"),
    "settling_time_s": ("Settling time", "s"), "max_current_A": ("Max current", "A"),
    "end_position": ("End position", "m"),
}


def _fmt(value):
    if value is None:
        return "—"
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "(" + ", ".join(_fmt(v) for v in value) + ")"
    if isinstance(value, float):
        if value == 0:
            return "0"
        if abs(value) >= 10000:
            return f"{value:,.2f}"
        if abs(value) < 0.001 and value != 0:
            return f"{value:.3e}"
        if abs(value) >= 100:
            return f"{value:.2f}"
        if abs(value) >= 1:
            return f"{value:.3f}"
        return f"{value:.4f}"
    return str(value)


def _material_props(ctx, material_id):
    import db as dbmod
    mat = dbmod.fetch_material(ctx["conn"], material_id)
    if mat is None:
        raise ToolInputError([], f"material '{material_id}' is not in the database")
    return mat["properties"], mat


def _run_solver_tool(ctx, tool_name, inputs, raw_text):
    import solvers as solversmod
    props = {}
    material_id = inputs.get("material_id")
    if material_id:
        props, _ = _material_props(ctx, material_id)
    solver_inputs = dict(inputs)
    # Sections are parsed from the raw text (or a stated default);
    # the solver refuses an empty section, so never pass {}.
    if tool_name in ("cantilever_beam", "simply_supported_beam"):
        sec = parse_section(raw_text) or DEFAULT_BEAM_SECTION
        solver_inputs["section"] = sec
        solver_inputs["material_id"] = material_id or "steel-s355"
        if "section" not in raw_text.lower():
            solver_inputs.setdefault("_assumption_section", True)
    if tool_name == "column_buckling":
        sec = parse_section(raw_text) or DEFAULT_COLUMN_SECTION
        solver_inputs["section"] = sec
        solver_inputs["material_id"] = material_id or "steel-s355"
        solver_inputs.setdefault("k_factor", 1.0)
    if tool_name == "gear_train":
        solver_inputs.setdefault("pressure_angle_deg", 20.0)
    if tool_name == "airfoil_lift":
        # The code comes from the text ("naca2412"), not from a number.
        m = re.search(r"naca\d{4}", raw_text.lower())
        solver_inputs["airfoil_code"] = m.group(0) if m else "naca2412"
    solver_inputs.pop("section", None) if tool_name not in (
        "cantilever_beam", "simply_supported_beam", "column_buckling") else None
    result = solversmod.run_solver(tool_name, solver_inputs, props or None)
    assumptions = []
    if tool_name in ("cantilever_beam", "simply_supported_beam") and \
            "section" not in raw_text.lower():
        assumptions.append("Section not given — assumed rectangle 0.1 × 0.2 m.")
    if tool_name == "column_buckling" and "section" not in raw_text.lower():
        assumptions.append("Section not given — assumed square 0.1 × 0.1 m.")
    if tool_name == "column_buckling":
        assumptions.append("End condition: pinned–pinned (k = 1.0).")
    if material_id:
        assumptions.append(f"Material {material_id} (database values).")
    return {"tool": tool_name, "values": result,
            "provenance": "verified calculation",
            "source": f"{tool_name} analytical solver (Stage 6/7)",
            "assumptions": assumptions}


def _material_lookup(ctx, inputs, raw_text):
    import db as dbmod
    query = inputs.get("query") or ""
    if query and re.fullmatch(r"-?\d+(?:\.\d+)?", query):
        query = ""  # a bare number from the parser, not a material name
    if not query:
        m = re.search(r"([a-z]+-[a-z0-9\-]+)", raw_text.lower())
        if m:
            query = m.group(1)
    if not query:
        low = raw_text.lower()
        for filler in ("properties of", "property of", "material", "lookup",
                       "show me", "what are the", "tell me about", "please",
                       "the", "of"):
            low = low.replace(filler, " ")
        query = " ".join(low.split())[:60]
    if not query:
        raise ToolInputError([{"key": "query", "label": "material name or id", "unit": ""}],
                             "Which material? For example: steel S355.")
    rows = dbmod.fetch_materials(ctx["conn"], "WHERE id LIKE ? OR name LIKE ?",
                                 ("%" + query + "%", "%" + query + "%"))
    if not rows:
        rows = dbmod.fetch_materials(ctx["conn"], "WHERE id = ?", (query,))
    if not rows:
        raise ToolInputError([], f"no material matching '{query}' is in the database")
    mat = dbmod.fetch_material(ctx["conn"], rows[0]["id"])
    props = {k: v for k, v in mat["properties"].items() if v is not None}
    return {"tool": "material_lookup", "values": props,
            "material": {"id": mat["id"], "name": mat["name"],
                         "category": mat["category"], "standard": mat.get("standard"),
                         "source": mat.get("source")},
            "provenance": "database value",
            "source": f"materials database ({mat.get('source') or 'typical published values'})",
            "assumptions": ["Missing properties are not shown — never zero or invented."]}


def _material_compare(ctx, inputs, raw_text):
    import db as dbmod
    ids = []
    raw_ids = inputs.get("ids") or ""
    if raw_ids:
        ids = [s.strip() for s in re.split(r"[,\s]+and\s+|[,\s]+", raw_ids) if s.strip()]
    if len(ids) < 2:
        found = re.findall(r"([a-z]+-[a-z0-9\-]+)", raw_text.lower())
        ids = found[:4]
    if len(ids) < 2:
        low = raw_text.lower()
        m = re.search(r"compare\s+(.+?)\s+(?:and|vs|with)\s+(.+)", low)
        if m:
            ids = [m.group(1).strip(), m.group(2).strip()]
    if len(ids) < 2:
        raise ToolInputError([{"key": "ids", "label": "two material ids", "unit": ""}],
                             "Compare which two materials? For example: steel-s355 and alu-6061-t6.")
    mats = []
    for mid in ids[:4]:
        mat = dbmod.fetch_material(ctx["conn"], mid)
        if mat is None:
            rows = dbmod.fetch_materials(ctx["conn"], "WHERE name LIKE ?", ("%" + mid + "%",))
            mat = dbmod.fetch_material(ctx["conn"], rows[0]["id"]) if rows else None
        if mat is None:
            raise ToolInputError([], f"material '{mid}' is not in the database")
        mats.append(mat)
    keys = ["density_kg_m3", "elastic_modulus_gpa", "yield_strength_mpa",
            "tensile_strength_mpa", "cost_index"]
    table = {k: [m["properties"].get(k) for m in mats] for k in keys}
    return {"tool": "material_compare", "values": table,
            "materials": [{"id": m["id"], "name": m["name"]} for m in mats],
            "provenance": "database value",
            "source": "materials database (typical published values)",
            "assumptions": []}


def _ohm_law(ctx, inputs, raw_text):
    given = {k: v for k, v in inputs.items()
             if k in ("voltage_V", "current_A", "resistance_ohm") and v is not None}
    if len(given) != 2:
        raise ToolInputError([], "Ohm's law needs exactly two of voltage, current, resistance — for example '12 V, 2 A'.")
    if "voltage_V" not in given:
        given["voltage_V"] = given["current_A"] * given["resistance_ohm"]
    elif "current_A" not in given:
        given["current_A"] = given["voltage_V"] / given["resistance_ohm"]
    else:
        given["resistance_ohm"] = given["voltage_V"] / given["current_A"]
    return {"tool": "ohm_law", "values": given,
            "provenance": "verified calculation",
            "source": "Ohm's law V = I·R",
            "assumptions": []}


def _voltage_divider(ctx, inputs, raw_text):
    import circuit as circuitmod
    v = inputs["voltage_V"]; r1 = inputs["r1_ohm"]; r2 = inputs["r2_ohm"]
    circuit = {"name": "Voltage divider (assistant)",
               "components": [
                   {"id": "V1", "type": "voltage_source", "nodes": ["in", "0"],
                    "params": {"value": v}},
                   {"id": "R1", "type": "resistor", "nodes": ["in", "out"],
                    "params": {"value": r1, "rating_W": 0.25}},
                   {"id": "R2", "type": "resistor", "nodes": ["out", "0"],
                    "params": {"value": r2, "rating_W": 0.25}}]}
    errors = circuitmod.validate_circuit(circuit)
    if errors:
        raise ToolInputError([], "circuit failed validation: " + "; ".join(errors))
    result = circuitmod.simulate_dc(circuit)
    vout = (result.get("voltages") or {}).get("out")
    if vout is None:
        raise ToolInputError([], "the circuit solver did not return an output voltage")
    return {"tool": "circuit_voltage_divider", "values": {
                "supply_V": v, "r1_ohm": r1, "r2_ohm": r2,
                "vout_V": vout, "current_A": (v - vout) / r1},
            "circuit": circuit,
            "provenance": "actual simulation result",
            "source": "MNA circuit solver (Stage 8), DC analysis",
            "assumptions": ["Ideal voltage source and resistors."]}


def _rocket_delta_v(ctx, inputs, raw_text):
    import aerospace as aeromod
    stage = {"isp_s": inputs["isp_s"], "m0_kg": inputs["m0_kg"],
             "mf_kg": inputs["mf_kg"], "name": "stage 1"}
    result = aeromod.rocket_delta_v([stage])
    stage_result = result["stages"][0]
    return {"tool": "rocket_delta_v",
            "values": {"delta_v_m_s": result["total_delta_v_m_s"],
                       "delta_v_km_s": result["total_delta_v_km_s"],
                       "mass_ratio": stage_result["mass_ratio"],
                       "propellant_kg": stage_result["propellant_kg"]},
            "provenance": "verified calculation",
            "source": "Tsiolkovsky rocket equation (Stage 10)",
            "assumptions": ["Single stage, vacuum delta-v (no gravity or drag losses)."]}


def _forward_kinematics(ctx, inputs, raw_text):
    import robotics as robotmod
    dh_text = inputs.get("dh") or ""
    joints_text = inputs.get("joints") or ""
    dh = None
    if dh_text:
        try:
            dh = json.loads(dh_text)
        except (ValueError, TypeError):
            dh = None
    if dh is None:
        # Plain-language form: link lengths then joint angles.
        nums = parse_numbers(raw_text)
        lengths = [n["value"] for n in nums if n["kind"] == "length"]
        jm = re.search(r"joints?\s+([-\d,\s.]+)", raw_text.lower())
        angles = _parse_list_floats(jm.group(1)) if jm else []
        if not lengths or not angles or len(lengths) != len(angles):
            raise ToolInputError(
                [{"key": "dh", "label": "link lengths and joint angles", "unit": ""}],
                "Give me the link lengths and joint angles — for example "
                "'FK, links 0.4 and 0.35 m, joints 30, 45 degrees'.")
        dh = [{"a": L, "alpha": 0, "d": 0, "theta": 0, "type": "revolute"}
              for L in lengths]
        joints = [math.radians(a) for a in angles]
    else:
        joints = [math.radians(a) for a in _parse_list_floats(joints_text)] \
            if joints_text else [0.0] * len(dh)
    result = robotmod.fk_dh(dh, joints)
    return {"tool": "forward_kinematics", "values": {
                "end_position": result["end_position"],
                "joint_positions": result["positions"]},
            "provenance": "verified calculation",
            "source": "Denavit-Hartenberg forward kinematics (Stage 10)",
            "assumptions": ["Planar revolute joints; angles in degrees in the message."]}


def _ik_2r(ctx, inputs, raw_text):
    import robotics as robotmod
    target = _parse_target_xy(raw_text)
    if target is None:
        raise ToolInputError([{"key": "target", "label": "target (x, y) in m", "unit": "m"}],
                             "Where should the end effector go? For example 'IK to (1, 1)'.")
    result = robotmod.ik_2r(inputs["l1"], inputs["l2"], target[0], target[1])
    return {"tool": "ik_2r", "values": result,
            "provenance": "verified calculation",
            "source": "analytic 2R inverse kinematics (Stage 10)",
            "assumptions": ["Planar 2R arm, elbow-up and elbow-down solutions."]}


def _pid_control(ctx, inputs, raw_text):
    import robotics as robotmod
    motor = dict(PID_MOTOR)
    motor.update({"setpoint_rad": inputs.get("setpoint_rad", 1.0),
                  "kp": inputs["kp"], "ki": inputs.get("ki", 0.0),
                  "kd": inputs.get("kd", 0.0), "duration_s": 5.0, "dt_s": 0.001})
    result = robotmod.pid_simulate(motor)
    # Keep only the scalar metrics — the time series is large and
    # belongs in the robotics lab, not in a chat message.
    metrics = {k: v for k, v in result.items() if k != "series"}
    metrics["overshoot_pct"] = metrics.pop("overshoot_percent", None)
    return {"tool": "pid_control", "values": metrics,
            "provenance": "verified calculation",
            "source": "PID simulation on the Stage 8 DC-motor model (Stage 10)",
            "assumptions": ["Motor: R 1.5 Ω, L 1 mH, Kt = Ke = 0.05, J 0.01 kg·m², "
                            "12 V limit, 5 s simulation."]}


def _project_inspect(ctx, inputs, raw_text):
    project = ctx.get("project")
    if project is None:
        raise ToolInputError([], "No project is attached to this conversation. "
                                 "Attach one of your projects first, then ask again.")
    payload = ctx.get("project_payload") or {}
    docs = {}
    for key in ("model", "structure", "aerospace", "robot"):
        if isinstance(payload.get(key), dict):
            docs[key] = {"version": payload[key].get("version"),
                         "kind": payload[key].get("kind")}
    rows = ctx["conn"].execute(
        "SELECT solver, status, created_at FROM simulations "
        "WHERE project_id=? AND owner_id=? ORDER BY created_at DESC LIMIT 5",
        (project["id"], ctx["user_id"])).fetchall()
    recent = [{"solver": r["solver"], "status": r["status"],
               "created_at": r["created_at"]} for r in rows]
    return {"tool": "project_inspect",
            "values": {"project_name": project.get("name"),
                       "documents": docs, "recent_simulations": recent},
            "provenance": "database value",
            "source": "your project (owner-verified read)",
            "assumptions": []}


def _project_propose(ctx, inputs, raw_text):
    project = ctx.get("project")
    if project is None:
        raise ToolInputError([], "No project is attached to this conversation. "
                                 "Attach one of your projects first.")
    payload = ctx.get("project_payload") or {}
    low = raw_text.lower()
    # Supported change 1: a structure element's section.
    sec = parse_section(raw_text)
    if "structure" in payload and isinstance(payload.get("structure"), dict) \
            and sec and ("section" in low or "beam" in low or "bigger" in low
                         or "smaller" in low or "stronger" in low):
        elements = payload["structure"].get("elements") or []
        target = None
        for el in elements:
            if isinstance(el, dict) and el.get("id") and \
                    str(el.get("id")).lower() in low:
                target = el
                break
        if target is None and elements:
            target = elements[0] if isinstance(elements[0], dict) else None
        if target is not None:
            return {"tool": "project_propose", "proposal": {
                        "target": "structure",
                        "element_id": target.get("id"),
                        "change": {"section": sec},
                        "summary": f"Change section of element "
                                   f"'{target.get('id')}' to "
                                   f"{sec['type']} "
                                   f"{_fmt(sec.get('b_m', sec.get('d_m', 0)) * 1000)} × "
                                   f"{_fmt(sec.get('h_m', 0) * 1000)} mm" if sec["type"] == "rectangle"
                                   else f"Change section of element '{target.get('id')}' to circle d "
                                        f"{_fmt(sec['d_m'] * 1000)} mm"},
                    "provenance": "proposal",
                    "source": "assistant proposal — needs your approval",
                    "assumptions": []}
    # Supported change 2: an aircraft design field.
    if "aerospace" in payload and isinstance(payload.get("aerospace"), dict):
        nums = parse_numbers(raw_text)
        for key, aliases in (("cruise_speed_m_s", ("cruise speed", "cruise")),
                             ("mass_kg", ("mass",))):
            for alias in aliases:
                if alias in low and nums:
                    return {"tool": "project_propose", "proposal": {
                                "target": "aerospace",
                                "change": {key: nums[0]["value"]},
                                "summary": f"Set {key.replace('_', ' ')} to "
                                           f"{_fmt(nums[0]['value'])}"},
                            "provenance": "proposal",
                            "source": "assistant proposal — needs your approval",
                            "assumptions": []}
    return {"tool": "project_propose", "proposal": None,
            "provenance": "proposal",
            "source": "assistant proposal — needs your approval",
            "assumptions": [],
            "unsupported": "I can propose a structure element's section or an "
                           "aircraft cruise speed / mass for now. Tell me one of "
                           "those — for example 'change the beam section to "
                           "0.2x0.3 m'."}


_EXECUTORS = {
    "solver": _run_solver_tool,
    "material_lookup": _material_lookup,
    "material_compare": _material_compare,
    "ohm_law": _ohm_law,
    "voltage_divider": _voltage_divider,
    "rocket_delta_v": _rocket_delta_v,
    "forward_kinematics": _forward_kinematics,
    "ik_2r": _ik_2r,
    "pid_control": _pid_control,
    "project_inspect": _project_inspect,
    "project_propose": _project_propose,
}


def execute_tool(ctx, tool_def, inputs, raw_text):
    """Run a tool through the existing engines. Returns the result
    dict. Raises ToolInputError (missing/invalid input) or
    ValueError (the underlying solver refused the input)."""
    executor = _EXECUTORS[tool_def["executor"]]
    if executor is _run_solver_tool:
        return executor(ctx, tool_def["name"], inputs, raw_text)
    return executor(ctx, inputs, raw_text)


def tool_summary(tool_def):
    return {"name": tool_def["name"], "label": tool_def["label"],
            "lab": tool_def["lab"],
            "params": [{"key": p["key"], "label": p["label"],
                        "unit": p["unit"], "optional": p["optional"]}
                       for p in tool_def["params"]]}


# ------------------------------------------------------------------ replies
def format_result(tool_def, result):
    """Render a tool result as a short, honest reply with units,
    provenance and assumptions. Numbers come only from `result`."""
    lines = []
    label = tool_def["label"]
    values = result.get("values", {})
    if tool_def["name"] == "material_lookup":
        mat = result.get("material", {})
        lines.append(f"**{mat.get('name', '')}** ({mat.get('id', '')}) — "
                     f"{mat.get('category', '')}, standard {mat.get('standard') or '—'}.")
        for key in ("density_kg_m3", "elastic_modulus_gpa", "yield_strength_mpa",
                    "tensile_strength_mpa", "poisson_ratio", "thermal_conductivity_w_mk"):
            if key in values:
                unit = {"density_kg_m3": "kg/m³", "elastic_modulus_gpa": "GPa",
                        "yield_strength_mpa": "MPa", "tensile_strength_mpa": "MPa",
                        "poisson_ratio": "", "thermal_conductivity_w_mk": "W/m·K"}[key]
                lines.append(f"- {key.replace('_', ' ')}: {_fmt(values[key])} {unit}".rstrip())
        lines.append(f"Source: {result.get('source')}.")
    elif tool_def["name"] == "material_compare":
        mats = result.get("materials", [])
        lines.append("Comparison (database values):")
        header = "| Property | " + " | ".join(m["name"] for m in mats) + " |"
        lines.append(header)
        lines.append("|" + " --- |" * (len(mats) + 1))
        for key, row in values.items():
            cells = " | ".join(_fmt(v) for v in row)
            lines.append(f"| {key.replace('_', ' ')} | {cells} |")
    elif tool_def["name"] == "project_inspect":
        lines.append(f"Project **{values.get('project_name')}**:")
        docs = values.get("documents", {})
        if docs:
            for k, v in docs.items():
                lines.append(f"- {k}: version {v.get('version')} "
                             f"({v.get('kind') or '—'})")
        else:
            lines.append("- No design documents saved yet (model, structure, aerospace, robot).")
        recent = values.get("recent_simulations", [])
        if recent:
            lines.append("Recent simulations:")
            for s in recent:
                lines.append(f"- {s.get('solver')}: {s.get('status')}")
        else:
            lines.append("- No simulations run yet.")
    else:
        lines.append(f"**{label}** — {result.get('provenance')}.")
        if isinstance(values, dict):
            for key, val in values.items():
                if key.startswith("_") or val is None:
                    continue
                lab, unit = VALUE_LABELS.get(key, (key.replace("_", " "), ""))
                if isinstance(val, (dict, list)) and key not in ("end_position",):
                    continue
                lines.append(f"- {lab}: {_fmt(val)} {unit}".rstrip())
            if "end_position" in values:
                lines.append(f"- End position: {_fmt(values['end_position'])} m")
    for a in result.get("assumptions", []):
        lines.append(f"Assumption: {a}")
    lines.append(f"Provenance: {result.get('provenance')} — {result.get('source')}.")
    return "\n".join(lines)
