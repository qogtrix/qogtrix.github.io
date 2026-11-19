/* AI Engineering Laboratory — shared app logic (Stage 1).
   Real functionality only: navigation, system status checks,
   projects in localStorage, lab cards from data/labs.json.
   No simulated results anywhere. */
(function () {
  'use strict';
  var PROJECTS_KEY = 'aielab.projects.v1';

  function showError(msg) {
    var b = document.getElementById('error-banner');
    if (!b) return;
    b.style.display = 'block';
    b.textContent = 'Something went wrong: ' + msg + ' — the rest of the page should still work. Try reloading.';
  }
  window.addEventListener('error', function (e) { showError(e.message || 'Unknown error'); });

  function basePath() {
    // Pages live at / and /labs/ ; workspace at /workspace.html
    return location.pathname.indexOf('/labs/') !== -1 ? '../' : '';
  }
  window.AIELAB_BASE = basePath();

  async function fetchJSON(rel) {
    var res = await fetch(basePath() + rel);
    if (!res.ok) throw new Error('HTTP ' + res.status + ' for ' + rel);
    return res.json();
  }

  // --- Navigation: hamburger + active link ---
  var burger = document.getElementById('hamburger');
  var sidebar = document.getElementById('sidebar');
  if (burger && sidebar) {
    burger.addEventListener('click', function () { sidebar.classList.toggle('open'); });
    sidebar.querySelectorAll('a').forEach(function (a) {
      a.addEventListener('click', function () { sidebar.classList.remove('open'); });
    });
  }
  // Mark active nav link by current path
  document.querySelectorAll('.nav-link').forEach(function (a) {
    var href = a.getAttribute('href') || '';
    var path = location.pathname.replace(/\/$/, '') || '/';
    var target = href.replace(/^\.\.\//, '/').replace(/^\.\//, '/');
    if (target && (path === target || path.endsWith(target))) a.classList.add('active');
  });

  // --- System status (real runtime checks) ---
  async function systemStatus() {
    var el = document.getElementById('system-status');
    if (!el) return;
    var rows = [];
    var webgl = false;
    try {
      var c = document.createElement('canvas');
      webgl = !!(c.getContext('webgl') || c.getContext('experimental-webgl'));
    } catch (e) { webgl = false; }
    rows.push(['WebGL available', webgl, webgl ? '3D workspace can render' : '3D workspace will show a fallback message']);
    // Three.js is only loaded on pages with a 3D viewer; on the dashboard
    // its absence is expected, not a failure — so only check it there.
    if (document.getElementById('viewer')) {
      var three = typeof window.THREE !== 'undefined';
      rows.push(['Three.js loaded', three, three ? 'Revision ' + (window.THREE.REVISION || '?') : 'CDN failed — 3D workspace shows a fallback message']);
    }
    var ls = false;
    try { localStorage.setItem('__aielab_test', '1'); localStorage.removeItem('__aielab_test'); ls = true; } catch (e) { ls = false; }
    rows.push(['Browser storage (projects)', ls, ls ? 'Projects save in this browser' : 'Projects cannot be saved in this browser']);
    try {
      var labs = await fetchJSON('data/labs.json');
      rows.push(['Lab data file', true, labs.labs.length + ' laboratories loaded']);
      var mats = await fetchJSON('data/materials.json');
      rows.push(['Materials data file', true, mats.materials.length + ' materials loaded']);
      var comps = await fetchJSON('data/components.json');
      rows.push(['Components data file', true, comps.components.length + ' components loaded']);
    } catch (e) {
      rows.push(['Data files', false, 'Could not load data/*.json — ' + e.message + '. Serve over HTTP, not file://']);
    }
    el.innerHTML = rows.map(function (r) {
      return '<div class="card" style="padding:12px 14px"><div style="display:flex;justify-content:space-between;gap:10px"><b>' + r[0] + '</b><span class="' + (r[1] ? 'status-ok' : 'status-bad') + '">' + (r[1] ? '● OK' : '● FAIL') + '</span></div><div class="small muted">' + r[2] + '</div></div>';
    }).join('');
  }

  // --- Dashboard counts + lab cards (computed from data, not hardcoded) ---
  async function renderDashboard() {
    var counts = document.getElementById('counts');
    var grid = document.getElementById('lab-grid');
    if (!counts && !grid) return;
    try {
      var labs = await fetchJSON('data/labs.json');
      var mats = await fetchJSON('data/materials.json');
      var comps = await fetchJSON('data/components.json');
      var projects = loadProjects();
      if (counts) {
        counts.innerHTML =
          stat(labs.labs.length, 'Laboratories') + stat(mats.materials.length, 'Materials in database') +
          stat(comps.components.length, 'Components in library') + stat(projects.length, 'Your projects (this browser)');
      }
      if (grid) {
        grid.innerHTML = labs.labs.map(function (lab) {
          return '<article class="card lab-card"><div class="icon">' + lab.icon + '</div><h3>' + lab.name + '</h3><p>' + lab.tagline + '</p><p class="small muted">' + lab.scope + '</p><div class="go"><a href="labs/' + lab.id + '.html">Open laboratory →</a></div></article>';
        }).join('');
      }
    } catch (e) {
      if (counts) counts.innerHTML = '<div class="notice err">Could not load dashboard data: ' + e.message + '. Serve the site over HTTP (see docs/RUN_DEPLOY.md) and reload.</div>';
      if (grid) grid.innerHTML = '';
    }
  }
  function stat(n, label) {
    return '<div class="card"><div class="stat-num">' + n + '</div><div class="stat-label">' + label + '</div></div>';
  }

  // --- Projects (localStorage, real) ---
  function loadProjects() {
    try { return JSON.parse(localStorage.getItem(PROJECTS_KEY) || '[]'); } catch (e) { return []; }
  }
  function saveProjects(list) {
    try { localStorage.setItem(PROJECTS_KEY, JSON.stringify(list)); return true; }
    catch (e) { showError('Could not save project: ' + e.message); return false; }
  }
  function renderProjects() {
    var listEl = document.getElementById('project-list');
    if (!listEl) return;
    var list = loadProjects();
    if (!list.length) {
      listEl.innerHTML = '<p class="muted">No projects yet. Create one below — it is stored in this browser only.</p>';
      return;
    }
    listEl.innerHTML = list.map(function (p) {
      return '<div class="card" style="margin-bottom:10px"><b>' + esc(p.name) + '</b> <span class="pill">' + esc(p.lab) + '</span> <span class="small muted">' + esc(p.created_at || '') + '</span><p class="small">' + esc(p.description || '') + '</p><div class="btn-row"><button class="secondary" data-export="' + p.id + '">Export JSON</button><button class="danger" data-delete="' + p.id + '">Delete</button></div></div>';
    }).join('');
    listEl.querySelectorAll('[data-delete]').forEach(function (b) {
      b.addEventListener('click', function () {
        if (!confirm('Delete this project?')) return;
        saveProjects(loadProjects().filter(function (p) { return p.id !== b.getAttribute('data-delete'); }));
        renderProjects(); renderDashboard();
      });
    });
    listEl.querySelectorAll('[data-export]').forEach(function (b) {
      b.addEventListener('click', function () {
        var p = loadProjects().find(function (x) { return x.id === b.getAttribute('data-export'); });
        if (!p) return;
        var blob = new Blob([JSON.stringify(p, null, 2)], { type: 'application/json' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = 'aielab-project-' + p.id + '.json';
        a.click(); URL.revokeObjectURL(a.href);
      });
    });
  }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }

  var form = document.getElementById('project-form');
  if (form) {
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var name = document.getElementById('project-name').value.trim();
      var lab = document.getElementById('project-lab').value;
      var desc = document.getElementById('project-desc').value.trim();
      if (!name) { alert('Give the project a name.'); return; }
      var list = loadProjects();
      list.unshift({ id: 'p' + Date.now().toString(36), name: name, lab: lab, description: desc, created_at: new Date().toISOString().slice(0, 10) });
      if (saveProjects(list)) { form.reset(); renderProjects(); renderDashboard(); }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    systemStatus(); renderDashboard(); renderProjects();
  });
})();
