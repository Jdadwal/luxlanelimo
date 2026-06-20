# Luxlane — Roadmap to Best-in-Class

Current state: polished, fully-functional **front-end prototype** (HTML/CSS/JS).
Validation, dynamic pricing, localStorage persistence, mock auth, and a trips
page all work and are browser-verified. Everything below is what turns this
prototype into a real, shippable product.

---

## 1. Real backend (highest impact)
- [~] **Maps/geocoding** — Mapbox geocoding + Matrix API integrated for real
      driving-distance pricing (server-side, tamper-proof, cached, graceful fallback
      to the estimate). Runs on the estimate until a token is added — see
      `MAPS_SETUP.md`. **Still to do:** address autocomplete in the form + a live map.
- [x] **Payments** — Stripe Checkout integrated (server-side dynamic pricing,
      redirect flow, success/cancel handling, webhook receiver). Runs in mock mode
      until a key is added. See `STRIPE_SETUP.md`. Cards/Apple/Google Pay handled by
      Stripe's hosted page — we never touch raw card data.
- [x] **Database + accounts** — Postgres persistence (bookings survive restarts
      when `DATABASE_URL` is set; auto-falls back to JSON). **Real authentication**
      for customers and drivers: PBKDF2-SHA256 hashed passwords, session tokens,
      persisted accounts, role enforcement. See `DEPLOY.md`.
- [~] **Email/SMS** — email hook done: welcome + booking-confirmation emails send
      via SMTP when configured, log otherwise (set `SMTP_*` env vars). **Still to do:**
      SMS alerts (Twilio) for driver-arrival, which needs a paid account/keys.

## 2. Trust & conversion (cheap, high ROI)
- [x] **Live ride tracking** (`track.html`) — customer watches the chauffeur on a
      live map with the car moving along the route, status, ETA countdown, driver
      card, and progress bar. Driver streams position (`/api/rides/location`); the
      server synthesizes smooth progress from elapsed time when no GPS feed is
      present, so it works in the demo. "📍 Track Ride" button on My Trips.
      **Still to do:** real street map (Mapbox GL) + true GPS projection.
- [ ] Fixed-price guarantee badge + transparent fare breakdown before payment.
- [ ] Reviews with real names/photos and a verified rating.
- [ ] Cancellation/refund policy shown inline at checkout.

## 2b. Driver app — DONE (foundation)
- [x] **Driver mobile app** (`driver.html`) — installable PWA: sign-in, online/offline,
      available-rides pool, accept rides, trip workflow (arrived → start → complete),
      earnings, navigate. Shares one ride pool with the customer site via the server.
      See `DRIVER_APP.md`. **Still to do:** real driver auth, GPS streaming, push
      notifications, dispatch/matching logic, Stripe Connect payouts.

## 3. Differentiation
- [ ] Sustainability: carbon-offset toggle, EV filter, "CO₂ saved" on receipts.
- [ ] Concierge layer: in-app chat, flight-delay auto-rebooking, favorite driver.
- [ ] Business portal: team accounts, cost centers, approvals, monthly invoice, CSV export.
- [ ] Loyalty tiers: upgrades, priority dispatch.

## 4. Polish & reach
- [ ] PWA / native app (installable, offline, push).
- [ ] Accessibility audit (WCAG AA): keyboard nav, focus states, ARIA, contrast.
- [ ] Performance & SEO: image optimization, meta/OpenGraph, structured data, sitemap.
- [ ] Multi-currency / multi-language.
- [ ] Analytics + A/B testing on the booking funnel.

---

## Recommended build order
1. Maps autocomplete + real pricing
2. Stripe checkout
3. Accounts / database
4. Live tracking

**Suggested stack:** Next.js + Supabase + Stripe + Mapbox — reuses the current
design while adding the real machinery.

## IP note
This is an original design *inspired by* the category, not a copy of any specific
brand's assets. Keep your own name, logo, copy, and photos before going live.
