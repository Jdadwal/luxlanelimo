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
import base64
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
EMAIL_FROM = os.environ.get("EMAIL_FROM", "Luxlane Limo <reserve@luxlanelimo.ca>").strip()

# Business contact details (shown on the site + used by the concierge).
COMPANY_NAME = os.environ.get("COMPANY_NAME", "Luxlane Limo").strip()
COMPANY_EMAIL = os.environ.get("COMPANY_EMAIL", "reserve@luxlanelimo.ca").strip()
COMPANY_PHONE = os.environ.get("COMPANY_PHONE", "+1 (416) 676-2669").strip()
COMPANY_PHONE_E164 = os.environ.get("COMPANY_PHONE_E164", "+14166762669").strip()
WHATSAPP_NUMBER = os.environ.get("WHATSAPP_NUMBER", "14166762669").strip()

# AI concierge. With a key it answers via Claude; without one it uses scripted
# replies, so the concierge works either way. (anthropic SDK imported lazily.)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
CONCIERGE_MODEL = os.environ.get("CONCIERGE_MODEL", "claude-opus-4-8").strip()

# Admin dashboard password. CHANGE THIS in production by setting ADMIN_PASSWORD.
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin1234").strip()

# SMS (Twilio). Sends real texts when all three are set; otherwise logs them so
# the flow is testable without an account. Secrets come from the environment only.
TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID", "").strip()
TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "").strip()
TWILIO_FROM_NUMBER = os.environ.get("TWILIO_FROM_NUMBER", "").strip()
# Optional: authenticate with a Twilio API Key (SK… + secret) instead of the
# Auth Token — recommended. Still needs TWILIO_ACCOUNT_SID for the request URL.
TWILIO_API_KEY_SID = os.environ.get("TWILIO_API_KEY_SID", "").strip()
TWILIO_API_KEY_SECRET = os.environ.get("TWILIO_API_KEY_SECRET", "").strip()
# Where new-booking SMS alerts go (defaults to the business line).
ADMIN_SMS_TO = os.environ.get("ADMIN_SMS_TO", COMPANY_PHONE_E164).strip()

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
               "?annotations=distance&access_token=%s"
               % (coord_str, MAPBOX_ACCESS_TOKEN))
        req = urllib.request.Request(url, headers={"User-Agent": "LuxlaneServer"})
        with urllib.request.urlopen(req, timeout=6) as resp:
            matrix = json.loads(resp.read().decode())
        meters = matrix["distances"][0][1]
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


