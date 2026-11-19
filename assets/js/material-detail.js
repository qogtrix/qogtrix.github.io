/* Individual material page — Stage 4.
   Loads data/materials.json (static, works on GitHub Pages).
   Shows every property grouped, with missing values marked
   "Not available", plus data quality, derived metrics, favorites
   and "select for project" (needs sign-in + backend). */
(function () {
  'use strict';
  var materials = [], catNames = {}, current = null;
  var favorites = new Set();

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function fmt(v, d) { return v == null ? 'Not available' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d == null ? 1 : d }); }
  function el(id) { return document.getElementById(id); }
  function api() { return window.AIELAB_AUTH && window.AIELAB_AUTH.api; }
  function signedIn() { return !!(window.AIELAB_AUTH && window.AIELAB_AUTH.user && window.AIELAB_AUTH.user()); }
  function dots(n) { var s = ''; for (var i = 1; i <= 5; i++) s += i <= (n || 0) ? '●' : '○'; return s; }

  var GROUPS = {
    'props-mechanical': [
      ['density_kg_m3', 'Density', 'kg/m³'], ['tensile_strength_mpa', 'Tensile strength', 'MPa'],
      ['compressive_strength_mpa', 'Compressive strength', 'MPa'], ['yield_strength_mpa', 'Yield strength', 'MPa'],
      ['elastic_modulus_gpa', 'Elastic modulus', 'GPa'], ['poisson_ratio', "Poisson's ratio", '—'],
      ['shear_modulus_gpa', 'Shear modulus', 'GPa'], ['hardness', 'Hardness', ''],
      ['fatigue_limit_mpa', 'Fatigue limit', 'MPa'], ['fracture_toughness_mpa_sqrt_m', 'Fracture toughness', 'MPa√m']
    ],
    'props-thermal': [
      ['thermal_conductivity_w_mk', 'Thermal conductivity', 'W/m·K'],
      ['specific_heat_j_kgk', 'Specific heat capacity', 'J/kg·K'],
      ['thermal_expansion_um_mk', 'Thermal expansion coefficient', 'µm/m·K'],
      ['melting_point_c', 'Melting point', '°C']
    ],
    'props-electrical': [
      ['electrical_resistivity_ohm_m', 'Electrical resistivity', 'Ω·m'],
      ['electrical_conductivity_pct_iacs', 'Electrical conductivity', '% IACS']
    ]
  };

  function propRow(key, label, unit, p) {
    var v = p[key], text;
    if (key === 'hardness') {
      text = v == null ? 'Not available' : v.value + ' ' + v.scale;
    } else if (v == null) {
      text = 'Not available';
    } else if (key === 'electrical_resistivity_ohm_m') {
      text = Number(v).toExponential(2) + ' ' + unit;
    } else {
      text = fmt(v, key === 'poisson_ratio' ? 2 : 1) + (unit ? ' ' + unit : '');
    }
    return '<dt>' + esc(label) + '</dt><dd' + (v == null ? ' class="missing"' : '') + '>' + esc(text) + '</dd>';
  }

  function render(m) {
    var p = m.properties || {};
    document.title = m.name + ' — AI Engineering Laboratory';
    el('crumb-name').textContent = m.name;
    el('detail-name').textContent = m.name;
    el('detail-sub').textContent = (m.grade ? 'Grade ' + m.grade + ' · ' : '') + (catNames[m.category] || m.category);
    el('detail-category').textContent = catNames[m.category] || m.category;
    el('detail-confidence').textContent = (m.confidence || 'typical') + ' data';
    el('detail-standard').textContent = 'Standard: ' + (m.standard || '—');
    el('detail-notes').textContent = m.notes || '';
    var stw = (p.tensile_strength_mpa != null && p.density_kg_m3) ? Math.round(p.tensile_strength_mpa * 1000 / p.density_kg_m3 * 10) / 10 : null;
    var ss = (p.elastic_modulus_gpa != null && p.density_kg_m3) ? Math.round(p.elastic_modulus_gpa * 1000 / p.density_kg_m3 * 10) / 10 : null;
    el('detail-stats').innerHTML =
      '<div class="card"><div class="stat-num">' + fmt(p.density_kg_m3, 0) + '</div><div class="stat-label">Density kg/m³</div></div>' +
      '<div class="card"><div class="stat-num">' + fmt(p.tensile_strength_mpa, 0) + '</div><div class="stat-label">Tensile strength MPa</div></div>' +
      '<div class="card"><div class="stat-num">' + fmt(stw) + '</div><div class="stat-label">Strength-to-weight kN·m/kg</div></div>' +
      '<div class="card"><div class="stat-num">' + fmt(ss) + '</div><div class="stat-label">Specific stiffness 10⁶ m²/s²</div></div>';
    Object.keys(GROUPS).forEach(function (id) {
      el(id).innerHTML = GROUPS[id].map(function (row) { return propRow(row[0], row[1], row[2], p); }).join('');
    });
    // Durability extras in the electrical card.
    el('props-electrical').innerHTML +=
      '<dt>Corrosion resistance</dt><dd>' + dots(m.corrosion_resistance) + ' (' + (m.corrosion_resistance || '—') + '/5)</dd>' +
      '<dt>Relative cost</dt><dd>' + dots(m.cost_index) + ' (' + (m.cost_index || '—') + '/5, 1 = cheapest)</dd>';
    var temp = m.temperature_range_c;
    el('props-quality').innerHTML =
      '<dt>Source / reference</dt><dd>' + esc(m.source || '—') + '</dd>' +
      '<dt>Standard / specification</dt><dd>' + esc(m.standard || '—') + '</dd>' +
      '<dt>Test conditions</dt><dd>' + esc(m.test_conditions || '—') + '</dd>' +
      '<dt>Temperature range</dt><dd>' + (temp ? temp[0] + ' to ' + temp[1] + ' °C' : 'Not available') + '</dd>' +
      '<dt>Data confidence</dt><dd>' + esc(m.confidence || 'typical') + ' — ' + (m.confidence === 'estimated' ? 'values are estimates, verify before use' : m.confidence === 'verified' ? 'checked against published standards' : 'typical published values') + '</dd>' +
      '<dt>Cost note</dt><dd>' + esc(m.cost_note || '') + '</dd>' +
      '<dt>Corrosion note</dt><dd>' + esc(m.corrosion_note || '') + '</dd>';
    // Related materials: same category first, then highest strength-to-weight.
    var related = materials.filter(function (x) { return x.id !== m.id; })
      .sort(function (a, b) {
        var ac = a.category === m.category ? 0 : 1, bc = b.category === m.category ? 0 : 1;
        return ac - bc || (b.properties.tensile_strength_mpa || -1) - (a.properties.tensile_strength_mpa || -1);
      }).slice(0, 3);
    el('related-grid').innerHTML = related.map(function (x) {
      var xp = x.properties || {};
      return '<article class="card"><h3><a href="material.html?id=' + x.id + '">' + esc(x.name) + '</a></h3>' +
        '<p class="small muted">' + esc(x.grade || '') + ' · ' + esc(catNames[x.category] || x.category) + '</p>' +
        '<p class="small">Density ' + fmt(xp.density_kg_m3, 0) + ' kg/m³ · Tensile ' + fmt(xp.tensile_strength_mpa, 0) + ' MPa</p></article>';
    }).join('');
    updateFavBtn();
    setupSelect();
    el('detail-loading').style.display = 'none';
    el('detail').style.display = 'block';
  }

  function updateFavBtn() {
    var b = el('detail-fav');
    var on = favorites.has(current.id);
    b.textContent = on ? '★' : '☆';
    b.classList.toggle('on', on);
  }

  function setupSelect() {
    if (!signedIn()) { el('select-signin').style.display = 'block'; return; }
    var box = el('select-box'); box.style.display = 'block';
    api()('GET', '/api/v1/projects').then(function (res) {
      var sel = el('select-project');
      var projects = res.projects || [];
      if (!projects.length) {
        sel.innerHTML = '<option value="">No projects yet — create one in My Projects first</option>';
        el('select-add').disabled = true;
        return;
      }
      sel.innerHTML = projects.map(function (p) { return '<option value="' + p.id + '">' + esc(p.name) + '</option>'; }).join('');
    }).catch(function () {
      el('select-result').textContent = 'Could not reach the backend — the hosted server sleeps when idle; wait a minute and try again.';
    });
    el('select-add').addEventListener('click', function () {
      var pid = el('select-project').value;
      if (!pid) return;
      api()('POST', '/api/v1/projects/' + pid + '/materials', { material_id: current.id })
        .then(function () { el('select-result').textContent = '✓ Added ' + current.name + ' to that project.'; })
        .catch(function (e) { el('select-result').textContent = 'Could not add it: ' + (e.message || 'backend error'); });
    });
  }

  async function load() {
    var id = new URLSearchParams(location.search).get('id');
    try {
      var mData = await (await fetch('data/materials.json')).json();
      var cData = await (await fetch('data/material_categories.json')).json();
      (cData.categories || []).forEach(function (c) { catNames[c.id] = c.name; });
      materials = mData.materials || [];
      current = materials.find(function (m) { return m.id === id; });
      if (!current) throw new Error('Material not found: ' + id);
      try { (JSON.parse(localStorage.getItem('aielab.favorites') || '[]')).forEach(function (f) { favorites.add(f); }); } catch (e) {}
      if (signedIn() && api()) {
        api()('GET', '/api/v1/materials/favorites').then(function (res) {
          favorites = new Set((res.favorites || []).map(function (f) { return f.id; }));
          updateFavBtn();
        }).catch(function () {});
      }
      render(current);
    } catch (e) {
      el('detail-loading').style.display = 'none';
      var err = el('detail-error');
      err.style.display = 'block';
      err.textContent = e.message + '. Go back to the Material Library and pick a material there.';
    }
    el('detail-fav').addEventListener('click', function () {
      if (!current) return;
      if (favorites.has(current.id)) favorites.delete(current.id); else favorites.add(current.id);
      try { localStorage.setItem('aielab.favorites', JSON.stringify(Array.from(favorites))); } catch (e) {}
      updateFavBtn();
      if (signedIn() && api()) {
        var p = favorites.has(current.id)
          ? api()('POST', '/api/v1/materials/favorites', { material_id: current.id })
          : api()('DELETE', '/api/v1/materials/favorites/' + current.id);
        p.catch(function () {});
      }
    });
  }
  document.addEventListener('DOMContentLoaded', load);
})();
