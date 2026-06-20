# Real Distance Pricing — Mapbox Setup

Fares are calculated **on the server** from the real driving distance between the
pick-up and drop-off addresses. This makes pricing both accurate and tamper-proof
(the browser only displays what the server says).

## How it works

```
booking.html  ──POST /api/quote {pickup, dropoff, service}──►  server.py
                                                                  │ road_distance()
                                                                  │   ├─ geocode both addresses (Mapbox Geocoding API)
                                                                  │   └─ driving distance (Mapbox Matrix API)
                                                                  │ fare = vehicle.base + km * vehicle.perKm  (+15% tax)
              ◄──────── { distance, distance_source, total } ─────┘
```

- The client fetches a quote (debounced) as the user types the addresses, and again
  at checkout the server recomputes authoritatively — both use the same cached
  distance, so the displayed price always equals the charged price.
- `distance_source` is `"mapbox"` (live) or `"estimate"` (fallback).

## Without a token (default)

The server falls back to a **deterministic estimate** derived from the address
text. The booking summary labels it "Est. distance". Everything works; the number
just isn't geographically accurate.

## Enable real distances

1. Create a free Mapbox account → copy your **default public token** (`pk....`)
   or create a token from the Mapbox dashboard. The Geocoding and Matrix APIs are
   included in the free tier.

2. Start the server with the token in the environment:

   ```bash
   export MAPBOX_ACCESS_TOKEN=pk.your_token_here
   python3 server.py
   ```

   The startup log will show `Mapbox live distances`. Quotes now return
   `distance_source: "mapbox"` and the summary label changes to "Distance".

   Combine with the Stripe key to run both live:
   ```bash
   export STRIPE_SECRET_KEY=sk_test_xxx
   export MAPBOX_ACCESS_TOKEN=pk.xxx
   python3 server.py
   ```

## Notes

- **Resilient by design:** if Mapbox is unreachable, an address can't be geocoded,
  or the token is missing, the server logs it and falls back to the estimate — the
  booking flow never breaks. (Verified: token set + API offline → graceful fallback.)
- **Caching:** results are cached per address pair (`_DISTANCE_CACHE`) to avoid
  repeat geocoding and stay within rate limits. Use a real cache (Redis) in production.
- **APIs used:** Mapbox Geocoding v5 (`/geocoding/v5/mapbox.places`) and the
  Directions Matrix API (`/directions-matrix/v1/mapbox/driving`).
- **Next step:** add address autocomplete in the booking form using the Mapbox
  Search JS SDK so users pick a real, geocodable address.
