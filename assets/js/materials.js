/* Materials + components tables — real client-side search / filter / sort
   over data/materials.json (v2 format, Stage 4) and data/components.json.
   v2 stores properties nested under `properties` with null = not
   available. This file maps them back to the flat fields the lab
   table uses, and exposes window.AIELAB_MATERIALS for the library,
   detail and project pages. */
(function () {
  'use strict';
  var materials = [], components = [], sortKey = 'name', sortDir = 1;

  function base() { return location.pathname.indexOf('/labs/') !== -1 ? '../' : ''; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmt(v, digits) { return v == null ? '—' : Number(v).toFixed(digits == null ? 1 : digits); }

  // Map a v2 material (nested properties) to the flat shape the
  // Stage 1 table expects. Unknown properties stay null — never 0.
  function flat(m) {
    var p = m.properties || {};
    return {
      id: m.id, name: m.name, grade: m.grade || '', category: m.category,
      categoryLabel: m.categoryLabel || m.category,
      density: p.density_kg_m3, youngs_modulus: p.elastic_modulus_gpa,
      yield_strength: p.yield_strength_mpa, tensile_strength: p.tensile_strength_mpa,
      poisson: p.poisson_ratio, thermal_conductivity: p.thermal_conductivity_w_mk,
      melting_point: p.melting_point_c, notes: m.notes || '',
      confidence: m.confidence || 'typical', standard: m.standard || '—',
      source: m.source || '', cost_index: m.cost_index,
      corrosion_resistance: m.corrosion_resistance,
      strength_to_weight: (p.tensile_strength_mpa != null && p.density_kg_m3)
        ? Math.round(p.tensile_strength_mpa * 1000 / p.density_kg_m3 * 10) / 10 : null,
      properties: p, raw: m
    };
  }

  var categories = [];
  async function loadData() {
    var mData = await (await fetch(base() + 'data/materials.json')).json();
    var cData = null;
    try { cData = await (await fetch(base() + 'data/material_categories.json')).json(); } catch (e) { cData = null; }
    var catNames = {};
    if (cData && cData.categories) {
      categories = cData.categories;
      cData.categories.forEach(function (c) { catNames[c.id] = c.name; });
    }
    materials = (mData.materials || []).map(function (m) {
      var f = flat(m);
      f.categoryLabel = catNames[m.category] || m.category;
      return f;
    });
    window.AIELAB_MATERIALS = {
      list: materials, categories: categories,
      byId: function (id) { return materials.find(function (m) { return m.id === id; }); },
      notice: mData.notice || ''
    };
    return mData;
  }

  async function load() {
    var matEl = document.getElementById('materials-table');
    var compEl = document.getElementById('components-table');
    if (!matEl && !compEl) return;
    try {
      var mData = await loadData();
      var cData = await (await fetch(base() + 'data/components.json')).json();
      components = cData.components || [];
      var notice = document.getElementById('materials-notice');
      if (notice) notice.textContent = mData.notice || '';
      buildCategoryFilter(); renderMaterials(); renderComponents();
    } catch (e) {
      var err = document.getElementById('materials-error');
      if (err) { err.style.display = 'block'; err.textContent = 'Could not load data files: ' + e.message + '. Serve the site over HTTP (see docs/RUN_DEPLOY.md), then use the Retry button.'; }
    }
  }
  function buildCategoryFilter() {
    var sel = document.getElementById('filter-category'); if (!sel) return;
    var cats = Array.from(new Set(materials.map(function (x) { return x.category; }))).sort();
    sel.innerHTML = '<option value="">All categories</option>' + cats.map(function (c) {
      var label = (categories.find(function (cc) { return cc.id === c; }) || {}).name || c;
      return '<option value="' + esc(c) + '">' + esc(label) + '</option>';
    }).join('');
  }
  function renderMaterials() {
    var tbody = document.querySelector('#materials-table tbody'); if (!tbody) return;
    var q = (document.getElementById('search-materials') || {}).value || '';
    q = q.trim().toLowerCase();
    var cat = (document.getElementById('filter-category') || {}).value || '';
    var rows = materials.filter(function (x) {
      return (!q || (x.name + ' ' + x.grade).toLowerCase().includes(q)) && (!cat || x.category === cat);
    });
    rows.sort(function (a, b) {
      var av = a[sortKey], bv = b[sortKey];
      if (av == null) return 1; if (bv == null) return -1;
      return (typeof av === 'string' ? av.localeCompare(bv) : av - bv) * sortDir;
    });
    tbody.innerHTML = rows.map(function (x) {
      return '<tr data-id="' + x.id + '"><td><a href="' + base() + 'material.html?id=' + x.id + '">' + esc(x.name) + '</a></td><td>' + esc(x.categoryLabel) + '</td><td class="num">' + (x.density == null ? '—' : x.density.toLocaleString()) + '</td><td class="num">' + fmt(x.youngs_modulus) + '</td><td class="num">' + fmt(x.yield_strength, 0) + '</td><td class="num">' + fmt(x.tensile_strength, 0) + '</td></tr>';
    }).join('') || '<tr><td colspan="6">No materials match that search.</td></tr>';
    var count = document.getElementById('materials-count'); if (count) count.textContent = rows.length + ' of ' + materials.length + ' materials';
    tbody.querySelectorAll('tr[data-id]').forEach(function (tr) {
      tr.addEventListener('click', function (ev) {
        if (ev.target.tagName === 'A') return;
        showDetail(tr.getAttribute('data-id'));
      });
    });
  }
  function showDetail(id) {
    var x = materials.find(function (m) { return m.id === id; }); if (!x) return;
    var el = document.getElementById('material-detail'); if (!el) return;
    el.style.display = 'block';
    el.innerHTML = '<h3>' + esc(x.name) + '</h3><dl class="kv">' +
      '<dt>Category</dt><dd>' + esc(x.categoryLabel) + '</dd>' +
      '<dt>Grade / standard</dt><dd>' + esc(x.grade) + ' — ' + esc(x.standard) + '</dd>' +
      '<dt>Density</dt><dd>' + (x.density == null ? '—' : x.density.toLocaleString() + ' kg/m³') + '</dd>' +
      '<dt>Young’s modulus</dt><dd>' + fmt(x.youngs_modulus) + ' GPa</dd>' +
      '<dt>Yield strength</dt><dd>' + fmt(x.yield_strength, 0) + ' MPa</dd>' +
      '<dt>Tensile strength</dt><dd>' + fmt(x.tensile_strength, 0) + ' MPa</dd>' +
      '<dt>Poisson ratio</dt><dd>' + fmt(x.poisson, 2) + '</dd>' +
      '<dt>Thermal conductivity</dt><dd>' + fmt(x.thermal_conductivity) + ' W/m·K</dd>' +
      '<dt>Melting point</dt><dd>' + (x.melting_point == null ? '— (not available)' : x.melting_point + ' °C') + '</dd>' +
      '<dt>Notes</dt><dd>' + esc(x.notes) + '</dd></dl>' +
      '<p><a href="' + base() + 'material.html?id=' + x.id + '">Open full material page →</a></p>' +
      '<p class="small muted">Typical published value — verify against the manufacturer’s datasheet before design use.</p>';
    el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
  function renderComponents() {
    var tbody = document.querySelector('#components-table tbody'); if (!tbody) return;
    var lab = (document.getElementById('filter-lab') || {}).value || '';
    var rows = components.filter(function (x) { return !lab || x.lab === lab; });
    tbody.innerHTML = rows.map(function (x) {
      return '<tr><td>' + esc(x.name) + '</td><td>' + esc(x.category) + '</td><td>' + esc(x.lab) + '</td><td>' + esc(x.standard) + '</td><td>' + esc(x.material) + '</td><td>' + esc(x.dimensions) + '</td></tr>';
    }).join('') || '<tr><td colspan="6">No components for that laboratory yet.</td></tr>';
    var count = document.getElementById('components-count'); if (count) count.textContent = rows.length + ' of ' + components.length + ' components';
  }
  document.addEventListener('DOMContentLoaded', function () {
    load();
    ['search-materials', 'filter-category'].forEach(function (id) {
      var el = document.getElementById(id); if (el) el.addEventListener('input', renderMaterials);
    });
    var fl = document.getElementById('filter-lab'); if (fl) fl.addEventListener('change', renderComponents);
    document.querySelectorAll('#materials-table th[data-sort]').forEach(function (th) {
      th.addEventListener('click', function () {
        var k = th.getAttribute('data-sort');
        if (sortKey === k) sortDir = -sortDir; else { sortKey = k; sortDir = 1; }
        renderMaterials();
      });
    });
    var retry = document.getElementById('retry-data');
    if (retry) retry.addEventListener('click', function () { location.reload(); });
  });
})();
