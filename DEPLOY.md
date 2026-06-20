# Deploying Luxlane

Luxlane has two parts:

- **Static front-end** — the HTML/CSS/JS pages (customer site, driver app, tracking).
- **Python backend** (`server.py`) — payments, pricing, the bookings pool, the
  driver/ride endpoints, and live tracking. The front-end calls it at `/api/...`.

> ⚠️ **GoDaddy "Web Hosting" (cPanel / shared) cannot run the Python backend.**
> Shared hosting only serves static files + PHP; it can't keep a persistent
> Python server running. Without the backend, payments, the driver app, and
> tracking stop working. So the backend must live on a Python-capable host.

`server.py` already serves the static files too, so the simplest setup is to host
**the whole app in one place** and point your GoDaddy domain at it.

---

## ✅ Recommended: deploy the whole app to Render (free), use your GoDaddy domain

### 1. Put the project on GitHub
Create a repo and push the `blacklane-clone` folder to it. (Render deploys from GitHub.)

### 2. Create the web service on Render
1. Sign up at https://render.com (free).
2. **New → Web Service → Build and deploy from a Git repository** → pick your repo.
3. Render auto-detects Python. Confirm:
   - **Start command:** `python3 server.py`
   - **Build command:** (leave blank)
   - **Instance type:** Free
4. Add environment variables (Render → your service → Environment):
   - `STRIPE_SECRET_KEY` = `sk_live_...` (or `sk_test_...` to keep testing)
   - `MAPBOX_ACCESS_TOKEN` = `pk....`
   - `STRIPE_WEBHOOK_SECRET` = `whsec_...` (after you create the webhook)
   - `LUXLANE_CURRENCY` = `usd`
5. Deploy. You'll get a URL like `https://luxlane.onrender.com`. Open it — the full
   site, driver app (`/driver.html`), and tracking all work, with no code changes.

   (Or use the included `render.yaml` "Blueprint" for a one-click setup.)

### 3. Point your GoDaddy domain at Render
1. In Render → your service → **Settings → Custom Domains**, add e.g.
   `www.yourdomain.com` (and `yourdomain.com`). Render shows you the DNS target.
2. In **GoDaddy → My Products → Domain → DNS → Manage DNS**:
   - Add a **CNAME**: `www` → the target Render gives you.
   - For the root domain, follow Render's instructions (an `A`/`ALIAS` record, or
     forward the root to `www`).
3. Wait for DNS to propagate (minutes to a few hours). Render issues free HTTPS
   automatically.

Done — your app is live on your own domain. GoDaddy remains your domain registrar.

---

## Alternative: static on GoDaddy + backend on Render (split)

Only do this if you specifically want to use your GoDaddy hosting for the pages.
It needs small code changes I can make for you:
1. A configurable API base URL on the front-end (so it calls the Render backend).
2. CORS headers on the server (to allow your GoDaddy domain).
3. Stripe success/cancel URLs pointed back at your GoDaddy domain.

Then: upload the HTML/CSS/JS to GoDaddy `public_html` via **cPanel → File Manager**
(or FTP), and deploy `server.py` to Render as above. Tell me if you want this and
I'll wire it up.

---

## Other Python-friendly hosts
The same files work on **Railway**, **Fly.io**, **PythonAnywhere**, or any VPS
(including a GoDaddy VPS). They all read the `PORT` env var, which `server.py`
already supports.

---

## Add a Postgres database (so bookings survive restarts)

The server uses Postgres automatically when a `DATABASE_URL` env var is present,
and falls back to the JSON file otherwise. To enable durable storage on Render:

1. **Render → New → PostgreSQL** (free tier). Wait for it to be created.
2. Copy its **Internal Database URL** (looks like `postgres://...`).
3. **Render → your web service → Environment** → add:
   - `DATABASE_URL` = the URL you copied
4. (Optional) set `LUXLANE_SEED_DEMO=0` so the 3 demo rides aren't created in prod.
5. Redeploy. The startup log will show `store: Postgres`, and the `bookings` table
   is created automatically. Bookings now persist across deploys and restarts.

`requirements.txt` already includes `psycopg2-binary`, which Render installs during
the build. No other setup is needed. (Railway and most hosts also inject `DATABASE_URL`
when you attach a Postgres add-on — same behavior.)

## Email notifications (optional)

Welcome and booking-confirmation emails are sent via SMTP when configured, and
logged to the console otherwise (so the flow works without a mail server). To turn
on real email, set these env vars:

- `SMTP_HOST`, `SMTP_PORT` (default 587), `SMTP_USER`, `SMTP_PASS`
- `EMAIL_FROM` (e.g. `Luxlane <no-reply@yourdomain.com>`)

Works with any SMTP provider (SendGrid, Mailgun, Amazon SES, Gmail app password).

## Accounts & authentication

Customer and driver accounts are real: passwords are hashed with PBKDF2-SHA256
(never stored in plaintext), and sessions use signed tokens. Accounts persist via
the same storage backend (Postgres in production, JSON file locally). No setup
needed — it's on by default.

## ⚠️ Production checklist before taking real payments
- **Database:** ✅ supported — set `DATABASE_URL` (see above). Without it, the free
  tier's disk is **ephemeral** and the JSON store resets on each deploy/restart.
- **Authentication:** ✅ real accounts with hashed passwords + sessions.
- **Switch Stripe to live keys** and set up the webhook (`STRIPE_SETUP.md`).
- **Free tier sleeps.** Render's free service spins down after inactivity and
  cold-starts on the next visit (a few seconds). Upgrade to a paid instance to keep
  it always-on.
- **Swap mock auth** (customer sign-in + driver login) for real authentication.
- HTTPS is handled automatically by Render/Railway.
