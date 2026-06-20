#!/usr/bin/env python3
"""
Luxlane booking server — static files + Stripe Checkout integration.

Runs on the Python standard library only (no pip install needed).

  • If STRIPE_SECRET_KEY is set in the environment, it talks to the REAL
    Stripe API to create Checkout Sessions.
  • If no key is set, it runs in MOCK mode: it simulates a Stripe-hosted
    checkout page so the whole booking → pay → confirm flow is testable
    locally without any credentials.

Endpoints:
  GET  /                              -> static files (index.html, etc.)
  POST /api/create-checkout-session   -> {url, id, ...quote}
  GET  /api/checkout-status?session_id=...  -> {payment_status}
  GET  /api/quote   (also POST)       -> authoritative server price
  GET  /api/mock-session?session_id=  -> mock checkout details (mock mode)
  POST /api/mock-pay                  -> mark mock session paid (mock mode)
  POST /api/webhook                   -> Stripe webhook receiver

Run:  python3 server.py [port]   (default port 4173)
"""

import json
import os
import re
import sys
import time
import hmac
import uuid
import hashlib
import secrets
import smtplib
import threading
import functools
import urllib.parse
import urllib.request
import urllib.error
from email.message import EmailMessage
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.abspath(__file__))
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
MAPBOX_ACCESS_TOKEN = os.environ.get("MAPBOX_ACCESS_TOKEN", "").strip()
CURRENCY = os.environ.get("LUXLANE_CURRENCY", "usd").strip().lower()
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SEED_DEMO = os.environ.get("LUXLANE_SEED_DEMO", "1") != "0"
MOCK = not STRIPE_SECRET_KEY

# Email (booking confirmations, welcome). Sends via SMTP when configured,
# otherwise logs the message so the flow is testable without a mail server.
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Luxlane <no-reply@luxlane.example>").strip()

# Pricing source of truth — must mirror assets/js/app.js FLEET base/perKm.
FLEET = {
    1: {"name": "Executive Sedan", "base": 65, "perKm": 2.2},
    2: {"name": "Luxury SUV", "base": 135, "perKm": 3.8},
    3: {"name": "Mercedes Sprinter Van", "base": 95, "perKm": 2.8},
    4: {"name": "Stretch Limousine", "base": 160, "perKm": 4.2},
}
SERVICE_LABELS = {
    "airport": "Airport Transfer", "hourly": "Hourly Hire",
    "intercity": "Intercity", "city": "City Transfer",
}

# In-memory stores (a real app would use a database).
MOCK_SESSIONS = {}    # sid -> session dict
PAID_BOOKINGS = {}    # ref -> booking metadata (populated by webhook / mock-pay)
_DISTANCE_CACHE = {}  # (origin, dest) -> (km, source) — avoids repeat geocoding

# Shared booking store — the operational pool that drivers see. Persisted to disk
# (a JSON file) so rides survive a restart. A real app would use a database.
DATA_DIR = os.path.join(ROOT, "data")
BOOKINGS_FILE = os.path.join(DATA_DIR, "bookings.json")
BOOKINGS = {}                       # ref -> booking dict (in-memory working set)
_BOOKINGS_LOCK = threading.Lock()   # ThreadingHTTPServer is multi-threaded
DRIVER_SHARE = 0.80                 # fraction of fare paid to the driver

# Storage backend: Postgres when DATABASE_URL is set (durable, survives restarts),
# otherwise a local JSON file (fine for local/demo). psycopg2 is imported lazily,
# so the JSON path needs no third-party packages.
_PG = None          # psycopg2 module (loaded only when a DB is configured)
_PG_JSON = None      # psycopg2.extras.Json adapter
_DB_ENABLED = False

# Accounts & sessions. USERS persist via the storage backend (Postgres/JSON);
# SESSIONS are kept in memory (cleared on restart -> users simply log in again).
USERS_FILE = os.path.join(DATA_DIR, "users.json")
USERS = {}                          # email(lowercased) -> user dict
SESSIONS = {}                       # token -> {email, role, exp}
_USERS_LOCK = threading.Lock()
SESSION_TTL_MS = 30 * 24 * 3600 * 1000  # 30 days

# Ride lifecycle: available -> assigned -> arrived -> on_trip -> completed
RIDE_STATUSES = ("arrived", "on_trip", "completed", "available")

