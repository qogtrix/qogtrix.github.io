/* Public gallery (Stage 3). No sign-in required.
   Uses only the public API — the server returns public projects
   only, so private projects cannot leak through this page. */
(function () {
  'use strict';
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  async function load() {
    var list = document.getElementById('gallery-list'); if (!list) return;
    var err = document.getElementById('gallery-error'), empty = document.getElementById('gallery-empty');
    list.innerHTML = '<p class="muted">Loading published projects…</p>';
    if (empty) empty.style.display = 'none'; if (err) err.style.display = 'none';
    var q = (document.getElementById('gallery-search') || {}).value || '';
    var lab = (document.getElementById('gallery-lab') || {}).value || '';
    var params = new URLSearchParams();
    if (q.trim()) params.set('q', q.trim());
    if (lab) params.set('lab', lab);
    try {
      var res = await fetch(window.AIELAB_API_BASE + '/api/v1/public/projects?' + params.toString());
      if (!res.ok) throw new Error('Gallery request failed (HTTP ' + res.status + ')');
      var data = await res.json();
      var projects = data.projects || [];
      if (!projects.length) { list.innerHTML = ''; if (empty) empty.style.display = 'block'; return; }
      list.innerHTML = projects.map(function (p) {
        return '<article class="card lab-card"><h3>' + esc(p.name) + '</h3>' +
          '<p>' + esc(p.description || 'No description.') + '</p>' +
          '<p class="small muted">By <b>@' + esc(p.owner_username || 'unknown') + '</b> · ' + esc(p.lab) + ' · Published ' + esc((p.updated_at || '').slice(0, 10)) + '</p>' +
          '<div class="go"><a href="#" data-view="' + p.id + '">View project →</a></div></article>';
      }).join('');
      list.querySelectorAll('[data-view]').forEach(function (a) {
        a.addEventListener('click', function (e) { e.preventDefault(); viewProject(a.getAttribute('data-view')); });
      });
    } catch (e) {
      list.innerHTML = '';
      if (err) { err.style.display = 'block'; err.textContent = 'Could not load the gallery: ' + e.message + ' — the hosted backend may be waking up; wait a minute and reload.'; }
    }
  }
  async function viewProject(id) {
    var d = document.getElementById('gallery-detail'); if (!d) return;
    try {
      var res = await fetch(window.AIELAB_API_BASE + '/api/v1/public/projects/' + id);
      if (!res.ok) throw new Error('HTTP ' + res.status);
      var p = (await res.json()).project;
      d.style.display = 'block';
      d.innerHTML = '<h3>' + esc(p.name) + ' <span class="pill">PUBLIC · read-only</span></h3>' +
        '<dl class="kv"><dt>Owner</dt><dd>@' + esc(p.owner_username || 'unknown') + '</dd>' +
        '<dt>Category</dt><dd>' + esc(p.lab) + '</dd>' +
        '<dt>Description</dt><dd>' + esc(p.description || '—') + '</dd>' +
        '<dt>Published</dt><dd>' + esc((p.updated_at || '').slice(0, 10)) + '</dd></dl>' +
        '<h3>Published design data</h3><pre>' + esc(JSON.stringify(p.payload || {}, null, 2)) + '</pre>' +
        '<p class="small muted">This is a read-only view. You cannot edit or delete another user\'s project.</p>';
      d.scrollIntoView({ behavior: 'smooth' });
    } catch (e) { d.style.display = 'block'; d.innerHTML = '<p>This project is not available (it may have been made private again).</p>'; }
  }
  document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('gallery-list')) return;
    load();
    ['gallery-search', 'gallery-lab'].forEach(function (id) {
      var e = document.getElementById(id); if (e) e.addEventListener('input', load);
    });
  });
})();
