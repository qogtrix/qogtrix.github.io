/* AI Engineering Laboratory — modelling maths (Stage 5).
   Pure JavaScript, no Three.js, no DOM: units, analytic volumes,
   and model validation. The same rules are mirrored in
   backend/model.py, and this file is directly testable with Node
   (test_stage5_math.js). Volumes are in mm^3. Analytic volumes
   are marked exact:false where a closed-form value is not
   available (rounded boxes, gears, bearings, booleans) — the
   browser computes exact mesh volumes instead (see model-kernel.js).
   Never invent a volume: unknown means null. */
(function (root) {
  'use strict';

  var UNITS = { mm: 1, cm: 10, m: 1000, in: 25.4 };
  var PRIMITIVE_KINDS = ['box', 'cylinder', 'sphere', 'cone', 'torus',
    'rounded_box', 'chamfered_box', 'extrude', 'revolve'];
  var COMPONENT_KINDS = ['gear', 'shaft', 'bearing', 'bolt', 'nut',
    'spring', 'piston', 'pipe', 'beam', 'motor', 'enclosure',
    'crankshaft', 'connecting_rod', 'flywheel', 'clutch', 'brake_disc',
    'coupling', 'pulley', 'sprocket', 'hydraulic_cylinder', 'valve', 'pump'];
  var BOOLEAN_OPS = ['union', 'subtract', 'intersect'];

  function toMM(value, unit) {
    if (typeof value !== 'number' || !isFinite(value)) return NaN;
    var f = UNITS[unit];
    if (f === undefined) return NaN;
    return value * f;
  }
  function fromMM(valueMM, unit) {
    var f = UNITS[unit];
    if (f === undefined) return NaN;
    return valueMM / f;
  }
  function convert(value, fromUnit, toUnit) {
    return fromMM(toMM(value, fromUnit), toUnit);
  }

  // -- geometry helpers -------------------------------------------------
  function polygonArea(points) {
    // Shoelace formula. Points: [[x, y], ...]; auto-closes.
    var a = 0;
    for (var i = 0; i < points.length; i++) {
      var p = points[i], q = points[(i + 1) % points.length];
      a += p[0] * q[1] - q[0] * p[1];
    }
    return Math.abs(a) / 2;
  }
  function polygonCentroidX(points) {
    var cx = 0, a = 0;
    for (var i = 0; i < points.length; i++) {
      var p = points[i], q = points[(i + 1) % points.length];
      var cross = p[0] * q[1] - q[0] * p[1];
      cx += (p[0] + q[0]) * cross;
      a += cross;
    }
    if (a === 0) return 0;
    return cx / (3 * a);
  }

  // -- analytic volumes -------------------------------------------------
  // Returns { value: number|null, exact: boolean, note: string }.
  // value is in mm^3. null means "cannot be computed analytically".
  function analyticVolume(comp) {
    var p = comp.params || {};
    function num(v) { return (typeof v === 'number' && isFinite(v)) ? v : null; }
    switch (comp.kind) {
      case 'box': {
        var l = num(p.length), w = num(p.width), h = num(p.height);
        if (l == null || w == null || h == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: l * w * h, exact: true, note: '' };
      }
      case 'cylinder': {
        var r = num(p.radius), hh = num(p.height);
        if (r == null || hh == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: Math.PI * r * r * hh, exact: true, note: '' };
      }
      case 'sphere': {
        var rs = num(p.radius);
        if (rs == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: 4 / 3 * Math.PI * rs * rs * rs, exact: true, note: '' };
      }
      case 'cone': {
        var rc = num(p.radius), hc = num(p.height);
        if (rc == null || hc == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: Math.PI * rc * rc * hc / 3, exact: true, note: '' };
      }
      case 'torus': {
        var R = num(p.radius), r2 = num(p.tube);
        if (R == null || r2 == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: 2 * Math.PI * Math.PI * R * r2 * r2, exact: true, note: '' };
      }
      case 'rounded_box': {
        var lb = num(p.length), wb = num(p.width), hb = num(p.height);
        if (lb == null || wb == null || hb == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: lb * wb * hb, exact: false, note: 'estimate: rounded corners ignored' };
      }
      case 'chamfered_box': {
        var lc = num(p.length), wc = num(p.width), hc2 = num(p.height), ch = num(p.chamfer);
        if (lc == null || wc == null || hc2 == null || ch == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: (lc * wc - 2 * ch * ch) * hc2, exact: true, note: 'chamfer on the 4 vertical edges' };
      }
      case 'extrude': {
        if (!Array.isArray(p.profile) || p.profile.length < 3) return { value: null, exact: false, note: 'profile needs at least 3 points' };
        var area = polygonArea(p.profile);
        (p.holes || []).forEach(function (hole) { area -= polygonArea(hole); });
        var depth = num(p.depth);
        if (depth == null) return { value: null, exact: false, note: 'missing depth' };
        return { value: area * depth, exact: true, note: '' };
      }
      case 'revolve': {
        if (!Array.isArray(p.profile) || p.profile.length < 2) return { value: null, exact: false, note: 'profile needs at least 2 points' };
        var a2 = polygonArea(p.profile);
        var cx = polygonCentroidX(p.profile);
        var angle = num(p.angle);
        if (angle == null) return { value: null, exact: false, note: 'missing angle' };
        // Pappus centroid theorem (profile must not cross the axis).
        return { value: a2 * 2 * Math.PI * Math.abs(cx) * angle / 360, exact: true, note: '' };
      }
      case 'shaft': {
        if (!Array.isArray(p.diameters) || !Array.isArray(p.lengths) || p.diameters.length !== p.lengths.length) return { value: null, exact: false, note: 'diameters and lengths must match' };
        var v = 0;
        for (var i = 0; i < p.diameters.length; i++) {
          var d = p.diameters[i], L = p.lengths[i];
          if (typeof d !== 'number' || typeof L !== 'number') return { value: null, exact: false, note: 'bad step' };
          v += Math.PI * (d / 2) * (d / 2) * L;
        }
        return { value: v, exact: true, note: '' };
      }
      case 'pipe': {
        var Do = num(p.outer_diameter), Di = num(p.inner_diameter), Lp = num(p.length);
        if (Do == null || Di == null || Lp == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: Math.PI / 4 * (Do * Do - Di * Di) * Lp, exact: true, note: '' };
      }
      case 'beam': {
        var Lb = num(p.length), Hb = num(p.height), fw = num(p.flange_width),
            ft = num(p.flange_thickness), wt = num(p.web_thickness);
        if (Lb == null || Hb == null || fw == null || ft == null || wt == null) return { value: null, exact: false, note: 'missing dimension' };
        var areaB = 2 * fw * ft + (Hb - 2 * ft) * wt;
        return { value: areaB * Lb, exact: true, note: '' };
      }
      case 'bolt': {
        var db = num(p.diameter), Lb2 = num(p.length), hh2 = num(p.head_height);
        if (db == null || Lb2 == null || hh2 == null) return { value: null, exact: false, note: 'missing dimension' };
        var acrossFlats = 1.8 * db;
        var hexArea = Math.sqrt(3) / 2 * acrossFlats * acrossFlats;
        return { value: Math.PI * (db / 2) * (db / 2) * Lb2 + hexArea * hh2, exact: true, note: '' };
      }
      case 'nut': {
        var dn = num(p.diameter), hn = num(p.height);
        if (dn == null || hn == null) return { value: null, exact: false, note: 'missing dimension' };
        var af = 1.8 * dn;
        var hexA = Math.sqrt(3) / 2 * af * af;
        return { value: hexA * hn - Math.PI * (dn / 2) * (dn / 2) * hn, exact: true, note: '' };
      }
      case 'spring': {
        var cd = num(p.coil_diameter), wd = num(p.wire_diameter), coils = num(p.coils), Ls = num(p.length);
        if (cd == null || wd == null || coils == null || Ls == null) return { value: null, exact: false, note: 'missing dimension' };
        var pitch = Ls / coils;
        var helixLen = coils * Math.sqrt(Math.pow(Math.PI * cd, 2) + pitch * pitch);
        return { value: Math.PI * (wd / 2) * (wd / 2) * helixLen, exact: true, note: '' };
      }
      case 'piston': {
        var dp = num(p.diameter), hp = num(p.height);
        if (dp == null || hp == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: Math.PI * (dp / 2) * (dp / 2) * hp, exact: false, note: 'estimate: ring grooves ignored' };
      }
      case 'motor': {
        var dm = num(p.diameter), Lm = num(p.length), sd = num(p.shaft_diameter), sl = num(p.shaft_length);
        if (dm == null || Lm == null || sd == null || sl == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: Math.PI * (dm / 2) * (dm / 2) * Lm + Math.PI * (sd / 2) * (sd / 2) * sl, exact: true, note: '' };
      }
      case 'enclosure': {
        var le = num(p.length), we = num(p.width), he = num(p.height), th = num(p.wall_thickness);
        if (le == null || we == null || he == null || th == null) return { value: null, exact: false, note: 'missing dimension' };
        var inner = Math.max(0, le - 2 * th) * Math.max(0, we - 2 * th) * Math.max(0, he - th);
        return { value: le * we * he - inner, exact: true, note: 'open-top shell' };
      }
      case 'gear': {
        var mod = num(p.module), teeth = num(p.teeth), tg = num(p.thickness), bore = num(p.bore_diameter);
        if (mod == null || teeth == null || tg == null) return { value: null, exact: false, note: 'missing dimension' };
        var pitchD = mod * teeth;
        var outerD = pitchD + 2 * mod;
        var vGear = Math.PI * (outerD / 2) * (outerD / 2) * tg * 0.9;
        if (bore != null) vGear -= Math.PI * (bore / 2) * (bore / 2) * tg;
        return { value: vGear, exact: false, note: 'estimate: teeth approximated as 90% of the outer cylinder' };
      }
      case 'bearing': {
        var bo = num(p.outer_diameter), bi = num(p.bore_diameter), wb2 = num(p.width);
        if (bo == null || bi == null || wb2 == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: Math.PI / 4 * (bo * bo - bi * bi) * wb2, exact: false, note: 'estimate: balls and races ignored' };
      }
      case 'crankshaft': {
        var md = num(p.main_diameter), cd2 = num(p.crank_diameter), th = num(p.throw), Lj = num(p.length);
        if (md == null || cd2 == null || th == null || Lj == null) return { value: null, exact: false, note: 'missing dimension' };
        // Estimate: two main journals + one crank pin + two webs (boxes).
        var vCrank = Math.PI * (md / 2) * (md / 2) * Lj * 0.7
          + Math.PI * (cd2 / 2) * (cd2 / 2) * 24
          + 2 * 8 * (th + md / 2 + cd2 / 2) * md;
        return { value: vCrank, exact: false, note: 'estimate: webs approximated as boxes' };
      }
      case 'connecting_rod': {
        var bd = num(p.big_diameter), sd = num(p.small_diameter), Lr = num(p.length), wr = num(p.width);
        if (bd == null || sd == null || Lr == null || wr == null) return { value: null, exact: false, note: 'missing dimension' };
        var bigRing = Math.PI / 4 * (bd * bd - Math.pow(bd * 0.6, 2)) * wr;
        var smallRing = Math.PI / 4 * (sd * sd - Math.pow(sd * 0.5, 2)) * wr;
        var shankLen = Math.max(0, Lr - (bd + sd) / 2);
        return { value: bigRing + smallRing + shankLen * wr * wr * 0.6, exact: false, note: 'estimate: bore sizes assumed (big 60%, small 50% of outer)' };
      }
      case 'flywheel': {
        var Df = num(p.diameter), tf = num(p.thickness), hub = num(p.hub_diameter), bore = num(p.bore_diameter);
        if (Df == null || tf == null || hub == null) return { value: null, exact: false, note: 'missing dimension' };
        var vFly = Math.PI / 4 * (Df * Df - (bore || 0) * (bore || 0)) * tf
          + Math.PI / 4 * hub * hub * 16;
        return { value: vFly, exact: true, note: 'disc with bore + hub ring' };
      }
      case 'clutch': {
        var Dc = num(p.diameter), tc = num(p.thickness), boreC = num(p.bore_diameter);
        if (Dc == null || tc == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: Math.PI / 4 * (Dc * Dc - (boreC || 0) * (boreC || 0)) * tc, exact: true, note: 'plate pack as one annulus' };
      }
      case 'brake_disc': {
        var Db = num(p.diameter), tb = num(p.thickness), boreB = num(p.bore_diameter), hubB = num(p.hub_diameter);
        if (Db == null || tb == null) return { value: null, exact: false, note: 'missing dimension' };
        var vBrake = Math.PI / 4 * (Db * Db - (boreB || 0) * (boreB || 0)) * tb;
        if (hubB != null) vBrake += Math.PI / 4 * hubB * hubB * tb;
        return { value: vBrake, exact: true, note: '' };
      }
      case 'coupling': {
        var Dcp = num(p.diameter), Lcp = num(p.length), boreCp = num(p.bore_diameter);
        if (Dcp == null || Lcp == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: Math.PI / 4 * (Dcp * Dcp - (boreCp || 0) * (boreCp || 0)) * Lcp, exact: false, note: 'estimate: bolts ignored' };
      }
      case 'pulley': {
        var Dp = num(p.diameter), wp = num(p.width), boreP = num(p.bore_diameter), gd = num(p.groove_depth);
        if (Dp == null || wp == null) return { value: null, exact: false, note: 'missing dimension' };
        var vPul = Math.PI / 4 * (Dp * Dp - (boreP || 0) * (boreP || 0)) * wp;
        if (gd != null) vPul -= Math.PI * Dp * gd * gd; // V-groove material removed (approx.)
        return { value: Math.max(0, vPul), exact: false, note: 'estimate: V-groove approximated' };
      }
      case 'sprocket': {
        var teethS = num(p.teeth), pitch = num(p.pitch), ts = num(p.thickness), boreS = num(p.bore_diameter);
        if (teethS == null || pitch == null || ts == null) return { value: null, exact: false, note: 'missing dimension' };
        var pd = pitch / Math.sin(Math.PI / teethS);
        var outer = pd + pitch * 0.6;
        var vSpr = Math.PI / 4 * (outer * outer - (boreS || 0) * (boreS || 0)) * ts * 0.85;
        return { value: vSpr, exact: false, note: 'estimate: teeth approximated as 85% of the outer cylinder' };
      }
      case 'hydraulic_cylinder': {
        var boreH = num(p.bore_diameter), rod = num(p.rod_diameter), stroke = num(p.stroke), barrel = num(p.barrel_length);
        if (boreH == null || rod == null || stroke == null || barrel == null) return { value: null, exact: false, note: 'missing dimension' };
        var wall = 5; // assumed barrel wall thickness, mm (stated in docs)
        var vHyd = Math.PI / 4 * (Math.pow(boreH + 2 * wall, 2) - boreH * boreH) * barrel
          + Math.PI / 4 * rod * rod * (stroke + barrel / 2);
        return { value: vHyd, exact: false, note: 'estimate: barrel wall assumed 5 mm' };
      }
      case 'valve': {
        var bl = num(p.body_length), bw = num(p.body_width), bh = num(p.body_height),
            bon = num(p.bonnet_diameter), hw = num(p.handwheel_diameter);
        if (bl == null || bw == null || bh == null || bon == null || hw == null) return { value: null, exact: false, note: 'missing dimension' };
        var vValve = bl * bw * bh + Math.PI / 4 * bon * bon * (bh / 2)
          + 2 * Math.PI * Math.PI * (hw / 2) * 3 * 3;
        return { value: vValve, exact: false, note: 'estimate: handwheel tube assumed 3 mm' };
      }
      case 'pump': {
        var Dh = num(p.housing_diameter), Lh = num(p.housing_length), imp = num(p.impeller_diameter);
        if (Dh == null || Lh == null || imp == null) return { value: null, exact: false, note: 'missing dimension' };
        return { value: Math.PI / 4 * Dh * Dh * Lh + Math.PI / 4 * imp * imp * (Lh / 3) * 0.5,
                 exact: false, note: 'estimate: impeller vanes approximated' };
      }
      case 'boolean':
        return { value: null, exact: false, note: 'boolean volume needs the mesh — computed in the browser' };
      case 'mesh':
        return { value: null, exact: false, note: 'imported mesh volume is computed in the browser' };
      default:
        return { value: null, exact: false, note: 'unknown kind: ' + comp.kind };
    }
  }

  // -- model validation ---------------------------------------------------
  // materialIds: Set/array of known Stage 4 material ids, or null to
  // skip the material check. Returns a list of error strings (empty = valid).
  function validateModel(model, materialIds) {
    var errors = [];
    if (!model || typeof model !== 'object') return ['model must be an object'];
    if (typeof model.version !== 'number' || model.version < 1) errors.push('model.version must be a positive integer');
    if (!UNITS.hasOwnProperty(model.units)) errors.push('model.units must be one of: ' + Object.keys(UNITS).join(', '));
    if (!Array.isArray(model.components)) return errors.concat(['model.components must be an array']);
    var ids = {}, byId = {};
    model.components.forEach(function (c, i) {
      var where = 'components[' + i + ']';
      if (!c || typeof c !== 'object') { errors.push(where + ' must be an object'); return; }
      if (typeof c.id !== 'string' || !c.id) { errors.push(where + '.id is required'); return; }
      if (ids[c.id]) errors.push('duplicate component id: ' + c.id);
      ids[c.id] = true; byId[c.id] = c;
      if (typeof c.name !== 'string' || !c.name) errors.push(where + '.name is required');
      if (['primitive', 'component', 'boolean', 'imported'].indexOf(c.type) === -1) errors.push(where + '.type is invalid: ' + c.type);
      if (c.type === 'primitive' && PRIMITIVE_KINDS.indexOf(c.kind) === -1) errors.push(where + '.kind is not a primitive: ' + c.kind);
      if (c.type === 'component' && COMPONENT_KINDS.indexOf(c.kind) === -1) errors.push(where + '.kind is not a library component: ' + c.kind);
      if (c.type === 'boolean' && c.kind !== 'boolean') errors.push(where + '.kind must be "boolean" for a boolean component');
      if (c.type === 'imported' && c.kind !== 'mesh') errors.push(where + '.kind must be "mesh" for an imported component');
      if (!c.params || typeof c.params !== 'object') errors.push(where + '.params is required');
      else validateParams(c, errors, where);
      if (c.material_id != null && materialIds && materialIds.indexOf(c.material_id) === -1) errors.push(where + '.material_id is not in the material database: ' + c.material_id);
      ['position', 'rotation'].forEach(function (k) {
        if (c[k] !== undefined && (!Array.isArray(c[k]) || c[k].length !== 3 || c[k].some(function (v) { return typeof v !== 'number' || !isFinite(v); }))) errors.push(where + '.' + k + ' must be [x, y, z] numbers');
      });
      if (c.scale !== undefined && (!Array.isArray(c.scale) || c.scale.length !== 3 || c.scale.some(function (v) { return typeof v !== 'number' || v <= 0; }))) errors.push(where + '.scale must be three positive numbers');
      if (c.tolerance_mm !== undefined && (typeof c.tolerance_mm !== 'number' || c.tolerance_mm < 0)) errors.push(where + '.tolerance_mm must be >= 0');
      if (c.parent_id != null && typeof c.parent_id !== 'string') errors.push(where + '.parent_id must be a string or null');
    });
    // Cross-component checks: booleans, parents, cycles.
    model.components.forEach(function (c) {
      if (!c || typeof c !== 'object') return;
      if (c.type === 'boolean') {
        var ops = (c.params || {}).operands;
        if (!Array.isArray(ops) || ops.length !== 2) errors.push(c.id + ': boolean needs exactly 2 operands');
        else {
          if (BOOLEAN_OPS.indexOf(c.params.op) === -1) errors.push(c.id + ': boolean op must be union/subtract/intersect');
          ops.forEach(function (op) {
            if (op === c.id) errors.push(c.id + ': boolean cannot use itself as an operand');
            else if (!byId[op]) errors.push(c.id + ': boolean operand not found: ' + op);
          });
        }
      }
      if (c.parent_id) {
        if (!byId[c.parent_id]) errors.push(c.id + ': parent not found: ' + c.parent_id);
        else {
          // Cycle check: walk up the parent chain.
          var seen = {}, cur = c;
          while (cur && cur.parent_id) {
            if (seen[cur.id]) { errors.push('parent cycle involving: ' + c.id); break; }
            seen[cur.id] = true;
            cur = byId[cur.parent_id];
          }
        }
      }
    });
    return errors;
  }

  function validateParams(c, errors, where) {
    var p = c.params;
    function pos(key) {
      if (typeof p[key] !== 'number' || !isFinite(p[key]) || p[key] <= 0) errors.push(where + '.params.' + key + ' must be a positive number');
    }
    function nonNeg(key) {
      if (typeof p[key] !== 'number' || !isFinite(p[key]) || p[key] < 0) errors.push(where + '.params.' + key + ' must be a number >= 0');
    }
    switch (c.kind) {
      case 'box': pos('length'); pos('width'); pos('height'); break;
      case 'cylinder': pos('radius'); pos('height'); break;
      case 'sphere': pos('radius'); break;
      case 'cone': pos('radius'); pos('height'); break;
      case 'torus': pos('radius'); pos('tube'); break;
      case 'rounded_box': pos('length'); pos('width'); pos('height'); pos('radius'); break;
      case 'chamfered_box': pos('length'); pos('width'); pos('height'); pos('chamfer'); break;
      case 'extrude':
        pos('depth');
        if (!Array.isArray(p.profile) || p.profile.length < 3) errors.push(where + '.params.profile needs at least 3 points');
        else if (p.profile.some(function (pt) { return !Array.isArray(pt) || pt.length !== 2 || pt.some(function (v) { return typeof v !== 'number' || !isFinite(v); }); })) errors.push(where + '.params.profile points must be [x, y] numbers');
        (p.holes || []).forEach(function (hole, i) {
          if (!Array.isArray(hole) || hole.length < 3) errors.push(where + '.params.holes[' + i + '] needs at least 3 points');
        });
        break;
      case 'revolve':
        if (typeof p.angle !== 'number' || p.angle <= 0 || p.angle > 360) errors.push(where + '.params.angle must be > 0 and <= 360');
        if (!Array.isArray(p.profile) || p.profile.length < 2) errors.push(where + '.params.profile needs at least 2 points');
        else if (p.profile.some(function (pt) { return !Array.isArray(pt) || pt.length !== 2 || pt.some(function (v) { return typeof v !== 'number' || !isFinite(v); }) || pt[0] < 0; })) errors.push(where + '.params.profile points must be [x, y] numbers with x >= 0');
        break;
      case 'gear':
        pos('module'); pos('thickness');
        if (typeof p.teeth !== 'number' || p.teeth < 6 || Math.floor(p.teeth) !== p.teeth) errors.push(where + '.params.teeth must be an integer >= 6');
        if (p.bore_diameter !== undefined) pos('bore_diameter');
        break;
      case 'shaft':
        if (!Array.isArray(p.diameters) || !Array.isArray(p.lengths) || !p.diameters.length || p.diameters.length !== p.lengths.length) errors.push(where + '.params.diameters and lengths must be non-empty arrays of equal length');
        else { p.diameters.forEach(function (d) { if (typeof d !== 'number' || d <= 0) errors.push(where + '.params.diameters must be positive'); }); p.lengths.forEach(function (L) { if (typeof L !== 'number' || L <= 0) errors.push(where + '.params.lengths must be positive'); }); }
        break;
      case 'bearing': pos('bore_diameter'); pos('outer_diameter'); pos('width'); break;
      case 'bolt': pos('diameter'); pos('length'); pos('head_height'); break;
      case 'nut': pos('diameter'); pos('height'); break;
      case 'spring': pos('coil_diameter'); pos('wire_diameter'); pos('length'); if (typeof p.coils !== 'number' || p.coils < 1) errors.push(where + '.params.coils must be >= 1'); break;
      case 'piston': pos('diameter'); pos('height'); if (p.ring_grooves !== undefined) nonNeg('ring_grooves'); break;
      case 'pipe': pos('outer_diameter'); pos('inner_diameter'); pos('length'); if (p.inner_diameter >= p.outer_diameter) errors.push(where + '.params.inner_diameter must be smaller than outer_diameter'); break;
      case 'beam': pos('length'); pos('height'); pos('flange_width'); pos('flange_thickness'); pos('web_thickness'); break;
      case 'motor': pos('diameter'); pos('length'); pos('shaft_diameter'); pos('shaft_length'); break;
      case 'enclosure': pos('length'); pos('width'); pos('height'); pos('wall_thickness'); break;
      case 'crankshaft':
        pos('main_diameter'); pos('crank_diameter'); pos('throw'); pos('length');
        if (typeof p.journals !== 'number' || p.journals < 2 || Math.floor(p.journals) !== p.journals) errors.push(where + '.params.journals must be an integer >= 2');
        break;
      case 'connecting_rod': pos('big_diameter'); pos('small_diameter'); pos('length'); pos('width'); break;
      case 'flywheel': pos('diameter'); pos('thickness'); pos('hub_diameter'); if (p.bore_diameter !== undefined) pos('bore_diameter'); break;
      case 'clutch':
        pos('diameter'); pos('thickness'); if (p.bore_diameter !== undefined) pos('bore_diameter');
        if (typeof p.plates !== 'number' || p.plates < 1 || Math.floor(p.plates) !== p.plates) errors.push(where + '.params.plates must be an integer >= 1');
        break;
      case 'brake_disc': pos('diameter'); pos('thickness'); if (p.bore_diameter !== undefined) pos('bore_diameter'); if (p.hub_diameter !== undefined) pos('hub_diameter'); break;
      case 'coupling':
        pos('diameter'); pos('length'); if (p.bore_diameter !== undefined) pos('bore_diameter');
        if (typeof p.bolts !== 'number' || p.bolts < 2 || Math.floor(p.bolts) !== p.bolts) errors.push(where + '.params.bolts must be an integer >= 2');
        break;
      case 'pulley': pos('diameter'); pos('width'); if (p.bore_diameter !== undefined) pos('bore_diameter'); if (p.groove_depth !== undefined) pos('groove_depth'); break;
      case 'sprocket':
        pos('pitch'); pos('thickness'); if (p.bore_diameter !== undefined) pos('bore_diameter');
        if (typeof p.teeth !== 'number' || p.teeth < 6 || Math.floor(p.teeth) !== p.teeth) errors.push(where + '.params.teeth must be an integer >= 6');
        break;
      case 'hydraulic_cylinder': pos('bore_diameter'); pos('rod_diameter'); pos('stroke'); pos('barrel_length'); if (p.rod_diameter >= p.bore_diameter) errors.push(where + '.params.rod_diameter must be smaller than bore_diameter'); break;
      case 'valve': pos('body_length'); pos('body_width'); pos('body_height'); pos('bonnet_diameter'); pos('handwheel_diameter'); break;
      case 'pump':
        pos('housing_diameter'); pos('housing_length'); pos('impeller_diameter');
        if (typeof p.vanes !== 'number' || p.vanes < 3 || Math.floor(p.vanes) !== p.vanes) errors.push(where + '.params.vanes must be an integer >= 3');
        break;
      case 'boolean': break; // checked in validateModel
      case 'mesh': break; // imported geometry: validated by the importer
      default: break;
    }
    if (c.kind === 'rounded_box' && typeof p.radius === 'number') {
      var minDim = Math.min(p.length || 0, p.width || 0, p.height || 0);
      if (p.radius * 2 > minDim) errors.push(where + '.params.radius must be at most half the smallest dimension');
    }
    if (c.kind === 'chamfered_box' && typeof p.chamfer === 'number') {
      var minDim2 = Math.min(p.length || 0, p.width || 0);
      if (p.chamfer * 2 > minDim2) errors.push(where + '.params.chamfer must be at most half the smallest side');
    }
  }

  function massKg(volumeMm3, densityKgM3) {
    if (volumeMm3 == null || densityKgM3 == null) return null;
    return volumeMm3 / 1e9 * densityKgM3; // mm^3 -> m^3
  }

  var api = {
    UNITS: UNITS, PRIMITIVE_KINDS: PRIMITIVE_KINDS, COMPONENT_KINDS: COMPONENT_KINDS,
    BOOLEAN_OPS: BOOLEAN_OPS, toMM: toMM, fromMM: fromMM, convert: convert,
    polygonArea: polygonArea, polygonCentroidX: polygonCentroidX,
    analyticVolume: analyticVolume, validateModel: validateModel, massKg: massKg
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  root.AIELAB_MODEL_MATH = api;
})(typeof window !== 'undefined' ? window : globalThis);
