/* AI Engineering Laboratory — API configuration.
   Local dev: run `cd backend && python3 app.py` and the site talks to
   http://127.0.0.1:8001. Production: the site is served from
   qogtrix.github.io and talks to the Render backend below.
   Either can be overridden per-browser in Account Settings (saved in
   this browser as aielab.api_base). */
var PROD_API_BASE = 'https://aielab-backend.onrender.com';
window.AIELAB_API_BASE = localStorage.getItem('aielab.api_base')
  || (window.location.hostname === 'qogtrix.github.io'
      ? PROD_API_BASE
      : 'http://127.0.0.1:8001');

/* Free-tier backends sleep after ~15 minutes idle. The first request
   after a nap fails while the server wakes (~30-60 s). Retry a failed
   request a few times with a pause instead of failing outright.
   onRetry(attempt, waitMs) lets the caller show a "waking up" status.
   Only network failures and 502/503/504 are retried — a 4xx is a real
   answer, not a sleeping server. */
window.aielabFetchWithWake = async function (url, options, onRetry) {
  var waits = [10000, 20000, 30000];
  for (var attempt = 0; attempt <= waits.length; attempt++) {
    try {
      var res = await fetch(url, options);
      if ((res.status === 502 || res.status === 503 || res.status === 504)
          && attempt < waits.length) {
        if (onRetry) onRetry(attempt + 1, waits[attempt]);
        await new Promise(function (r) { setTimeout(r, waits[attempt]); });
        continue;
      }
      return res;
    } catch (e) {
      if (attempt < waits.length) {
        if (onRetry) onRetry(attempt + 1, waits[attempt]);
        await new Promise(function (r) { setTimeout(r, waits[attempt]); });
        continue;
      }
      throw e;
    }
  }
};