# Live tracking. LOCATIONS holds the latest position pushed by a driver's device.
# When no fresh GPS is being streamed, the track endpoint synthesizes smooth
# progress from elapsed time so the demo moves once the driver starts the trip.
LOCATIONS = {}              # ref -> {lat, lon, progress, etaMin, leg, updatedAt}
LOCATION_FRESH_MS = 12000   # treat pushed GPS as live if newer than this
DEMO_APPROACH_MS = 45000    # demo: time for driver to reach the pick-up
DEMO_TRIP_MS = 90000        # demo: time for the pick-up -> destination leg


# ---------------------------------------------------------------- pricing
def estimate_distance(a, b):
    """Deterministic pseudo-distance (km). Mirrors estimateDistance() in app.js.
    Used only as a fallback when Mapbox is unavailable."""
    if not a or not b:
        return 0
    s = re.sub(r"\s+", "", (a + "|" + b).lower())
    h = 0
    for ch in s:
        h = (h * 31 + ord(ch)) & 0xFFFFFFFF
    return 8 + (h % 39)


def get_real_distance(origin_text, destination_text):
    """Geocode both addresses and return real driving distance in km via Mapbox.
    Returns None on any failure so the caller can fall back to the estimate."""
    try:
        coords = []
        for address in (origin_text, destination_text):
            q = urllib.parse.quote(address)
            url = ("https://api.mapbox.com/geocoding/v5/mapbox.places/%s.json"
                   "?access_token=%s&limit=1" % (q, MAPBOX_ACCESS_TOKEN))
            req = urllib.request.Request(url, headers={"User-Agent": "LuxlaneServer"})
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
            feats = data.get("features") or []
            if not feats:
                return None
            coords.append(feats[0]["center"])  # Mapbox returns [lon, lat]

        coord_str = "%s,%s;%s,%s" % (coords[0][0], coords[0][1], coords[1][0], coords[1][1])
        url = ("https://api.mapbox.com/directions-matrix/v1/mapbox/driving/%s"
               "?sources=0&destinations=1&annotations=distance&access_token=%s"
               % (coord_str, MAPBOX_ACCESS_TOKEN))
        req = urllib.request.Request(url, headers={"User-Agent": "LuxlaneServer"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            matrix = json.loads(resp.read().decode())
        meters = matrix["distances"][0][0]
        if meters is None:
            return None
        return meters / 1000.0
    except Exception as e:  # noqa: BLE001
        print("[mapbox] lookup failed (%s) — using estimate" % e, flush=True)
        return None


def road_distance(origin, destination, service="city"):
    """Return (distance_km, source). Uses Mapbox when a token is configured,
    otherwise the deterministic estimate. Cached per address pair."""
    if not origin or not destination:
        return 0.0, "none"
    key = (origin.strip().lower(), destination.strip().lower())
    if key in _DISTANCE_CACHE:
        return _DISTANCE_CACHE[key]

    km = get_real_distance(origin, destination) if MAPBOX_ACCESS_TOKEN else None
    if km is not None:
        out = (round(km, 1), "mapbox")
    else:
        est = estimate_distance(origin, destination)
        if service == "intercity" and est:
            est += 40  # estimate-only fudge; real routing already covers it
        out = (float(est), "estimate")
    _DISTANCE_CACHE[key] = out
    return out


def compute_quote(p):
    service = p.get("service", "airport")
    try:
        vid = int(p.get("vehicleId") or 1)
    except (TypeError, ValueError):
        vid = 1
    v = FLEET.get(vid, FLEET[1])

    distance_source = "none"
    if service == "hourly":
        try:
            hours = int(p.get("hours") or 2)
        except (TypeError, ValueError):
            hours = 2
        fare = v["base"] * hours
        distance = 0
    else:
        distance, distance_source = road_distance(
            p.get("pickup", ""), p.get("dropoff", ""), service)
        distance = round(distance, 1)
        fare = max(v["base"], v["base"] + distance * v["perKm"])
        hours = 0

    fare = round(fare, 2)
    tax = round(fare * 0.15, 2)
    total = round(fare + tax, 2)
    return {
        "service": service,
        "serviceLabel": SERVICE_LABELS.get(service, "Ride"),
        "vehicleId": vid,
        "vehicle": v["name"],
        "distance": distance,
        "distance_source": distance_source,
        "hours": hours,
        "fare": fare,
        "tax": tax,
        "total": total,
        "currency": CURRENCY,
        "amount_cents": int(round(total * 100)),
    }


# ---------------------------------------------------------------- booking store
def init_storage():
    """Pick the storage backend. Uses Postgres if DATABASE_URL is set and the
    driver is available; otherwise the JSON file. Never raises — always leaves a
    working backend."""
    global _PG, _PG_JSON, _DB_ENABLED
    if not DATABASE_URL:
        _DB_ENABLED = False
        return
    try:
        import psycopg2 as pg
        from psycopg2.extras import Json as pgjson
        _PG, _PG_JSON = pg, pgjson
        conn = pg.connect(DATABASE_URL)
        with conn, conn.cursor() as cur:
            cur.execute(
                "CREATE TABLE IF NOT EXISTS bookings ("
                "ref TEXT PRIMARY KEY, data JSONB NOT NULL, updated_at BIGINT);")
            cur.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "email TEXT PRIMARY KEY, data JSONB NOT NULL);")
        conn.close()
        _DB_ENABLED = True
        print("[store] using Postgres (DATABASE_URL)", flush=True)
    except Exception as e:  # noqa: BLE001
        _DB_ENABLED = False
        print("[store] Postgres unavailable (%s) — using JSON file" % e, flush=True)


def load_bookings():
    global BOOKINGS
    if _DB_ENABLED:
        try:
            conn = _PG.connect(DATABASE_URL)
            with conn, conn.cursor() as cur:
                cur.execute("SELECT data FROM bookings;")
                rows = cur.fetchall()
            conn.close()
            BOOKINGS = {r[0]["ref"]: r[0] for r in rows}
            return
        except Exception as e:  # noqa: BLE001
            print("[store] DB load failed (%s)" % e, flush=True)
            BOOKINGS = {}
            return
    try:
        with open(BOOKINGS_FILE, "r") as f:
            BOOKINGS = {b["ref"]: b for b in json.load(f)}
    except Exception:
        BOOKINGS = {}


def persist_bookings():
    """Persist the working set. Call sites already hold _BOOKINGS_LOCK.
    (Writes all rows; fine at this scale — switch to per-row upserts if it grows.)"""
    if _DB_ENABLED:
        try:
            conn = _PG.connect(DATABASE_URL)
            with conn, conn.cursor() as cur:
                for b in BOOKINGS.values():
                    cur.execute(
                        "INSERT INTO bookings (ref, data, updated_at) VALUES (%s, %s, %s) "
                        "ON CONFLICT (ref) DO UPDATE SET data = EXCLUDED.data, "
                        "updated_at = EXCLUDED.updated_at;",
                        (b["ref"], _PG_JSON(b), b.get("updatedAt")))
            conn.close()
            return
        except Exception as e:  # noqa: BLE001
            print("[store] DB save failed (%s)" % e, flush=True)
            return
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(BOOKINGS_FILE, "w") as f:
            json.dump(list(BOOKINGS.values()), f, indent=2)
    except Exception as e:  # noqa: BLE001
        print("[store] save failed: %s" % e, flush=True)


def upsert_booking(b):
    """Insert or update a booking. Normalizes the ref and stamps timestamps."""
    ref = (b.get("ref") or "").lstrip("#").strip() or ("LX-" + uuid.uuid4().hex[:6].upper())
    b["ref"] = ref
    now = int(time.time() * 1000)
    with _BOOKINGS_LOCK:
        rec = BOOKINGS.get(ref, {})
        rec.update(b)
        rec.setdefault("status", "available")
        rec.setdefault("createdAt", now)
        rec["updatedAt"] = now
        if rec.get("total") is not None:
            rec["driverEarn"] = round(float(rec["total"]) * DRIVER_SHARE, 2)
        BOOKINGS[ref] = rec
        persist_bookings()
    return BOOKINGS[ref]


def seed_demo_rides():
    """Put a few unassigned rides in the pool so the driver app has something
    to show on first run. Skipped if the store already has data, or if demo
    seeding is disabled (set LUXLANE_SEED_DEMO=0 in production)."""
    if BOOKINGS or not SEED_DEMO:
        return
    demo = [
        {"ref": "LX-DEMO01", "service": "Airport Transfer", "serviceKey": "airport",
         "pickup": "JFK International Airport, Terminal 4",
         "dropoff": "The Plaza Hotel, 5th Avenue, Manhattan",
         "dateISO": "2026-06-19T15:30", "passengers": "2",
         "vehicle": "Luxury SUV", "vehicleEmoji": "🚙", "distance": 32,
         "total": 255.30, "passenger": "Marcus Reynolds", "phone": "+1 555 0142"},
        {"ref": "LX-DEMO02", "service": "City Transfer", "serviceKey": "city",
         "pickup": "Wall Street, Financial District",
         "dropoff": "Brooklyn Bridge Park, DUMBO",
         "dateISO": "2026-06-19T17:00", "passengers": "1",
         "vehicle": "Executive Sedan", "vehicleEmoji": "🚗", "distance": 9,
         "total": 110.40, "passenger": "Sophia Laurent", "phone": "+1 555 0199"},
        {"ref": "LX-DEMO03", "service": "Intercity", "serviceKey": "intercity",
         "pickup": "Midtown Manhattan",
         "dropoff": "Newark Liberty International Airport",
         "dateISO": "2026-06-19T19:15", "passengers": "4",
         "vehicle": "Mercedes Sprinter Van", "vehicleEmoji": "🚐", "distance": 28,
         "total": 184.00, "passenger": "James Kaur", "phone": "+1 555 0123"},
    ]
    now = int(time.time() * 1000)
    for b in demo:
        b["status"] = "available"
        b["createdAt"] = b["updatedAt"] = now
        b["driverEarn"] = round(b["total"] * DRIVER_SHARE, 2)
        BOOKINGS[b["ref"]] = b
    persist_bookings()


# ---------------------------------------------------------------- accounts
def load_users():
    global USERS
    if _DB_ENABLED:
        try:
            conn = _PG.connect(DATABASE_URL)
            with conn, conn.cursor() as cur:
                cur.execute("SELECT data FROM users;")
                rows = cur.fetchall()
            conn.close()
            USERS = {r[0]["email"]: r[0] for r in rows}
            return
        except Exception as e:  # noqa: BLE001
            print("[store] users load failed (%s)" % e, flush=True)
            USERS = {}
            return
    try:
        with open(USERS_FILE, "r") as f:
            USERS = {u["email"]: u for u in json.load(f)}
    except Exception:
        USERS = {}


def persist_users():
    if _DB_ENABLED:
        try:
            conn = _PG.connect(DATABASE_URL)
            with conn, conn.cursor() as cur:
                for u in USERS.values():
                    cur.execute(
                        "INSERT INTO users (email, data) VALUES (%s, %s) "
                        "ON CONFLICT (email) DO UPDATE SET data = EXCLUDED.data;",
                        (u["email"], _PG_JSON(u)))
            conn.close()
            return
        except Exception as e:  # noqa: BLE001
            print("[store] users save failed (%s)" % e, flush=True)
            return
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(USERS_FILE, "w") as f:
            json.dump(list(USERS.values()), f, indent=2)
    except Exception as e:  # noqa: BLE001
        print("[store] users save failed: %s" % e, flush=True)


def hash_password(pw):
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), 120000)
    return "pbkdf2_sha256$120000$%s$%s" % (salt, dk.hex())


