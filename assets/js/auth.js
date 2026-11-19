/* AI Engineering Laboratory — auth client (Stage 2).
   Talks to the real backend (assets/js/config.js). Token is stored
   in localStorage; the server can revoke it at any time (logout).
   No password is ever stored in the browser. */
(function () {
  'use strict';
  function apiBase() { return window.AIELAB_API_BASE || 'http://127.0.0.1:8001'; }
  function token() { return localStorage.getItem('aielab.token') || ''; }
  function setToken(t) { if (t) localStorage.setItem('aielab.token', t); else localStorage.removeItem('aielab.token'); }
  function user() { try { return JSON.parse(localStorage.getItem('aielab.user') || 'null'); } catch (e) { return null; } }
  function setUser(u) { if (u) localStorage.setItem('aielab.user', JSON.stringify(u)); else localStorage.removeItem('aielab.user'); }

  async function api(method, path, body) {
    var res;
    try {
      res = await fetch(apiBase() + path, {
        method: method,
        headers: { 'Content-Type': 'application/json', 'Authorization': token() ? 'Bearer ' + token() : '' },
        body: body === undefined ? undefined : JSON.stringify(body)
      });
    } catch (e) {
      throw new Error('Cannot reach the backend at ' + apiBase() + '. Start it with: cd backend && python3 app.py — ' + e.message);
    }
    var data = {};
    try { data = await res.json(); } catch (e) { /* empty body */ }
    if (!res.ok) throw new Error(data.error || ('Request failed (HTTP ' + res.status + ')'));
    return data;
  }
  async function logout() {
    try { await api('POST', '/api/v1/auth/logout'); } catch (e) { /* token may already be dead */ }
    setToken(null); setUser(null);
    location.href = (location.pathname.indexOf('/labs/') !== -1 ? '../' : '') + 'auth.html';
  }
  function requireAuth() {
    if (!token()) { location.href = (location.pathname.indexOf('/labs/') !== -1 ? '../' : '') + 'auth.html'; return false; }
    return true;
  }
  function showError(el, err) { if (el) { el.style.display = 'block'; el.textContent = err.message || String(err); } }
  function clearError(el) { if (el) { el.style.display = 'none'; el.textContent = ''; } }

  window.AIELAB_AUTH = { api: api, apiBase: apiBase, token: token, setToken: setToken, user: user, setUser: setUser, logout: logout, requireAuth: requireAuth, showError: showError, clearError: clearError };

  document.addEventListener('DOMContentLoaded', function () {
    // Sidebar auth state
    var state = document.getElementById('auth-state');
    if (state) {
      var u = user();
      state.innerHTML = u
        ? 'Signed in as <b>' + u.name + '</b><br><span class="small">' + u.email + '</span> · <a href="#" id="logout-link">Sign out</a>'
        : 'Not signed in · <a href="auth.html">Sign in</a>';
      var lo = document.getElementById('logout-link');
      if (lo) lo.addEventListener('click', function (e) { e.preventDefault(); logout(); });
    }
    // Login form
    var login = document.getElementById('login-form');
    if (login) login.addEventListener('submit', async function (e) {
      e.preventDefault();
      var err = document.getElementById('login-error'); clearError(err);
      var btn = login.querySelector('button'); btn.disabled = true; btn.textContent = 'Signing in…';
      try {
        var r = await api('POST', '/api/v1/auth/login', { email: document.getElementById('login-email').value.trim(), password: document.getElementById('login-password').value });
        setToken(r.token); setUser(r.user);
        location.href = 'projects.html';
      } catch (ex) { showError(err, ex); btn.disabled = false; btn.textContent = 'Sign in'; }
    });
    // Register form
    var reg = document.getElementById('register-form');
    if (reg) reg.addEventListener('submit', async function (e) {
      e.preventDefault();
      var err = document.getElementById('register-error'); clearError(err);
      var btn = reg.querySelector('button'); btn.disabled = true; btn.textContent = 'Creating account…';
      try {
        var r = await api('POST', '/api/v1/auth/register', { name: document.getElementById('register-name').value.trim(), username: document.getElementById('register-username').value.trim(), email: document.getElementById('register-email').value.trim(), password: document.getElementById('register-password').value });
        setToken(r.token); setUser(r.user);
        location.href = 'projects.html';
      } catch (ex) { showError(err, ex); btn.disabled = false; btn.textContent = 'Create account'; }
    });
    // Global logout buttons
    document.querySelectorAll('[data-logout]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.preventDefault(); logout(); });
    });
  });
})();