def send_sms(to, body):
    """Send an SMS via Twilio when configured, otherwise log it. Never raises.
    Uses an API Key (SK… + secret) when provided, else the Account Auth Token."""
    to = (to or "").strip()
    # Credentials for HTTP Basic auth: API key preferred, Auth Token fallback.
    if TWILIO_API_KEY_SID and TWILIO_API_KEY_SECRET:
        cred_user, cred_secret = TWILIO_API_KEY_SID, TWILIO_API_KEY_SECRET
    else:
        cred_user, cred_secret = TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN
    if not (TWILIO_ACCOUNT_SID and cred_secret and TWILIO_FROM_NUMBER and to):
        print("[sms] (not configured) to=%s body=%r" % (to, body[:60]), flush=True)
        return
    try:
        url = "https://api.twilio.com/2010-04-01/Accounts/%s/Messages.json" % TWILIO_ACCOUNT_SID
        data = urllib.parse.urlencode({"To": to, "From": TWILIO_FROM_NUMBER, "Body": body}).encode()
        auth = base64.b64encode(("%s:%s" % (cred_user, cred_secret)).encode()).decode()
        req = urllib.request.Request(url, data=data, headers={
            "Authorization": "Basic " + auth,
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()
        print("[sms] sent to %s" % to, flush=True)
    except Exception as e:  # noqa: BLE001
        print("[sms] send failed (%s)" % e, flush=True)


# ---------------------------------------------------------------- concierge
def business_facts():
    return (
        "%s is a premium chauffeur service covering the Greater Toronto Area, "
        "Niagara, and cross-border trips to/from the USA. Available 24/7.\n\n"
        "SERVICES: Airport transfers (Pearson YYZ, Billy Bishop, Buffalo) with flight "
        "tracking and free wait time; Cross-border trips between Canada and the USA; "
        "Niagara Falls & wine tours; Corporate travel; Weddings & limousines; Night out.\n\n"
        "FLEET & FLAT 'FROM' RATES: Executive Sedan (3 passengers) from $65; "
        "Luxury SUV (6 passengers) from $135; Mercedes Sprinter Van (12 passengers) from $95; "
        "Stretch Limousine (8 passengers) from $160. Prices are fixed/flat with no surge; "
        "final price depends on distance and is shown before payment.\n\n"
        "BOOKING: Customers book online via the 'Book Now' page — instant fixed quote, "
        "choose a vehicle, pay securely. A 15%% deposit secures the reservation; free "
        "cancellation up to 24 hours before pick-up.\n\n"
        "CONTACT: phone %s, WhatsApp %s, email %s."
        % (COMPANY_NAME, COMPANY_PHONE, COMPANY_PHONE, COMPANY_EMAIL)
    )


def scripted_concierge(message):
    """Keyword-based answers — used when no Anthropic key is configured."""
    m = (message or "").lower()
    contact = "Call %s, WhatsApp %s, or email %s." % (COMPANY_PHONE, COMPANY_PHONE, COMPANY_EMAIL)

    def has(*words):
        return any(w in m for w in words)

    if has("hi", "hello", "hey", "good morning", "good evening"):
        return "Hi! I'm the %s concierge. I can help with rates, our fleet, airport and cross-border trips, Niagara tours, and booking. What do you need?" % COMPANY_NAME
    if has("price", "rate", "cost", "how much", "quote", "fare"):
        return ("Our flat 'from' rates: Executive Sedan from $65, Mercedes Sprinter Van from $95, "
                "Luxury SUV from $135, Stretch Limousine from $160. Prices are fixed with no surge — "
                "you'll see the exact price (based on distance) before you pay. Get an instant quote on the Book Now page.")
    if has("vehicle", "fleet", "car", "suv", "sedan", "van", "sprinter", "limo", "seats", "passengers"):
        return ("Our fleet: Executive Sedan (up to 3), Luxury SUV (up to 6), Mercedes Sprinter Van (up to 12), "
                "and a Stretch Limousine (up to 8) for weddings and nights out. All are late-model, immaculate, "
                "and driven by professional chauffeurs.")
    if has("airport", "pearson", "yyz", "billy bishop", "buffalo", "flight"):
        return ("Yes — we do airport transfers to/from Pearson (YYZ), Billy Bishop, and Buffalo, with real-time "
                "flight tracking and complimentary wait time. Book on the Book Now page or " + contact)
    if has("border", "usa", "u.s", "united states", "cross", "customs"):
        return ("We specialize in cross-border trips between Canada and the USA — door-to-door, private, and "
                "stress-free at the border. " + contact)
    if has("niagara", "falls", "wine", "tour"):
        return ("We offer Niagara Falls and wine-country tours with a private chauffeur, at your pace, all day. " + contact)
    if has("wedding", "prom", "event", "night out", "concert"):
        return ("For weddings, proms, and nights out we have a stretch limousine and luxury sedans. "
                "Tell us your date and we'll take care of the rest — " + contact)
    if has("corporate", "business", "company", "account"):
        return ("We handle corporate travel with reliable executive transport, centralized billing, and a dedicated "
                "account manager. " + contact)
    if has("book", "reserve", "reservation", "schedule"):
        return ("Booking takes about 2 minutes: open the Book Now page, enter your trip, pick a vehicle, and pay. "
                "A 15% deposit secures it, with free cancellation up to 24h before pick-up.")
    if has("deposit", "pay", "payment", "card", "cancel", "refund"):
        return ("A 15% deposit secures your reservation; the balance is due on the ride. Payments are processed "
                "securely. Free cancellation up to 24 hours before pick-up.")
    if has("area", "where", "service area", "region", "gta", "toronto", "ontario"):
        return ("We cover the Greater Toronto Area, Niagara, and cross-border trips to/from the USA, 24/7.")
    if has("contact", "phone", "call", "email", "whatsapp", "reach", "number"):
        return contact
    if has("hour", "open", "24", "available", "time", "when"):
        return "We're available 24/7, 365 days a year. " + contact
    return ("I can help with rates, our fleet, airport and cross-border trips, Niagara tours, weddings, and booking. "
            "For anything specific, " + contact)


def ai_concierge(message, history):
    """Answer via Claude (prompt-cached system prompt). Returns None on failure
    so the caller can fall back to scripted replies."""
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic  # lazy — only needed when a key is configured
    except Exception as e:  # noqa: BLE001
        print("[concierge] anthropic SDK not installed (%s)" % e, flush=True)
        return None
    system_prompt = (
        "You are the friendly, concise virtual concierge for " + COMPANY_NAME + ", a chauffeur "
        "service. Answer customer questions using ONLY the facts below. Keep replies short "
        "(1-3 sentences), warm, and helpful. Quote the 'from' rates but never invent an exact "
        "total — tell them the Book Now page gives an instant fixed quote. If you don't know "
        "something, share the contact details. Encourage booking when appropriate. "
        "Reply in the customer's language.\n\n=== BUSINESS FACTS ===\n" + business_facts()
    )
    convo = []
    for turn in (history or [])[-10:]:
        role = turn.get("role")
        content = (turn.get("content") or "").strip()
        if role in ("user", "assistant") and content:
            convo.append({"role": role, "content": content})
    convo.append({"role": "user", "content": message})
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        resp = client.messages.create(
            model=CONCIERGE_MODEL,
            max_tokens=400,
            system=[{"type": "text", "text": system_prompt,
                     "cache_control": {"type": "ephemeral"}}],
            messages=convo,
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip() or None
    except Exception as e:  # noqa: BLE001
        print("[concierge] Claude call failed (%s) — using scripted reply" % e, flush=True)
        return None


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
        if path == "/api/admin/bookings":
            return self.handle_admin_bookings()
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
                               "auth": True,
                               "concierge": "ai" if ANTHROPIC_API_KEY else "scripted",
                               "company": {"name": COMPANY_NAME, "email": COMPANY_EMAIL,
                                           "phone": COMPANY_PHONE, "phoneE164": COMPANY_PHONE_E164,
                                           "whatsapp": WHATSAPP_NUMBER}})
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
        if path == "/api/concierge":
            return self.handle_concierge()
        if path == "/api/admin/login":
            return self.handle_admin_login()
        if path == "/api/admin/update":
            return self.handle_admin_update()
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
        if is_new:
            details = ("Reference: #%s\nService: %s\nPick-up: %s\nDrop-off: %s\n"
                       "When: %s\nVehicle: %s\nPassengers: %s\nTotal: $%s"
                       % (rec["ref"], rec.get("service", ""), rec.get("pickup", ""),
                          rec.get("dropoff", ""), rec.get("dateISO", "TBD"),
                          rec.get("vehicle", ""), rec.get("passengers", ""),
                          rec.get("total", "")))
            # Confirmation to the customer
            if rec.get("email"):
                send_email(
                    rec["email"], "Your %s booking is confirmed (#%s)" % (COMPANY_NAME, rec["ref"]),
                    "Hi %s,\n\nYour ride is confirmed.\n\n%s\n\n"
                    "Track your chauffeur live from My Trips. Questions? Call %s or WhatsApp %s.\n\n— %s"
                    % (rec.get("passenger", "there"), details, COMPANY_PHONE, COMPANY_PHONE, COMPANY_NAME))
            # Notification to the reservations inbox
            send_email(
                COMPANY_EMAIL, "New booking #%s — %s" % (rec["ref"], rec.get("service", "")),
                "New reservation received.\n\n%s\n\nPassenger: %s\nEmail: %s\nPhone: %s"
                % (details, rec.get("passenger", ""), rec.get("email", ""), rec.get("phone", "")))
            # SMS: confirm to the customer + alert the business
            if rec.get("phone"):
                send_sms(rec["phone"],
                         "%s: your ride #%s is confirmed for %s (%s). Track it from My Trips. Questions? %s"
                         % (COMPANY_NAME, rec["ref"], rec.get("dateISO", "TBD"), rec.get("vehicle", ""), COMPANY_PHONE))
            send_sms(ADMIN_SMS_TO,
                     "New booking #%s: %s, %s -> %s, %s, $%s (%s)"
                     % (rec["ref"], rec.get("service", ""), rec.get("pickup", ""), rec.get("dropoff", ""),
                        rec.get("vehicle", ""), rec.get("total", ""), rec.get("passenger", "")))
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

    def handle_concierge(self):
        data, _ = self._read_json()
        message = (data.get("message") or "").strip()
        history = data.get("history") or []
        if not message:
            return self._json({"error": "Empty message."}, 400)
        reply = ai_concierge(message, history)
        source = "ai"
        if not reply:
            reply = scripted_concierge(message)
            source = "scripted"
        return self._json({"reply": reply, "source": source})

    # ---- admin dashboard ----
    def _admin_ok(self):
        token = self._auth_token()
        s = SESSIONS.get(token) if token else None
        if not s or s.get("role") != "admin":
            return False
        if s["exp"] < int(time.time() * 1000):
            SESSIONS.pop(token, None)
            return False
        return True

    def handle_admin_login(self):
        data, _ = self._read_json()
        if not ADMIN_PASSWORD or (data.get("password") or "") != ADMIN_PASSWORD:
            return self._json({"error": "Incorrect admin password."}, 401)
        token = secrets.token_urlsafe(32)
        SESSIONS[token] = {"email": "admin", "role": "admin",
                           "exp": int(time.time() * 1000) + SESSION_TTL_MS}
        return self._json({"token": token, "role": "admin"})

    def handle_admin_bookings(self):
        if not self._admin_ok():
            return self._json({"error": "Not authorized."}, 401)
        with _BOOKINGS_LOCK:
            items = list(BOOKINGS.values())
        items.sort(key=lambda b: b.get("createdAt", 0), reverse=True)
        active_statuses = ("available", "assigned", "arrived", "on_trip")
        completed = [b for b in items if b.get("status") == "completed"]
        revenue = round(sum(float(b.get("total") or 0) for b in completed), 2)
        stats = {
            "total": len(items),
            "revenue": revenue,
            "upcoming": len([b for b in items if b.get("status") in active_statuses]),
            "completed": len(completed),
            "cancelled": len([b for b in items if b.get("status") == "cancelled"]),
        }
        drivers = sorted({b.get("driverName") for b in items if b.get("driverName")})
        drivers += [u["name"] for u in USERS.values()
                    if u.get("role") == "driver" and u["name"] not in drivers]
        return self._json({"bookings": items, "stats": stats, "drivers": drivers})

    def handle_admin_update(self):
        if not self._admin_ok():
            return self._json({"error": "Not authorized."}, 401)
        data, _ = self._read_json()
        ref = (data.get("ref") or "").lstrip("#").strip()
        valid = ("available", "assigned", "arrived", "on_trip", "completed", "cancelled")
        now = int(time.time() * 1000)
        with _BOOKINGS_LOCK:
            b = BOOKINGS.get(ref)
            if not b:
                return self._json({"error": "Booking not found."}, 404)
            if "status" in data and data["status"] in valid:
                b["status"] = data["status"]
                if data["status"] == "completed":
                    b["completedAt"] = now
                if data["status"] == "available":
                    b["driverId"] = None
                    b["driverName"] = None
            if "driverName" in data:
                name = (data.get("driverName") or "").strip()
                b["driverName"] = name or None
                b["driverId"] = (re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or None) if name else None
                if name and b.get("status") == "available":
                    b["status"] = "assigned"
            b["updatedAt"] = now
            persist_bookings()
            rec = dict(b)
        return self._json({"ok": True, "booking": rec})

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
        # Text the customer when the chauffeur arrives.
        if status == "arrived" and ride.get("phone"):
            send_sms(ride["phone"],
                     "%s: your chauffeur has arrived at %s for ride #%s. %s"
                     % (COMPANY_NAME, ride.get("pickup", "your pick-up"), ride["ref"], COMPANY_PHONE))
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
