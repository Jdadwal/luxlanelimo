# Stripe Checkout — Setup Guide

The booking flow uses **Stripe Checkout** (the hosted, redirect-based flow).
Customers enter card details on Stripe's own PCI-compliant page — this site
never sees or stores card numbers.

## How it works

```
Booking form (booking.html)
   │  customer fills journey, vehicle, passenger info
   ▼
confirmBooking()  ──POST /api/create-checkout-session──►  server.py
   │                                                          │ computes price
   │                                                          │ creates Stripe
   │            ◄────────────── { url } ──────────────────────┘ Checkout Session
   ▼
window.location = url   →   Stripe-hosted Checkout page (enter card)
   │
   │  on success Stripe redirects to:
   ▼
booking.html?paid=1&session_id=...   →  verify via /api/checkout-status  →  confirmation + saved to My Trips
```

The **price is calculated on the server** (`compute_quote` in `server.py`), so a
user cannot tamper with the amount in the browser. The client-side price is for
display only.

## Run locally

```bash
python3 server.py            # serves on http://localhost:4173
# or choose a port:
python3 server.py 8080
```

With **no key set**, the server runs in **MOCK mode**: it simulates the Stripe
checkout page (`mock-checkout.html`) so you can click through the entire flow
without credentials. You'll see `[MOCK]` in the startup log.

## Go live (real payments)

1. Create a Stripe account → get your **Secret key** (`sk_test_...` for testing,
   `sk_live_...` for production) from the Stripe Dashboard → Developers → API keys.

2. Start the server with the key in the environment:

   ```bash
   export STRIPE_SECRET_KEY=sk_test_xxxxxxxxxxxxx
   export LUXLANE_CURRENCY=usd        # optional, default usd
   python3 server.py
   ```

   The startup log will now say `[LIVE Stripe]`. The mock page is no longer used —
   customers go to the real Stripe Checkout page.

3. Test with Stripe's test card: `4242 4242 4242 4242`, any future expiry, any CVC.

## Webhooks (recommended for production)

A webhook is the reliable way to know a payment succeeded (a customer might close
the tab before the redirect). The endpoint is already implemented at
`POST /api/webhook`.

1. In the Stripe Dashboard → Developers → Webhooks, add an endpoint pointing to
   `https://yourdomain.com/api/webhook` and subscribe to
   `checkout.session.completed`.
2. Copy the signing secret (`whsec_...`) and set it:

   ```bash
   export STRIPE_WEBHOOK_SECRET=whsec_xxxxxxxxxxxxx
   ```

   The server verifies the signature (HMAC-SHA256) before trusting the event.

For local webhook testing, use the Stripe CLI:
```bash
stripe listen --forward-to localhost:4173/api/webhook
```

## Production notes / next steps

- **Persistence:** bookings and `PAID_BOOKINGS` are currently in-memory + browser
  `localStorage`. Move to a real database (Postgres) so paid orders survive restarts.
- **Fulfillment:** act on the payment in the webhook handler (assign a chauffeur,
  send a confirmation email) rather than trusting the redirect alone.
- **WSGI server:** `server.py` uses the stdlib HTTP server (fine for dev). For
  production, port the handlers to Flask/FastAPI behind gunicorn/uvicorn, or to a
  Node/Next.js API route.
- **HTTPS:** Stripe requires HTTPS in live mode. Terminate TLS at your host/reverse proxy.
