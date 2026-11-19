/* Materials + components tables — real client-side search / filter / sort
   over data/materials.json and data/components.json. */
(function () {
  'use strict';
  var materials = [], components = [], sortKey = 'name', sortDir = 1;

  function base() { return location.pathname.indexOf('/labs/') !== -1 ? '../' : ''; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmt(v, digits) { return v == null ? '—' : Number(v).toFixed(digits == null ? 1 : digits); }

  async function load() {
    var matEl = document.getElementById('materials-table');
    var compEl = document.getElementById('components-table');
    if (!matEl && !compEl) return;
    try {
      var mData = await (await fetch(base() + 'data/materials.json')).json();
      materials = mData.materials || [];
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
    sel.innerHTML = '<option value="">All categories</option>' + cats.map(function (c) { return '<option>' + esc(c) + '</option>'; }).join('');
  }
  function renderMaterials() {
    var tbody = document.querySelector('#materials-table tbody'); if (!tbody) return;
    var q = (document.getElementById('search-materials') || {}).value || '';
    q = q.trim().toLowerCase();
    var cat = (document.getElementById('filter-category') || {}).value || '';
    var rows = materials.filter(function (x) {
      return (!q || x.name.toLowerCase().includes(q)) && (!cat || x.category === cat);
    });
    rows.sort(function (a, b) {
      var av = a[sortKey], bv = b[sortKey];
      if (av == null) return 1; if (bv == null) return -1;
      return (typeof av === 'string' ? av.localeCompare(bv) : av - bv) * sortDir;
    });
    tbody.innerHTML = rows.map(function (x) {
      return '<tr data-id="' + x.id + '"><td>' + esc(x.name) + '</td><td>' + esc(x.category) + '</td><td class="num">' + x.density.toLocaleString() + '</td><td class="num">' + fmt(x.youngs_modulus) + '</td><td class="num">' + fmt(x.yield_strength, 0) + '</td><td class="num">' + fmt(x.tensile_strength, 0) + '</td></tr>';
    }).join('') || '<tr><td colspan="6">No materials match that search.</td></tr>';
    var count = document.getElementById('materials-count'); if (count) count.textContent = rows.length + ' of ' + materials.length + ' materials';
    tbody.querySelectorAll('tr[data-id]').forEach(function (tr) {
      tr.addEventListener('click', function () { showDetail(tr.getAttribute('data-id')); });
    });
  }
  function showDetail(id) {
    var x = materials.find(function (m) { return m.id === id; }); if (!x) return;
    var el = document.getElementById('material-detail'); if (!el) return;
    el.style.display = 'block';
    el.innerHTML = '<h3>' + esc(x.name) + '</h3><dl class="kv">' +
      '<dt>Category</dt><dd>' + esc(x.category) + '</dd>' +
      '<dt>Density</dt><dd>' + x.density.toLocaleString() + ' kg/m³</dd>' +
      '<dt>Young’s modulus</dt><dd>' + fmt(x.youngs_modulus) + ' GPa</dd>' +
      '<dt>Yield strength</dt><dd>' + fmt(x.yield_strength, 0) + ' MPa</dd>' +
      '<dt>Tensile strength</dt><dd>' + fmt(x.tensile_strength, 0) + ' MPa</dd>' +
      '<dt>Poisson ratio</dt><dd>' + fmt(x.poisson, 2) + '</dd>' +
      '<dt>Thermal conductivity</dt><dd>' + fmt(x.thermal_conductivity) + ' W/m·K</dd>' +
      '<dt>Melting point</dt><dd>' + (x.melting_point == null ? '— (composite / no single melting point)' : x.melting_point + ' °C') + '</dd>' +
      '<dt>Notes</dt><dd>' + esc(x.notes) + '</dd></dl>' +
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
