/* AI Engineering Laboratory — My Projects client (Stage 2).
   All project data comes from the backend, scoped to the signed-in
   user. This page never shows another user's projects — the API
   only returns the caller's own, and direct access to another
   user's project returns 404. */
(function () {
  'use strict';
  var current = null; // project currently open in the editor

  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function el(id) { return document.getElementById(id); }

  async function loadProjects() {
    var list = el('projects-list'), empty = el('projects-empty'), err = el('projects-error');
    if (!list) return;
    list.innerHTML = '<p class="muted">Loading your projects…</p>';
    if (empty) empty.style.display = 'none';
    if (err) err.style.display = 'none';
    var q = (el('search-projects') || {}).value || '';
    var lab = (el('filter-lab-projects') || {}).value || '';
    var params = new URLSearchParams();
    if (q.trim()) params.set('q', q.trim());
    if (lab) params.set('lab', lab);
    try {
      var r = await window.AIELAB_AUTH.api('GET', '/api/v1/projects?' + params.toString());
      var projects = r.projects || [];
      var recent = projects.slice(0, 5);
      var recEl = el('recent-list');
      if (recEl) recEl.innerHTML = recent.length ? recent.map(function (p) { return '<div class="card" style="padding:10px 12px"><b>' + esc(p.name) + '</b> <span class="pill">' + esc(p.lab) + '</span><div class="small muted">Updated ' + esc(p.updated_at || '') + '</div></div>'; }).join('') : '<p class="muted">No projects yet.</p>';
      if (!projects.length) {
        list.innerHTML = '';
        if (empty) empty.style.display = 'block';
        return;
      }
      list.innerHTML = projects.map(function (p) {
        return '<div class="card" style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap"><div><b>' + esc(p.name) + '</b> <span class="pill">' + esc(p.lab) + '</span> <span class="pill">' + (p.visibility === 'public' ? '🌐 PUBLIC' : '🔒 PRIVATE') + '</span><div class="small muted">' + esc(p.description || '') + '</div><div class="small muted">Updated ' + esc(p.updated_at || '') + '</div></div>' +
          '<div class="btn-row" style="margin:0"><button class="secondary" data-open="' + p.id + '">Open</button>' + (p.visibility === 'public' ? '<button class="secondary" data-vis="' + p.id + '" data-to="private">Make private</button>' : '<button class="secondary" data-vis="' + p.id + '" data-to="public">Publish</button>') + '<button class="secondary" data-duplicate="' + p.id + '">Duplicate</button><button class="danger" data-delete="' + p.id + '" data-name="' + esc(p.name) + '">Delete</button></div></div></div>';
      }).join('');
      list.querySelectorAll('[data-open]').forEach(function (b) { b.addEventListener('click', function () { openProject(b.getAttribute('data-open')); }); });
      list.querySelectorAll('[data-duplicate]').forEach(function (b) { b.addEventListener('click', async function () { await window.AIELAB_AUTH.api('POST', '/api/v1/projects/' + b.getAttribute('data-duplicate') + '/duplicate'); loadProjects(); }); });
      list.querySelectorAll('[data-vis]').forEach(function (b) { b.addEventListener('click', async function () {
        var to = b.getAttribute('data-to');
        if (to === 'public' && !confirm('Publish this project? Anyone will be able to view its name, description, category, your username and its published design data.')) return;
        await window.AIELAB_AUTH.api('POST', '/api/v1/projects/' + b.getAttribute('data-vis') + '/' + (to === 'public' ? 'publish' : 'unpublish'));
        loadProjects();
      }); });
      list.querySelectorAll('[data-delete]').forEach(function (b) { b.addEventListener('click', async function () {
        if (!confirm('Delete "' + b.getAttribute('data-name') + '"? This cannot be undone.')) return;
        await window.AIELAB_AUTH.api('DELETE', '/api/v1/projects/' + b.getAttribute('data-delete'));
        if (current && current.id === b.getAttribute('data-delete')) { current = null; el('project-editor').style.display = 'none'; }
        loadProjects();
      }); });
    } catch (e) {
      list.innerHTML = '';
      if (err) { err.style.display = 'block'; err.textContent = e.message; }
    }
  }

  // -- Stage 4: materials selected for the open project ---------------
  var matNames = {};
  async function loadMaterialNames() {
    try {
      var r = await window.AIELAB_AUTH.api('GET', '/api/v1/materials');
      (r.materials || []).forEach(function (m) { matNames[m.id] = m.name; });
    } catch (e) {
      try {
        var d = await (await fetch('data/materials.json')).json();
        (d.materials || []).forEach(function (m) { matNames[m.id] = m.name; });
      } catch (e2) { /* names stay as ids */ }
    }
    var sel = el('editor-material-select');
    if (sel) sel.innerHTML = Object.keys(matNames).sort().map(function (id) {
      return '<option value="' + id + '">' + esc(matNames[id]) + '</option>';
    }).join('');
  }
  function renderEditorMaterials() {
    var box = el('editor-materials-list'); if (!box || !current) return;
    var ids = (current.payload && current.payload.materials) || [];
    if (!ids.length) { box.innerHTML = '<span class="muted">No materials selected yet.</span>'; return; }
    box.innerHTML = ids.map(function (id) {
      return '<span class="pill" style="margin:2px 4px 2px 0">' + esc(matNames[id] || id) +
        ' <a href="#" data-remove-mat="' + id + '" title="Remove">✕</a></span>';
    }).join('') + ' <span class="small muted">(<a href="materials.html">browse the library</a>)</span>';
    box.querySelectorAll('[data-remove-mat]').forEach(function (a) {
      a.addEventListener('click', async function (ev) {
        ev.preventDefault();
        try {
          var r = await window.AIELAB_AUTH.api('DELETE', '/api/v1/projects/' + current.id + '/materials/' + a.getAttribute('data-remove-mat'));
          current = r.project;
          el('edit-payload').value = JSON.stringify(current.payload || {}, null, 2);
          renderEditorMaterials();
        } catch (e) { alert('Could not remove material: ' + e.message); }
      });
    });
  }

  async function openProject(id) {
    try {
      var r = await window.AIELAB_AUTH.api('GET', '/api/v1/projects/' + id);
      current = r.project;
      el('editor-title').textContent = 'Editing: ' + current.name;
      el('edit-name').value = current.name;
      el('edit-desc').value = current.description || '';
      el('edit-lab').value = current.lab;
      el('edit-visibility').value = current.visibility || 'private';
      el('visibility-status').textContent = (current.visibility === 'public' ? '🌐 PUBLIC — visible in the Public Gallery' : '🔒 PRIVATE — only you can see it');
      el('edit-payload').value = JSON.stringify(current.payload || {}, null, 2);
      await loadMaterialNames();
      renderEditorMaterials();
      el('project-editor').style.display = 'block';
      el('project-editor').scrollIntoView({ behavior: 'smooth' });
    } catch (e) { alert('Could not open project: ' + e.message); }
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (!el('projects-list')) return;
    if (!window.AIELAB_AUTH.requireAuth()) return;
    loadProjects();
    ['search-projects', 'filter-lab-projects'].forEach(function (id) {
      var e = el(id); if (e) e.addEventListener('input', loadProjects);
    });
    var create = el('create-project-form');
    if (create) create.addEventListener('submit', async function (e) {
      e.preventDefault();
      var err = el('create-error'); window.AIELAB_AUTH.clearError(err);
      try {
        await window.AIELAB_AUTH.api('POST', '/api/v1/projects', { name: el('new-name').value.trim(), description: el('new-desc').value.trim(), lab: el('new-lab').value });
        create.reset(); loadProjects();
      } catch (ex) { window.AIELAB_AUTH.showError(err, ex); }
    });
    var save = el('save-project');
    if (save) save.addEventListener('click', async function () {
      if (!current) return;
      var payload;
      try { payload = JSON.parse(el('edit-payload').value || '{}'); }
      catch (e) { alert('Design data is not valid JSON: ' + e.message); return; }
      try {
        var r = await window.AIELAB_AUTH.api('PATCH', '/api/v1/projects/' + current.id,
          { name: el('edit-name').value.trim(), description: el('edit-desc').value.trim(), lab: el('edit-lab').value, visibility: el('edit-visibility').value, payload: payload });
        current = r.project;
        el('editor-title').textContent = 'Editing: ' + current.name;
        el('save-status').textContent = 'Saved at ' + new Date().toLocaleTimeString() + ' — progress persists on the server.';
        loadProjects();
      } catch (e) { alert('Could not save: ' + e.message); }
    });
    var close = el('close-editor');
    if (close) close.addEventListener('click', function () { current = null; el('project-editor').style.display = 'none'; });
    var addMat = el('editor-material-add');
    if (addMat) addMat.addEventListener('click', async function () {
      if (!current) return;
      var mid = (el('editor-material-select') || {}).value;
      if (!mid) return;
      try {
        var r = await window.AIELAB_AUTH.api('POST', '/api/v1/projects/' + current.id + '/materials', { material_id: mid });
        current = r.project;
        el('edit-payload').value = JSON.stringify(current.payload || {}, null, 2);
        renderEditorMaterials();
      } catch (e) { alert('Could not add material: ' + e.message); }
    });
  });
})();
