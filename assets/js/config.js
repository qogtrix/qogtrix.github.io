/* AI Engineering Laboratory — API configuration (Stage 2).
   The static site (GitHub Pages) cannot run the backend itself.
   Set the backend URL here, or in Account Settings (saved in this
   browser). Default is a local backend: run `cd backend && python3 app.py`.
   The hosted fullstack version of Stage 2 uses its own built-in API
   and does not need this setting. */
window.AIELAB_API_BASE = localStorage.getItem('aielab.api_base') || 'http://127.0.0.1:8001';