def verify_password(pw, stored):
    try:
        algo, iters, salt, h = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode("utf-8"), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), h)
    except Exception:  # noqa: BLE001
        return False


def new_session(email, role):
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {"email": email, "role": role,
                       "exp": int(time.time() * 1000) + SESSION_TTL_MS}
    return token


def session_user(token):
    if not token:
        return None
    s = SESSIONS.get(token)
    if not s:
        return None
    if s["exp"] < int(time.time() * 1000):
        SESSIONS.pop(token, None)
        return None
    return USERS.get(s["email"])


def public_user(u):
    return {"id": u["email"], "name": u["name"], "email": u["email"], "role": u["role"]}


EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def send_email(to, subject, body):
    """Send an email if SMTP is configured, otherwise log it (so the flow is
    testable without a mail server). Never raises."""
    if not (SMTP_HOST and to):
        print("[email] (not configured) to=%s subject=%r" % (to, subject), flush=True)
        return
    try:
        msg = EmailMessage()
        msg["From"] = EMAIL_FROM
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(body)
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as s:
            s.starttls()
            if SMTP_USER:
                s.login(SMTP_USER, SMTP_PASS)
            s.send_message(msg)
        print("[email] sent to %s (%s)" % (to, subject), flush=True)
    except Exception as e:  # noqa: BLE001
        print("[email] send failed (%s)" % e, flush=True)


