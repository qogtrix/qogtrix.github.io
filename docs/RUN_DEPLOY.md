# Run & Deploy — Stage 1

## Run locally (no install needed)

The site is pure static HTML/CSS/JS. Any static server works.
Do **not** just double-click `index.html` for the 3D pages — the
JSON data files are loaded with `fetch()`, which browsers block
from `file://` URLs.

```bash
cd ai-engineering-lab
python3 -m http.server 8000
# open http://localhost:8000/
```

Or with Node (already installed, v24):

```bash
npx --yes serve .
# open the URL it prints
```

Then open: Dashboard `/`, Workspace `/workspace.html`,
a lab e.g. `/labs/mechanical.html`.

## Deploy — GitHub Pages (current live host)

The live site is the `qogtrix/qogtrix.github.io` repository.

1. Copy the contents of `ai-engineering-lab/` to the root of that
   repo (replace the old placeholder `index.html`).
2. Commit and push to the repo's default branch.
3. GitHub Pages rebuilds automatically (usually < 1 minute).
4. Verify: `https://qogtrix.github.io/` returns 200 and shows the
   dashboard; check one lab page and `workspace.html`.

`.nojekyll` is included so GitHub Pages serves files/folders
starting with `_` correctly (none in Stage 1, but it prevents
surprises later).

## Custom domain — after PR merge (pending)

`qogtrix.is-a.dev` is **not live yet** (PR #61755 open, 19 Nov 2026).

After the maintainer merges it:

1. In the `qogtrix.github.io` repo: Settings → Pages →
   Custom domain → enter `qogtrix.is-a.dev` → Save.
2. Tick Enforce HTTPS once the certificate is issued.
3. Wait for DNS propagation, then verify
   `https://qogtrix.is-a.dev/` loads the same dashboard.
4. Do not add a `CNAME` file by hand before this step — Pages
   creates/manages it from the setting above.

## Backend (Stage 2 preparation only — do not deploy yet)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --reload --port 8001
# GET http://localhost:8001/health  →  {"status":"ok",...}
# Any /api/v1/simulate/* route     →  501 Not Implemented (by design)
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Materials table says "could not load data" | You opened the file via `file://`, or the JSON path is wrong. Serve over HTTP (above) and retry. |
| 3D canvas shows "Three.js could not be loaded" | No internet / CDN blocked. Check connection, retry. The rest of the site still works. |
| 3D canvas shows "WebGL is not available" | Browser/device has WebGL disabled. Try another browser. |
| Page looks unstyled | `assets/css/style.css` path wrong after copying — keep the folder structure exactly as in this repo. |
| GitHub Pages still shows the old placeholder | Pages rebuild takes ~1 min; hard-refresh (Ctrl+Shift+R). Check the repo actually received the push. |
