# Luxlane Driver App

The driver-facing side of the platform — a mobile **PWA** (installable web app)
that drivers use to receive and accept ("allot") rides, run the trip, and track
earnings. It shares one bookings pool with the customer site through the server.

Open it at **`/driver.html`** (e.g. http://localhost:4173/driver.html), or via
the "🚘 Drive with Us" link in the customer site footer.

## How it works

```
Customer books & pays ──► POST /api/bookings ──► shared ride pool (server, data/bookings.json)
                                                        │
Driver app ──GET /api/rides?status=available──────────►│  shows available rides
   Accept  ──POST /api/rides/accept──────────────────► │  ride -> assigned to driver
   Trip    ──POST /api/rides/status (arrived/on_trip/completed)
   Earnings ◄── completed rides × 80% driver share
```

The driver app polls every 5 seconds while online, so new customer bookings
appear automatically.

## Features

- **Sign in** — any name + 4-digit PIN (mock auth; swap for real auth in production).
- **Online / Offline toggle** — only receive rides when online.
- **Available Rides** — pickup/drop-off, time, distance, passenger count, fare, and
  the driver's earnings (80% of fare). One tap to **Accept**.
- **My Rides** — accepted trips with a status workflow:
  `Arrived → Start Trip → Complete Trip`, plus a **Navigate** button (opens Google Maps).
- **Earnings** — total earned, trips completed, average per trip, and a payout list.
- **Profile** — driver identity, rating, sign out.
- **Installable** — `manifest.webmanifest` + `sw.js` service worker; "Add to Home
  Screen" gives a full-screen app with an offline shell.

## Demo data

On first run the server seeds 3 sample rides so the pool isn't empty. Delete
`data/bookings.json` (or it's recreated) to reset to a clean demo state.

## Run

```bash
python3 server.py
# customer site:  http://localhost:4173/
# driver app:     http://localhost:4173/driver.html
```

## Production next steps

- **Real driver auth** (phone OTP / accounts) + background checks & document upload.
- **Real-time push** instead of polling (WebSocket / Server-Sent Events) and push
  notifications for new ride offers.
- **Live GPS**: stream the driver's location so customers can track the car
  (pairs with the customer-side live-tracking roadmap item).
- **Dispatch logic**: auto-offer the nearest online driver, accept timeout, surge,
  driver ratings — instead of an open "claim any ride" pool.
- **Database** for the bookings pool (Postgres) instead of the JSON file.
- **Payouts** via Stripe Connect (pay drivers their share automatically).
