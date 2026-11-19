# Run the lab online with Cloudflare Tunnel (from your own PC)

No credit card, ₹0, no code changes. The backend runs on your PC;
Cloudflare Tunnel gives it a public address, and the site at
https://qogtrix.github.io talks to it. Your data lives in Turso,
so it survives the PC being off.

**The one trade-off:** the lab is only up while your PC is on and
awake. If the PC sleeps or is off, the site can't reach the backend.

## What you need

- Python 3.12 (from python.org — tick **Add to PATH** during install)
- Git
- cloudflared (Cloudflare's tunnel program)
- Your Turso account (already have it — `aielab` database exists)

## Step 1 — Get the code

```bash
git clone https://github.com/qogtrix/qogtrix.github.io.git aielab
cd aielab
```

(On Windows, use Git Bash or PowerShell for these commands.)

## Step 2 — Install the one dependency

```bash
pip install -r backend/requirements.txt
```

This installs `libsql`, the only extra package — it lets the backend
sync with Turso. Without it the backend still runs, but only on a
local file and your data won't be in Turso.

Check Python first if this fails: `python --version` should say 3.12.

## Step 3 — Create a Turso token (do this once)

The token made during setup was shown once and never stored, so make
a fresh one — it takes 30 seconds:

1. Open https://app.turso.tech/qogtrix/databases/aielab and sign in.
2. Click **Create Token**, copy the token it shows.
3. Save it as an environment variable (so it never sits in a file):

   **Windows (PowerShell, once):**
   ```powershell
   setx TURSO_DATABASE_URL "libsql://aielab-qogtrix.aws-us-west-2.turso.io"
   setx TURSO_AUTH_TOKEN "paste-your-token-here"
   ```
   Close and reopen the terminal after `setx`.

   **Mac / Linux (once, add to `~/.zshrc` or `~/.bashrc`):**
   ```bash
   export TURSO_DATABASE_URL="libsql://aielab-qogtrix.aws-us-west-2.turso.io"
   export TURSO_AUTH_TOKEN="paste-your-token-here"
   ```

Never paste the token in chat or commit it to the repo.

## Step 4 — Start the backend

**Windows:** double-click `start-backend.bat` (it checks the token is
set, then runs the backend).

**Mac / Linux:**
```bash
cd backend && python3 app.py
```

You should see a line saying the server is listening. Leave this
window open.

## Step 5 — Check it works

Open http://127.0.0.1:8001/health in your browser. You should see
something like `{"status": "ok", "stage": 11, ...}`.

## Step 6 — Start the tunnel

Install cloudflared if you haven't:

- **Windows:** `winget install Cloudflare.cloudflared`
- **Mac:** `brew install cloudflared`
- **Linux:** download the `.deb`/`.rpm` from Cloudflare's releases

Then, in a **new** terminal window (keep the backend running):

```bash
cloudflared tunnel --url http://localhost:8001
```

It prints a public address like `https://random-words.trycloudflare.com`.
**Copy that address** — that is your backend's public URL. Leave this
window open too.

## Step 7 — Point the site at the tunnel

1. Open https://qogtrix.github.io and go to **Settings**.
2. Find the **API base** field, paste your tunnel address, save.
   (The page reloads. This setting lives in your browser only.)
3. Go to **Sign up** and create your account.

Or send the tunnel address to Muse and it will wire it in and test
everything live for you.

## Step 8 — Close registration (after your account exists)

Registration is open by default so you can sign up. Once your account
works, close it so nobody else can register:

```powershell
setx AIELAB_REGISTRATION "closed"
```

Then stop the backend (Ctrl+C) and start it again. Your account keeps
working; new sign-ups get refused.

## Daily use

1. Start the backend (Step 4).
2. Start the tunnel (Step 6) — the address changes every time you
   restart it, so update the API base in Settings each time, or send
   the new address to Muse.
3. Keep the PC awake while you use the lab (Settings → Power → never
   sleep, or just know the lab goes down when it sleeps).
4. Stop with Ctrl+C in both windows when done.

## Later — a stable address (named tunnel)

The quick tunnel above changes address on every restart. For a
permanent address (e.g. `lab.qogtrix.com`), set up a **named tunnel**:

1. Make a free Cloudflare account (email only, no card).
2. Move `qogtrix.com` DNS to Cloudflare (free; nameservers change at
   your domain registrar — the site itself doesn't move).
3. `cloudflared tunnel login`, `cloudflared tunnel create aielab`,
   then route `lab.qogtrix.com` to `http://localhost:8001`.
4. Tell Muse the address — it will update the site's config and
   re-push so everyone uses the stable address.

## Troubleshooting

| Problem | Fix |
|---|---|
| `python` not recognised | Reinstall Python 3.12 and tick **Add to PATH** |
| `pip install` fails for libsql | Use Python 3.12 64-bit; try `pip install --upgrade pip` first |
| Backend says "port already in use" | Another backend is running — close the old window, or set `AIELAB_PORT=8002` and tunnel to that port instead |
| `health` shows an error / won't load | Backend isn't running — check the backend window for an error |
| Tunnel says "connection refused" | Start the backend first (Step 4), then the tunnel |
| Site says "Cannot reach the backend" | PC asleep/off, tunnel window closed, or the API base in Settings is an old tunnel address — start both and paste the current address |
| `start-backend.bat` says the token isn't set | Do Step 3 again, then open a **new** terminal (setx only applies to new windows) |
