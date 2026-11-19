/* Material Library — Stage 4.
   Loads data/materials.json + data/material_categories.json (static,
   so it works on GitHub Pages with no backend). When the local
   backend is reachable, favorites sync to the server and the
   recommend/compare calls go to the API; otherwise everything is
   computed in the browser from the same data, with the same
   formulas the backend uses (see docs/MATERIALS.md). Missing
   values are always null — shown as "—", never as 0. */
(function () {
  'use strict';
  var materials = [], categories = [], catNames = {};
  var favorites = new Set(), compare = new Set();
  var filters = { q: '', category: '', minTensile: '', maxDensity: '', minMelting: '', maxCost: '', sort: 'name', favOnly: false };
  var notice = '';

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmt(v, d) { return v == null ? '—' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 1 : d }); }
  function el(id) { return document.getElementById(id); }
  function api() { return window.AIELAB_AUTH && window.AIELAB_AUTH.api; }
  function signedIn() { return !!(window.AIELAB_AUTH && window.AIELAB_AUTH.user && window.AIELAB_AUTH.user()); }
  function flat(m) {
    var p = m.properties || {};
    var stw = (p.tensile_strength_mpa != null && p.density_kg_m3) ? Math.round(p.tensile_strength_mpa * 1000 / p.density_kg_m3 * 10) / 10 : null;
    var ss = (p.elastic_modulus_gpa != null && p.density_kg_m3) ? Math.round(p.elastic_modulus_gpa * 1000 / p.density_kg_m3 * 10) / 10 : null;
    return { id: m.id, name: m.name, grade: m.grade || '', category: m.category,
      categoryLabel: catNames[m.category] || m.category, confidence: m.confidence || 'typical',
      standard: m.standard || '—', source: m.source || '', cost_index: m.cost_index,
      corrosion_resistance: m.corrosion_resistance, properties: p,
      strength_to_weight: stw, specific_stiffness: ss, notes: m.notes || '' };
  }
  function dots(n, max) {
    var s = '';
    for (var i = 1; i <= (max || 5); i++) s += i <= (n || 0) ? '●' : '○';
    return s;
  }

  async function load() {
    var errEl = el('lib-error'), loadEl = el('lib-loading');
    try {
      var mData = await (await fetch('data/materials.json')).json();
      var cData = await (await fetch('data/material_categories.json')).json();
      categories = cData.categories || [];
      categories.forEach(function (c) { catNames[c.id] = c.name; });
      materials = (mData.materials || []).map(flat);
      notice = mData.notice || '';
      var nEl = el('lib-notice'); if (nEl) nEl.textContent = notice;
      loadFavorites();
      buildChips(); render();
      if (loadEl) loadEl.style.display = 'none';
    } catch (e) {
      if (loadEl) loadEl.style.display = 'none';
      if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Could not load the material database: ' + e.message + '. Serve the site over HTTP (see docs/RUN_DEPLOY.md).'; }
    }
  }

  // -- favorites: server when signed in, this device otherwise --------
  function loadFavorites() {
    try { (JSON.parse(localStorage.getItem('aielab.favorites') || '[]')).forEach(function (id) { favorites.add(id); }); } catch (e) {}
    if (signedIn() && api()) {
      api()('GET', '/api/v1/materials/favorites').then(function (res) {
        var ids = (res.favorites || []).map(function (f) { return f.id; });
        favorites = new Set(ids);
        saveLocalFavorites(); render();
      }).catch(function () { /* offline — local favorites stand */ });
    }
  }
  function saveLocalFavorites() {
    try { localStorage.setItem('aielab.favorites', JSON.stringify(Array.from(favorites))); } catch (e) {}
  }
  function toggleFavorite(id) {
    var adding = !favorites.has(id);
    if (adding) favorites.add(id); else favorites.delete(id);
    saveLocalFavorites(); render();
    if (signedIn() && api()) {
      var p = adding ? api()('POST', '/api/v1/materials/favorites', { material_id: id })
                     : api()('DELETE', '/api/v1/materials/favorites/' + id);
      p.catch(function () { /* server sync failed — local copy kept */ });
    }
  }

  // -- filtering / sorting ----------------------------------------------
  function filtered() {
    var q = filters.q.trim().toLowerCase();
    var rows = materials.filter(function (m) {
      var p = m.properties;
      if (filters.favOnly && !favorites.has(m.id)) return false;
      if (filters.category && m.category !== filters.category) return false;
      if (q && (m.name + ' ' + m.grade + ' ' + m.categoryLabel).toLowerCase().indexOf(q) === -1) return false;
      if (filters.minTensile !== '' && (p.tensile_strength_mpa == null || p.tensile_strength_mpa < +filters.minTensile)) return false;
      if (filters.maxDensity !== '' && (p.density_kg_m3 == null || p.density_kg_m3 > +filters.maxDensity)) return false;
      if (filters.minMelting !== '' && (p.melting_point_c == null || p.melting_point_c < +filters.minMelting)) return false;
      if (filters.maxCost !== '' && (m.cost_index == null || m.cost_index > +filters.maxCost)) return false;
      return true;
    });
    var k = filters.sort;
    rows.sort(function (a, b) {
      if (k === 'strength_to_weight') return (b.strength_to_weight || -1) - (a.strength_to_weight || -1);
      if (k === 'density') return (a.properties.density_kg_m3 || 1e18) - (b.properties.density_kg_m3 || 1e18);
      if (k === 'tensile') return (b.properties.tensile_strength_mpa || -1) - (a.properties.tensile_strength_mpa || -1);
      if (k === 'cost') return (a.cost_index || 99) - (b.cost_index || 99);
      return a.name.localeCompare(b.name);
    });
    return rows;
  }

  function buildChips() {
    var wrap = el('category-chips'); if (!wrap) return;
    var counts = {};
    materials.forEach(function (m) { counts[m.category] = (counts[m.category] || 0) + 1; });
    var html = '<button class="chip' + (filters.category === '' ? ' active' : '') + '" data-cat="">All · ' + materials.length + '</button>';
    categories.forEach(function (c) {
      html += '<button class="chip' + (filters.category === c.id ? ' active' : '') + '" data-cat="' + c.id + '">' + esc(c.icon + ' ' + c.name) + ' · ' + (counts[c.id] || 0) + '</button>';
    });
    wrap.innerHTML = html;
    wrap.querySelectorAll('.chip').forEach(function (b) {
      b.addEventListener('click', function () { filters.category = b.getAttribute('data-cat'); buildChips(); render(); });
    });
  }

  function cardHTML(m) {
    var p = m.properties;
    var fav = favorites.has(m.id), inCmp = compare.has(m.id);
    return '<article class="card mat-card">' +
      '<div class="mat-head"><h3><a href="material.html?id=' + m.id + '">' + esc(m.name) + '</a></h3>' +
      '<button class="fav-btn' + (fav ? ' on' : '') + '" data-fav="' + m.id + '" title="' + (fav ? 'Remove from favorites' : 'Add to favorites') + '">' + (fav ? '★' : '☆') + '</button></div>' +
      '<p class="small muted">' + esc(m.grade) + ' · ' + esc(m.categoryLabel) + '</p>' +
      '<p><span class="pill">' + esc(m.confidence) + ' data</span> <span class="pill">Cost ' + dots(m.cost_index) + '</span></p>' +
      '<div class="grid cols-2 mat-stats">' +
      '<div><div class="stat-num">' + fmt(p.density_kg_m3, 0) + '</div><div class="stat-label">Density kg/m³</div></div>' +
      '<div><div class="stat-num">' + fmt(p.tensile_strength_mpa, 0) + '</div><div class="stat-label">Tensile MPa</div></div>' +
      '<div><div class="stat-num">' + fmt(p.elastic_modulus_gpa) + '</div><div class="stat-label">Stiffness GPa</div></div>' +
      '<div><div class="stat-num">' + fmt(m.strength_to_weight) + '</div><div class="stat-label">Strength-to-weight</div></div></div>' +
      '<p class="small muted">Corrosion ' + dots(m.corrosion_resistance) + ' · ' + esc(m.standard) + '</p>' +
      '<div class="btn-row"><a href="material.html?id=' + m.id + '"><button class="secondary">View details</button></a>' +
      '<button class="secondary cmp-btn' + (inCmp ? ' on' : '') + '" data-cmp="' + m.id + '">' + (inCmp ? '✓ Comparing' : '＋ Compare') + '</button></div>' +
      '</article>';
  }

  function render() {
    var grid = el('materials-grid'); if (!grid) return;
    var rows = filtered();
    var count = el('lib-count'); if (count) count.textContent = rows.length + ' of ' + materials.length + ' materials' + (favorites.size ? ' · ' + favorites.size + ' favorite' + (favorites.size > 1 ? 's' : '') : '');
    var empty = el('lib-empty');
    if (!rows.length) {
      grid.innerHTML = '';
      if (empty) empty.style.display = 'block';
    } else {
      if (empty) empty.style.display = 'none';
      grid.innerHTML = rows.map(cardHTML).join('');
    }
    grid.querySelectorAll('[data-fav]').forEach(function (b) {
      b.addEventListener('click', function () { toggleFavorite(b.getAttribute('data-fav')); });
    });
    grid.querySelectorAll('[data-cmp]').forEach(function (b) {
      b.addEventListener('click', function () {
        var id = b.getAttribute('data-cmp');
        if (compare.has(id)) compare.delete(id);
        else if (compare.size < 4) compare.add(id);
        else { alert('Compare up to 4 materials at a time. Remove one first.'); return; }
        render(); renderTray();
      });
    });
    renderTray();
  }

  // -- comparison -------------------------------------------------------
  var CMP_ROWS = [
    { key: 'density_kg_m3', label: 'Density', unit: 'kg/m³', dir: 'min' },
    { key: 'tensile_strength_mpa', label: 'Tensile strength', unit: 'MPa', dir: 'max' },
    { key: 'compressive_strength_mpa', label: 'Compressive strength', unit: 'MPa', dir: 'max' },
    { key: 'yield_strength_mpa', label: 'Yield strength', unit: 'MPa', dir: 'max' },
    { key: 'elastic_modulus_gpa', label: 'Elastic modulus', unit: 'GPa', dir: 'max' },
    { key: 'shear_modulus_gpa', label: 'Shear modulus', unit: 'GPa', dir: 'max' },
    { key: 'thermal_conductivity_w_mk', label: 'Thermal conductivity', unit: 'W/m·K', dir: 'max' },
    { key: 'specific_heat_j_kgk', label: 'Specific heat', unit: 'J/kg·K', dir: 'max' },
    { key: 'thermal_expansion_um_mk', label: 'Thermal expansion', unit: 'µm/m·K', dir: 'min' },
    { key: 'melting_point_c', label: 'Melting point', unit: '°C', dir: 'max' },
    { key: 'electrical_resistivity_ohm_m', label: 'Electrical resistivity', unit: 'Ω·m', dir: 'min' },
    { key: 'electrical_conductivity_pct_iacs', label: 'Electrical conductivity', unit: '% IACS', dir: 'max' },
    { key: 'fatigue_limit_mpa', label: 'Fatigue limit', unit: 'MPa', dir: 'max' },
    { key: 'fracture_toughness_mpa_sqrt_m', label: 'Fracture toughness', unit: 'MPa√m', dir: 'max' },
    { key: '__stw', label: 'Strength-to-weight', unit: 'kN·m/kg', dir: 'max' },
    { key: '__ss', label: 'Specific stiffness', unit: '10⁶ m²/s²', dir: 'max' },
    { key: '__cost', label: 'Relative cost (1 cheap – 5 expensive)', unit: '1–5', dir: 'min' },
    { key: '__corr', label: 'Corrosion resistance', unit: '1–5', dir: 'max' }
  ];
  function cmpValue(m, key) {
    if (key === '__stw') return m.strength_to_weight;
    if (key === '__ss') return m.specific_stiffness;
    if (key === '__cost') return m.cost_index;
    if (key === '__corr') return m.corrosion_resistance;
    return m.properties[key];
  }
  function renderTray() {
    var tray = el('compare-tray'); if (!tray) return;
    if (!compare.size) { tray.style.display = 'none'; return; }
    tray.style.display = 'flex';
    var names = Array.from(compare).map(function (id) {
      var m = materials.find(function (x) { return x.id === id; });
      return m ? esc(m.name) : id;
    });
    tray.querySelector('.tray-text').innerHTML = '<strong>Compare (' + compare.size + '/4):</strong> ' + names.join(' · ');
    var btn = el('compare-go');
    btn.disabled = compare.size < 2;
    btn.textContent = compare.size < 2 ? 'Select at least 2' : 'Compare ' + compare.size + ' materials';
  }
  function renderComparison() {
    var sec = el('compare-section'); if (!sec) return;
    var mats = Array.from(compare).map(function (id) { return materials.find(function (x) { return x.id === id; }); }).filter(Boolean);
    if (mats.length < 2) { sec.style.display = 'none'; return; }
    var html = '<h2>Comparison</h2><p class="small muted">Best value in each row is highlighted. “—” means the value is not on record — it is not zero.</p><div class="table-wrap"><table><thead><tr><th>Property</th>' +
      mats.map(function (m) { return '<th><a href="material.html?id=' + m.id + '">' + esc(m.name) + '</a></th>'; }).join('') + '</tr></thead><tbody>';
    CMP_ROWS.forEach(function (row) {
      var vals = mats.map(function (m) { return cmpValue(m, row.key); });
      var present = vals.map(function (v, i) { return [i, v]; }).filter(function (t) { return t[1] != null; });
      var best = null;
      if (row.dir && present.length >= 2) best = (row.dir === 'max' ? Math.max : Math.min).apply(null, present.map(function (t) { return t[1]; }));
      html += '<tr><td>' + esc(row.label) + ' <span class="muted">(' + esc(row.unit) + ')</span></td>' +
        vals.map(function (v) {
          var cls = (v != null && best != null && v === best) ? ' class="best-cell"' : '';
          return '<td' + cls + '>' + (v == null ? '—' : fmt(v, row.key.indexOf('resistivity') !== -1 ? 2 : 1)) + '</td>';
        }).join('') + '</tr>';
    });
    html += '</tbody></table></div><p><button class="secondary" id="compare-clear">Clear comparison</button></p>';
    sec.innerHTML = html;
    sec.style.display = 'block';
    sec.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el('compare-clear').addEventListener('click', function () { compare.clear(); render(); sec.style.display = 'none'; });
  }

  // -- recommend (same transparent scoring as the backend) --------------
  function recommend() {
    var req = {
      minTensile: el('rec-min-tensile').value ? +el('rec-min-tensile').value : null,
      maxDensity: el('rec-max-density').value ? +el('rec-max-density').value : null,
      minMelting: el('rec-min-melting').value ? +el('rec-min-melting').value : null,
      maxCost: el('rec-max-cost').value ? +el('rec-max-cost').value : null,
      minCorrosion: el('rec-min-corrosion').value ? +el('rec-min-corrosion').value : null
    };
    var out = el('rec-results');
    var cands = materials.filter(function (m) {
      var p = m.properties;
      if (req.minTensile != null && (p.tensile_strength_mpa == null || p.tensile_strength_mpa < req.minTensile)) return false;
      if (req.maxDensity != null && (p.density_kg_m3 == null || p.density_kg_m3 > req.maxDensity)) return false;
      if (req.minMelting != null && (p.melting_point_c == null || p.melting_point_c < req.minMelting)) return false;
      if (req.maxCost != null && (m.cost_index == null || m.cost_index > req.maxCost)) return false;
      if (req.minCorrosion != null && (m.corrosion_resistance == null || m.corrosion_resistance < req.minCorrosion)) return false;
      return true;
    });
    if (!cands.length) {
      out.innerHTML = '<p class="notice">No material in the current library meets all requirements — relax a constraint and try again.</p>';
      return;
    }
    var maxStw = Math.max.apply(null, cands.map(function (m) { return m.strength_to_weight || 0; })) || 1;
    var maxSs = Math.max.apply(null, cands.map(function (m) { return m.specific_stiffness || 0; })) || 1;
    var ranked = cands.map(function (m) {
      var stw = (m.strength_to_weight || 0) / maxStw, ss = (m.specific_stiffness || 0) / maxSs;
      var cheap = 1 - ((m.cost_index || 3) - 1) / 4;
      var reasons = [], tradeoffs = [];
      if (m.strength_to_weight) reasons.push('Strength-to-weight ' + m.strength_to_weight + ' kN·m/kg');
      if (m.properties.tensile_strength_mpa) reasons.push('Tensile ' + m.properties.tensile_strength_mpa + ' MPa');
      if ((m.cost_index || 99) <= 2) reasons.push('Low relative cost');
      if ((m.cost_index || 0) >= 4) tradeoffs.push('Expensive (cost 4–5)');
      if ((m.corrosion_resistance || 5) <= 2) tradeoffs.push('Needs corrosion protection');
      return { m: m, score: Math.round((0.5 * stw + 0.3 * ss + 0.2 * cheap) * 1000) / 1000, reasons: reasons, tradeoffs: tradeoffs };
    }).sort(function (a, b) { return b.score - a.score; }).slice(0, 5);
    out.innerHTML = '<p class="small muted">Scoring: 50% strength-to-weight + 30% specific stiffness + 20% low cost, each normalized to the best candidate here. ' + (materials.length - cands.length) + ' of ' + materials.length + ' materials did not meet the requirements.</p>' +
      ranked.map(function (r, i) {
        return '<div class="card rec-card"><strong>#' + (i + 1) + ' <a href="material.html?id=' + r.m.id + '">' + esc(r.m.name) + '</a></strong> — score ' + r.score +
          '<br><span class="small">Why: ' + esc(r.reasons.join(' · ') || 'Meets your requirements') + '</span>' +
          (r.tradeoffs.length ? '<br><span class="small status-warn">Trade-offs: ' + esc(r.tradeoffs.join(' · ')) + '</span>' : '') + '</div>';
      }).join('');
  }

  document.addEventListener('DOMContentLoaded', function () {
    load();
    var s = el('lib-search'); if (s) s.addEventListener('input', function () { filters.q = s.value; render(); });
    [['lib-min-tensile', 'minTensile'], ['lib-max-density', 'maxDensity'], ['lib-min-melting', 'minMelting'], ['lib-max-cost', 'maxCost']].forEach(function (pair) {
      var inp = el(pair[0]); if (inp) inp.addEventListener('input', function () { filters[pair[1]] = inp.value; render(); });
    });
    var sort = el('lib-sort'); if (sort) sort.addEventListener('change', function () { filters.sort = sort.value; render(); });
    var fav = el('lib-fav-only'); if (fav) fav.addEventListener('change', function () { filters.favOnly = fav.checked; render(); });
    var go = el('compare-go'); if (go) go.addEventListener('click', renderComparison);
    var clear = el('compare-clear-tray'); if (clear) clear.addEventListener('click', function () { compare.clear(); render(); });
    var rec = el('rec-run'); if (rec) rec.addEventListener('click', recommend);
  });
})();