# ---------------------------------------------------------------- stripe api
def stripe_post(path, data):
    body = urllib.parse.urlencode(data, doseq=True).encode()
    req = urllib.request.Request(
        "https://api.stripe.com" + path, data=body,
        headers={
            "Authorization": "Bearer " + STRIPE_SECRET_KEY,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


def stripe_get(path):
    req = urllib.request.Request(
        "https://api.stripe.com" + path,
        headers={"Authorization": "Bearer " + STRIPE_SECRET_KEY},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read())


# ---------------------------------------------------------------- handler
class Handler(SimpleHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw or b"{}"), raw
        except json.JSONDecodeError:
            return {}, raw

    def _base_url(self):
        host = self.headers.get("Host", "localhost:4173")
        return "http://" + host

    # ---- routing ----
    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/quote":
            params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
            return self._json(compute_quote(params))
        if path == "/api/checkout-status":
            return self.handle_checkout_status()
        if path == "/api/mock-session":
            return self.handle_mock_session()
        if path == "/api/rides":
            return self.handle_list_rides()
        if path == "/api/rides/track":
            return self.handle_ride_track()
        if path == "/api/auth/me":
            return self.handle_auth_me()
        if path == "/api/config":
            return self._json({"mode": "mock" if MOCK else "live", "currency": CURRENCY,
                               "distances": "mapbox" if MAPBOX_ACCESS_TOKEN else "estimate",
                               "storage": "postgres" if _DB_ENABLED else "file",
                               "email": "smtp" if SMTP_HOST else "log",
                               # Only public (pk.) tokens are exposed to the browser
                               # for address autocomplete; secret tokens are never sent.
                               "mapboxToken": MAPBOX_ACCESS_TOKEN if MAPBOX_ACCESS_TOKEN.startswith("pk.") else "",
                               "auth": True})
        return super().do_GET()

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path == "/api/create-checkout-session":
            return self.handle_create_session()
        if path == "/api/quote":
            data, _ = self._read_json()
            return self._json(compute_quote(data))
        if path == "/api/mock-pay":
            return self.handle_mock_pay()
        if path == "/api/webhook":
            return self.handle_webhook()
        if path == "/api/bookings":
            return self.handle_save_booking()
        if path == "/api/auth/register":
            return self.handle_auth_register()
        if path == "/api/auth/login":
            return self.handle_auth_login()
        if path == "/api/auth/logout":
            return self.handle_auth_logout()
        if path == "/api/rides/accept":
            return self.handle_ride_accept()
        if path == "/api/rides/status":
            return self.handle_ride_status()
        if path == "/api/rides/location":
            return self.handle_ride_location()
        self._json({"error": "not found"}, 404)

    # ---- checkout session ----
    def handle_create_session(self):
        data, _ = self._read_json()
        quote = compute_quote(data)
        ref = (data.get("ref") or "").lstrip("#") or ("LX-" + uuid.uuid4().hex[:6].upper())
        email = data.get("email") or ""
        base = self._base_url()
        success = base + "/booking.html?paid=1&session_id={CHECKOUT_SESSION_ID}"
        cancel = base + "/booking.html?canceled=1"
        label = "%s — %s" % (quote["serviceLabel"], quote["vehicle"])
        route = "%s → %s" % (data.get("pickup", "Pickup"), data.get("dropoff", "Destination"))
        desc = ("%d hours" % quote["hours"]) if quote["hours"] else ("~%d km · %s" % (quote["distance"], route))

        if quote["amount_cents"] < 50:
            return self._json({"error": "Amount below minimum charge."}, 400)

        if MOCK:
            sid = "cs_mock_" + uuid.uuid4().hex
            MOCK_SESSIONS[sid] = {
                "amount": quote["amount_cents"], "currency": CURRENCY,
                "label": label, "desc": desc, "ref": ref, "email": email,
                "success_url": success.replace("{CHECKOUT_SESSION_ID}", sid),
                "cancel_url": cancel, "payment_status": "unpaid", "quote": quote,
            }
            return self._json({"url": base + "/mock-checkout.html?session_id=" + sid,
                               "id": sid, "mock": True, **quote})

        # Real Stripe Checkout Session
        params = {
            "mode": "payment",
            "success_url": success,
            "cancel_url": cancel,
            "client_reference_id": ref,
            "line_items[0][quantity]": 1,
            "line_items[0][price_data][currency]": CURRENCY,
            "line_items[0][price_data][unit_amount]": quote["amount_cents"],
            "line_items[0][price_data][product_data][name]": label,
            "line_items[0][price_data][product_data][description]": desc,
            "payment_method_types[0]": "card",
            "metadata[ref]": ref,
            "metadata[service]": quote["serviceLabel"],
            "metadata[vehicle]": quote["vehicle"],
            "metadata[pickup]": data.get("pickup", ""),
            "metadata[dropoff]": data.get("dropoff", ""),
        }
        if email:
            params["customer_email"] = email
        try:
            session = stripe_post("/v1/checkout/sessions", params)
        except urllib.error.HTTPError as e:
            return self._json({"error": e.read().decode("utf-8", "replace")}, 502)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": str(e)}, 502)
        return self._json({"url": session.get("url"), "id": session.get("id"), **quote})

    def handle_checkout_status(self):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        sid = params.get("session_id", "")
        if MOCK:
            sess = MOCK_SESSIONS.get(sid)
            status = sess["payment_status"] if sess else "unpaid"
            return self._json({"payment_status": status, "mock": True})
        try:
            session = stripe_get("/v1/checkout/sessions/" + urllib.parse.quote(sid))
        except Exception as e:  # noqa: BLE001
            return self._json({"payment_status": "unknown", "error": str(e)}, 502)
        return self._json({"payment_status": session.get("payment_status"),
                           "ref": session.get("client_reference_id")})

    # ---- mock-mode helpers ----
    def handle_mock_session(self):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        sess = MOCK_SESSIONS.get(params.get("session_id", ""))
        if not sess:
            return self._json({"error": "session not found"}, 404)
        return self._json({"amount": sess["amount"], "currency": sess["currency"],
                           "label": sess["label"], "desc": sess["desc"],
                           "ref": sess["ref"], "email": sess["email"]})

    def handle_mock_pay(self):
        data, _ = self._read_json()
        sess = MOCK_SESSIONS.get(data.get("session_id", ""))
        if not sess:
            return self._json({"error": "session not found"}, 404)
        sess["payment_status"] = "paid"
        PAID_BOOKINGS[sess["ref"]] = sess["quote"]
        print("[mock] payment captured for %s — %s %.2f" %
              (sess["ref"], CURRENCY.upper(), sess["amount"] / 100))
        return self._json({"success_url": sess["success_url"]})

    # ---- webhook ----
    def handle_webhook(self):
        _, raw = self._read_json()
        if STRIPE_WEBHOOK_SECRET:
            sig = self.headers.get("Stripe-Signature", "")
            if not self._verify_signature(raw, sig):
                return self._json({"error": "invalid signature"}, 400)
        try:
            event = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad payload"}, 400)
        if event.get("type") == "checkout.session.completed":
            session = event.get("data", {}).get("object", {})
            ref = session.get("client_reference_id")
            if ref:
                PAID_BOOKINGS[ref] = session
                print("[webhook] checkout.session.completed for %s" % ref)
        return self._json({"received": True})

    def _verify_signature(self, payload, sig_header):
        try:
            parts = dict(p.split("=", 1) for p in sig_header.split(","))
            t, v1 = parts.get("t"), parts.get("v1")
            signed = ("%s." % t).encode() + payload
            expected = hmac.new(STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
            return hmac.compare_digest(expected, v1 or "")
        except Exception:  # noqa: BLE001
            return False

    # ---- driver / rides ----
    def handle_save_booking(self):
        data, _ = self._read_json()
        ref_key = (data.get("ref") or "").lstrip("#").strip()
        with _BOOKINGS_LOCK:
            is_new = ref_key not in BOOKINGS
        rec = upsert_booking(data)
        if is_new and rec.get("email"):
            send_email(
                rec["email"], "Your Luxlane booking is confirmed (#%s)" % rec["ref"],
                "Hi %s,\n\nYour ride is confirmed.\n\n"
                "Reference: #%s\nService: %s\nPick-up: %s\nDrop-off: %s\nVehicle: %s\nTotal: $%s\n\n"
                "You can track your chauffeur live from My Trips.\n\n— Luxlane"
                % (rec.get("passenger", "there"), rec["ref"], rec.get("service", ""),
                   rec.get("pickup", ""), rec.get("dropoff", ""), rec.get("vehicle", ""),
                   rec.get("total", "")))
        return self._json({"ok": True, "ref": rec["ref"]})

    def handle_list_rides(self):
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        driver = params.get("driver")
        status = params.get("status")
        with _BOOKINGS_LOCK:
            items = list(BOOKINGS.values())
        if driver:
            items = [b for b in items if b.get("driverId") == driver]
        elif status == "available":
            items = [b for b in items if b.get("status") == "available"]
        elif status:
            items = [b for b in items if b.get("status") == status]
        items.sort(key=lambda b: b.get("dateISO") or "")
        return self._json({"rides": items, "count": len(items)})

    def _auth_token(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth[7:].strip()
        return None

    def handle_auth_register(self):
        data, _ = self._read_json()
        name = (data.get("name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        role = data.get("role") if data.get("role") in ("customer", "driver") else "customer"
        if not name:
            return self._json({"error": "Please enter your name."}, 400)
        if not EMAIL_RE.match(email):
            return self._json({"error": "Please enter a valid email."}, 400)
        if len(password) < 6:
            return self._json({"error": "Password must be at least 6 characters."}, 400)
        with _USERS_LOCK:
            if email in USERS:
                return self._json({"error": "An account with this email already exists."}, 409)
            user = {"email": email, "name": name, "role": role,
                    "pwd": hash_password(password), "createdAt": int(time.time() * 1000)}
            USERS[email] = user
            persist_users()
        token = new_session(email, role)
        send_email(email, "Welcome to Luxlane",
                   "Hi %s,\n\nYour Luxlane %s account is ready. Enjoy the ride.\n\n— Luxlane"
                   % (name, role))
        print("[auth] registered %s (%s)" % (email, role), flush=True)
        return self._json({"token": token, "user": public_user(user)})

    def handle_auth_login(self):
        data, _ = self._read_json()
        email = (data.get("email") or "").strip().lower()
        password = data.get("password") or ""
        want_role = data.get("role") if data.get("role") in ("customer", "driver") else None
        user = USERS.get(email)
        if not user or not verify_password(password, user.get("pwd", "")):
            return self._json({"error": "Incorrect email or password."}, 401)
        if want_role and user.get("role") != want_role:
            other = "driver" if want_role == "customer" else "customer"
            return self._json({"error": "This email is registered as a %s account." % other}, 403)
        token = new_session(email, user["role"])
        return self._json({"token": token, "user": public_user(user)})

    def handle_auth_me(self):
        user = session_user(self._auth_token())
        if not user:
            return self._json({"error": "Not signed in."}, 401)
        return self._json({"user": public_user(user)})

    def handle_auth_logout(self):
        token = self._auth_token()
        if token:
            SESSIONS.pop(token, None)
        return self._json({"ok": True})

    def handle_ride_accept(self):
        data, _ = self._read_json()
        ref = (data.get("ref") or "").lstrip("#").strip()
        driver_id = data.get("driverId")
        driver_name = data.get("driverName")
        if not ref or not driver_id:
            return self._json({"error": "Missing ride or driver."}, 400)
        now = int(time.time() * 1000)
        with _BOOKINGS_LOCK:
            b = BOOKINGS.get(ref)
            if not b:
                return self._json({"error": "Ride not found."}, 404)
            if b.get("status") != "available" and b.get("driverId") != driver_id:
                return self._json({"error": "This ride was already taken."}, 409)
            b["status"] = "assigned"
            b["driverId"] = driver_id
            b["driverName"] = driver_name
            b["acceptedAt"] = now
            b["updatedAt"] = now
            persist_bookings()
            ride = dict(b)
        print("[ride] %s accepted by %s" % (ref, driver_name), flush=True)
        return self._json({"ok": True, "ride": ride})

    def handle_ride_status(self):
        data, _ = self._read_json()
        ref = (data.get("ref") or "").lstrip("#").strip()
        driver_id = data.get("driverId")
        status = data.get("status")
        if status not in RIDE_STATUSES:
            return self._json({"error": "Invalid status."}, 400)
        now = int(time.time() * 1000)
        with _BOOKINGS_LOCK:
            b = BOOKINGS.get(ref)
            if not b:
                return self._json({"error": "Ride not found."}, 404)
            if b.get("driverId") != driver_id:
                return self._json({"error": "Not your ride."}, 403)
            if status == "available":  # driver releases the ride back to the pool
                b["driverId"] = None
                b["driverName"] = None
            b["status"] = status
            b["updatedAt"] = now
            if status == "on_trip" and not b.get("tripStartedAt"):
                b["tripStartedAt"] = now
            if status == "completed":
                b["completedAt"] = now
            persist_bookings()
            ride = dict(b)
        return self._json({"ok": True, "ride": ride})

    def handle_ride_location(self):
        """A driver's device pushes its live position (best-effort GPS)."""
        data, _ = self._read_json()
        ref = (data.get("ref") or "").lstrip("#").strip()
        driver_id = data.get("driverId")
        with _BOOKINGS_LOCK:
            b = BOOKINGS.get(ref)
            if not b:
                return self._json({"error": "Ride not found."}, 404)
            if b.get("driverId") != driver_id:
                return self._json({"error": "Not your ride."}, 403)
            LOCATIONS[ref] = {
                "lat": data.get("lat"), "lon": data.get("lon"),
                "progress": data.get("progress"), "etaMin": data.get("etaMin"),
                "leg": data.get("leg"), "updatedAt": int(time.time() * 1000),
            }
        return self._json({"ok": True})

    def handle_ride_track(self):
        """Live status for the customer's tracking screen. Uses fresh pushed GPS
        when available, otherwise synthesizes progress from elapsed time."""
        params = dict(urllib.parse.parse_qsl(urllib.parse.urlparse(self.path).query))
        ref = (params.get("ref") or "").lstrip("#").strip()
        now = int(time.time() * 1000)
        with _BOOKINGS_LOCK:
            b = BOOKINGS.get(ref)
            loc = LOCATIONS.get(ref)
        if not b:
            return self._json({"found": False}, 404)

        status = b.get("status", "available")
        fresh = bool(loc and (now - loc.get("updatedAt", 0) < LOCATION_FRESH_MS))
        total_min = max(2, round((b.get("distance") or 10) / 40.0 * 60))
        progress, eta, leg = 0.0, None, "approach"
        lat = lon = None

        if status == "completed":
            progress, eta, leg = 1.0, 0, "trip"
        elif status == "on_trip":
            leg = "trip"
            if fresh and loc.get("progress") is not None:
                progress, eta = loc["progress"], loc.get("etaMin")
            else:
                started = b.get("tripStartedAt") or now
                progress = min(1.0, (now - started) / float(DEMO_TRIP_MS))
                eta = round((1 - progress) * total_min)
        elif status == "arrived":
            progress, eta, leg = 1.0, 0, "approach"
        elif status == "assigned":
            leg = "approach"
            if fresh and loc.get("progress") is not None:
                progress, eta = loc["progress"], loc.get("etaMin")
            else:
                acc = b.get("acceptedAt") or now
                progress = min(1.0, (now - acc) / float(DEMO_APPROACH_MS))
                eta = round((1 - progress) * 5)
        if fresh:
            lat, lon = loc.get("lat"), loc.get("lon")

        return self._json({
            "found": True, "ref": ref, "status": status, "leg": leg,
            "pickup": b.get("pickup"), "dropoff": b.get("dropoff"),
            "vehicle": b.get("vehicle"), "vehicleEmoji": b.get("vehicleEmoji"),
            "driverName": b.get("driverName"), "passenger": b.get("passenger"),
            "distance": b.get("distance"),
            "progress": round(progress, 3), "etaMin": eta, "lat": lat, "lon": lon,
            "updatedAt": now,
        })

    def log_message(self, fmt, *args):
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)


def main():
    # Port priority: CLI arg > $PORT (set by hosts like Render/Railway) > 4173.
    port = int(sys.argv[1]) if len(sys.argv) > 1 else int(os.environ.get("PORT", "4173"))
    init_storage()
    load_bookings()
    load_users()
    seed_demo_rides()
    handler = functools.partial(Handler, directory=ROOT)
    httpd = ThreadingHTTPServer(("", port), handler)
    mode = "MOCK (no Stripe key set)" if MOCK else "LIVE Stripe"
    dist = "Mapbox live distances" if MAPBOX_ACCESS_TOKEN else "estimate fallback"
    store = "Postgres" if _DB_ENABLED else "JSON file"
    mail = "SMTP" if SMTP_HOST else "log-only"
    print("Luxlane server on http://localhost:%d  [%s | %s | store: %s | email: %s | auth: on]"
          % (port, mode, dist, store, mail))
    if MOCK:
        print("  -> Set STRIPE_SECRET_KEY to enable real Stripe Checkout.")
    if not MAPBOX_ACCESS_TOKEN:
        print("  -> Set MAPBOX_ACCESS_TOKEN to enable real driving-distance pricing.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.shutdown()


if __name__ == "__main__":
    main()
