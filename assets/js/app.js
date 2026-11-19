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

  // --- Hosted backend (Stage 11 deployment): the site talks to the
  // Render backend when the user is signed in. Requests use the same
  // wake-aware fetch as the labs, so a sleeping free-tier server
  // wakes up instead of failing the first call.
  var API_BASE = (window.AIELAB_API_BASE || 'http://127.0.0.1:8001');
  function apiToken() { try { return localStorage.getItem('aielab.token') || ''; } catch (e) { return ''; } }
  async function apiJSON(path, opts) {
    var doFetch = window.aielabFetchWithWake || fetch;
    var res = await doFetch(API_BASE + path, Object.assign({
      headers: { 'Content-Type': 'application/json', 'Authorization': apiToken() ? 'Bearer ' + apiToken() : '' }
    }, opts || {}));
    var data = {};
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) throw new Error(data.error || ('HTTP ' + res.status));
    return data;
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
      if (counts) {
        counts.innerHTML =
          stat(labs.labs.length, 'Laboratories') + stat(mats.materials.length, 'Materials in database') +
          stat(comps.components.length, 'Components in library') + stat('…', apiToken() ? 'Your projects (on the server)' : 'Your projects (this browser)');
        refreshProjectCount();
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
  // Fill in the project count once the server answers (or fall back
  // to the local list). Kept separate so a sleeping backend never
  // holds up the rest of the dashboard.
  async function refreshProjectCount() {
    var counts = document.getElementById('counts');
    if (!counts || counts.children.length < 4) return;
    var num = counts.children[3].querySelector('.stat-num');
    var lab = counts.children[3].querySelector('.stat-label');
    if (!num) return;
    if (!apiToken()) {
      num.textContent = loadProjects().length;
      if (lab) lab.textContent = 'Your projects (this browser)';
      return;
    }
    try {
      var data = await apiJSON('/api/v1/projects');
      num.textContent = (data.projects || []).length;
      if (lab) lab.textContent = 'Your projects (on the server)';
    } catch (e) {
      num.textContent = loadProjects().length;
      if (lab) lab.textContent = 'Your projects (this browser — server unreachable)';
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
  // --- Projects: the signed-in user's server projects, or the local
  // (guest) list. Opening a server project remembers it as the
  // last-used project, so the lab re-opens it (see aielab.last_project).
  var LAB_PAGES = { mechanical: 'mechanical.html', electrical: 'electrical.html', structural: 'structural.html', aerospace: 'aerospace.html', robotics: 'robotics.html', materials: 'materials.html', general: 'projects.html' };
  function renderServerProjects(list) {
    var listEl = document.getElementById('project-list');
    if (!listEl) return;
    var sub = document.getElementById('projects-sub');
    if (sub) sub.textContent = '— saved on the server under your account';
    if (!list.length) {
      listEl.innerHTML = '<p class="muted">No projects yet on the server. Create one below — it will be saved to your account.</p>';
      return;
    }
    listEl.innerHTML = list.map(function (p) {
      var page = LAB_PAGES[p.lab] || 'projects.html';
      var href = page + '?project=' + encodeURIComponent(p.id);
      return '<div class="card" style="margin-bottom:10px"><b>' + esc(p.name) + '</b> <span class="pill">' + esc(p.lab) + '</span> <span class="small muted">' + esc(p.updated_at || p.created_at || '') + '</span><p class="small">' + esc(p.description || '') + '</p><div class="btn-row"><a href="' + href + '" data-open-project="' + p.id + '"><button class="secondary">Open in lab</button></a></div></div>';
    }).join('');
    listEl.querySelectorAll('[data-open-project]').forEach(function (a) {
      a.addEventListener('click', function () {
        try { localStorage.setItem('aielab.last_project', a.getAttribute('data-open-project')); } catch (e) { /* ignore */ }
      });
    });
  }
  async function renderProjects() {
    var listEl = document.getElementById('project-list');
    if (!listEl) return;
    var serverNote = '';
    if (apiToken()) {
      listEl.innerHTML = '<p class="muted">Loading your projects from the server…</p>';
      try {
        var data = await apiJSON('/api/v1/projects');
        renderServerProjects(data.projects || []);
        return;
      } catch (e) {
        serverNote = '<p class="muted">Could not reach the server (' + esc(e.message) + ') — showing the projects stored in this browser instead.</p>';
      }
    }
    var sub = document.getElementById('projects-sub');
    if (sub) sub.textContent = '— stored in this browser only (sign in to save them on the server)';
    var list = loadProjects();
    if (!list.length) {
      listEl.innerHTML = serverNote + '<p class="muted">No projects yet. Create one below — it is stored in this browser only.</p>';
      return;
    }
    listEl.innerHTML = serverNote + list.map(function (p) {
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
      if (apiToken()) {
        // Signed in: create on the server, where every lab reads it.
        apiJSON('/api/v1/projects', { method: 'POST', body: JSON.stringify({ name: name, description: desc, lab: lab }) })
          .then(function () { form.reset(); renderProjects(); renderDashboard(); })
          .catch(function (err) { showError('Could not create the project on the server: ' + err.message); });
        return;
      }
      var list = loadProjects();
      list.unshift({ id: 'p' + Date.now().toString(36), name: name, lab: lab, description: desc, created_at: new Date().toISOString().slice(0, 10) });
      if (saveProjects(list)) { form.reset(); renderProjects(); renderDashboard(); }
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    systemStatus(); renderDashboard(); renderProjects();
  });
})();
