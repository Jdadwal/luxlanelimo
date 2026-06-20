/* ===========================
   LUXLANE — APP JAVASCRIPT
   Fully functional: validation, dynamic pricing,
   localStorage persistence, mock auth, trips.
   =========================== */

'use strict';

/* ---------- STORAGE KEYS ---------- */
const LS_BOOKINGS = 'luxlane_bookings';
const LS_USER = 'luxlane_user';

/* ---------- FLEET DATA ---------- */
const FLEET = [
  { id: 1, name: 'Executive Sedan', category: 'Business Class', class: 'business', seats: 3, luggage: 3, base: 65, perKm: 2.2, badge: 'Popular', amenities: ['Wi-Fi', 'Charger', 'Water', 'Mints'], emoji: '🚗', image: 'assets/img/sedan.jpg', desc: 'Lincoln Continental or similar. The benchmark for business travel — refined, comfortable, effortlessly professional.' },
  { id: 2, name: 'Premium Sedan', category: 'Business Class', class: 'business', seats: 3, luggage: 3, base: 70, perKm: 2.3, badge: null, amenities: ['Wi-Fi', 'Charger', 'Water'], emoji: '🚗', image: 'assets/img/sedan.jpg', desc: 'A polished executive sedan for airport runs and city meetings across the GTA.' },
  { id: 3, name: 'First Class Sedan', category: 'First Class', class: 'first', seats: 3, luggage: 4, base: 110, perKm: 3.5, badge: 'First Class', amenities: ['Wi-Fi', 'Charger', 'Water', 'Press', 'Amenity Kit'], emoji: '🚘', image: 'assets/img/sedan.jpg', desc: 'The pinnacle of automotive luxury — premium leather, ambient lighting, and a whisper-quiet cabin.' },
  { id: 4, name: 'Luxury Sedan', category: 'First Class', class: 'first', seats: 3, luggage: 4, base: 115, perKm: 3.6, badge: 'First Class', amenities: ['Wi-Fi', 'Charger', 'Water', 'Press'], emoji: '🚘', image: 'assets/img/sedan.jpg', desc: 'Executive rear seating and a serene ride for VIP guests and long-distance comfort.' },
  { id: 5, name: 'Mercedes Sprinter Van', category: 'Business Van', class: 'van', seats: 12, luggage: 10, base: 95, perKm: 2.8, badge: 'Groups', amenities: ['Wi-Fi', 'Chargers', 'Water', 'Reclining Seats'], emoji: '🚐', image: 'assets/img/sprinter.jpg', desc: 'Spacious and premium — perfect for groups, families, corporate teams, and airport runs with extra luggage.' },
  { id: 6, name: 'Tesla Model S', category: 'Electric', class: 'electric', seats: 3, luggage: 3, base: 90, perKm: 2.5, badge: 'Electric', amenities: ['Wi-Fi', 'Charger', 'Water', 'Autopilot'], emoji: '⚡', image: 'assets/img/sedan.jpg', desc: 'Zero emissions, full luxury. A whisper-silent ride with cutting-edge technology throughout.' },
  { id: 7, name: 'Luxury SUV', category: 'SUV', class: 'suv', seats: 6, luggage: 5, base: 135, perKm: 3.8, badge: 'SUV', amenities: ['Wi-Fi', 'Charger', 'Water', 'Privacy Glass'], emoji: '🚙', image: 'assets/img/suv.jpg', desc: 'Commanding presence and ultimate comfort — preferred for families, ski trips, and high-profile arrivals.' },
  { id: 8, name: 'Cadillac Escalade', category: 'SUV', class: 'suv', seats: 6, luggage: 6, base: 145, perKm: 3.9, badge: 'SUV', amenities: ['Wi-Fi', 'Charger', 'Water', 'Entertainment'], emoji: '🚙', image: 'assets/img/suv.jpg', desc: 'American luxury at its most iconic. A statement vehicle for any occasion.' },
  { id: 9, name: 'Stretch Limousine', category: 'Limousine', class: 'limo', seats: 8, luggage: 4, base: 160, perKm: 4.2, badge: 'Events', amenities: ['Bar', 'Lighting', 'Sound System', 'Privacy'], emoji: '🥂', image: 'assets/img/limo.jpg', desc: 'Stretch limo for weddings, proms, and nights out — arrive in unforgettable style.' },
];

const SERVICE_LABELS = { airport: 'Airport Transfer', hourly: 'Hourly Hire', intercity: 'Intercity', city: 'City Transfer' };

/* =====================================================
   GENERIC UI: navbar, mobile menu, animations, counters
   ===================================================== */
function initChrome() {
  const navbar = document.getElementById('navbar');
  if (navbar && !navbar.classList.contains('scrolled')) {
    const onScroll = () => navbar.classList.toggle('scrolled', window.scrollY > 40);
    window.addEventListener('scroll', onScroll);
    onScroll();
  }

  const hamburger = document.getElementById('hamburger');
  const mobileMenu = document.getElementById('mobileMenu');
  const mobileClose = document.getElementById('mobileClose');
  if (hamburger && mobileMenu) {
    hamburger.addEventListener('click', () => mobileMenu.classList.add('open'));
    mobileClose && mobileClose.addEventListener('click', () => mobileMenu.classList.remove('open'));
    mobileMenu.querySelectorAll('a').forEach(a => a.addEventListener('click', () => mobileMenu.classList.remove('open')));
  }

  // Fade-up
  const fadeEls = document.querySelectorAll('.fade-up');
  if (fadeEls.length && 'IntersectionObserver' in window) {
    const obs = new IntersectionObserver((entries) => {
      entries.forEach((entry, i) => {
        if (entry.isIntersecting) {
          setTimeout(() => entry.target.classList.add('visible'), i * 70);
          obs.unobserve(entry.target);
        }
      });
    }, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
    fadeEls.forEach(el => obs.observe(el));
  } else {
    fadeEls.forEach(el => el.classList.add('visible'));
  }

  // Counters
  const counters = document.querySelectorAll('[data-count]');
  if (counters.length && 'IntersectionObserver' in window) {
    const cObs = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        const el = entry.target;
        const target = parseInt(el.dataset.count, 10);
        const isPct = (el.closest('.stat-item')?.querySelector('.stat-label')?.textContent || '').includes('%');
        const suffix = isPct ? '%' : '+';
        let val = 0;
        const step = Math.max(1, Math.ceil(target / 110));
        const timer = setInterval(() => {
          val = Math.min(val + step, target);
          el.textContent = val + suffix;
          if (val >= target) clearInterval(timer);
        }, 16);
        cObs.unobserve(el);
      });
    }, { threshold: 0.5 });
    counters.forEach(el => cObs.observe(el));
  }

  // Hero booking tabs
  document.querySelectorAll('.booking-tab').forEach(tab => {
    tab.addEventListener('click', () => {
      tab.closest('.booking-tabs').querySelectorAll('.booking-tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      const map = { transfer: 'airport', hourly: 'hourly', intercity: 'intercity' };
      try { sessionStorage.setItem('luxlane_service', map[tab.dataset.tab] || 'airport'); } catch (e) {}
    });
  });

  // Active nav highlight
  const page = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.navbar-nav a').forEach(a => {
    a.classList.toggle('active', a.getAttribute('href') === page);
  });
}

/* =====================================================
   TOAST
   ===================================================== */
function showToast(message, icon) {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const toast = document.createElement('div');
  toast.className = 'toast';
  toast.innerHTML = `<span class="toast-icon">${icon || '✓'}</span><span>${message}</span>`;
  document.body.appendChild(toast);
  setTimeout(() => { toast.classList.add('hide'); setTimeout(() => toast.remove(), 300); }, 3800);
}

/* =====================================================
   HERO FORM -> carry data to booking page
   ===================================================== */
function handleHeroBook(e) {
  e.preventDefault();
  const form = e.target;
  const inputs = form.querySelectorAll('.form-control');
  const data = {
    pickup: inputs[0]?.value.trim() || '',
    dropoff: inputs[1]?.value.trim() || '',
    datetime: inputs[2]?.value || '',
  };
  const activeTab = form.closest('.booking-widget')?.querySelector('.booking-tab.active');
  const map = { transfer: 'airport', hourly: 'hourly', intercity: 'intercity' };
  data.service = map[activeTab?.dataset.tab] || 'airport';
  try { sessionStorage.setItem('luxlane_prefill', JSON.stringify(data)); } catch (err) {}
  window.location.href = 'booking.html';
}

/* =====================================================
   FLEET RENDERING (home + fleet page)
   ===================================================== */
function fleetCardHome(v) {
  return `
    <div class="fleet-card fade-up">
      <div class="fleet-card-image">
        ${v.image ? `<img src="${v.image}" alt="${v.name}" loading="lazy" />` : `<span style="font-size:5rem;">${v.emoji}</span>`}
        ${v.badge ? `<span class="fleet-badge">${v.badge}</span>` : ''}
      </div>
      <div class="fleet-card-body">
        <div class="fleet-card-header">
          <div><h3>${v.name}</h3><p>${v.category}</p></div>
          <div class="fleet-price"><span class="from">from</span><span class="amount">$${v.base}</span></div>
        </div>
        <div class="fleet-features">
          <div class="fleet-feature"><span>👤</span> ${v.seats} seats</div>
          <div class="fleet-feature"><span>🧳</span> ${v.luggage} bags</div>
          <div class="fleet-feature"><span>📶</span> Wi-Fi</div>
        </div>
        <a href="booking.html?vehicle=${v.id}" class="btn btn-primary" style="width:100%;justify-content:center;">Book This Vehicle</a>
      </div>
    </div>`;
}

function renderHomeFleet(classFilter) {
  const grid = document.getElementById('fleetGrid');
  if (!grid) return;
  const filtered = FLEET.filter(v => v.class === classFilter).slice(0, 3);
  grid.innerHTML = filtered.map(fleetCardHome).join('');
  grid.querySelectorAll('.fade-up').forEach(el => setTimeout(() => el.classList.add('visible'), 60));
}

function initHomeFleet() {
  const tabs = document.querySelectorAll('.fleet-tab');
  if (!tabs.length) return;
  renderHomeFleet('business');
  tabs.forEach(tab => tab.addEventListener('click', () => {
    tabs.forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    renderHomeFleet(tab.dataset.fleet);
  }));
}

function renderFullFleet(filter) {
  const grid = document.getElementById('fleetFullGrid');
  if (!grid) return;
  const filtered = filter === 'all' ? FLEET : FLEET.filter(v => v.class === filter);
  if (!filtered.length) {
    grid.innerHTML = `<p style="grid-column:1/-1;text-align:center;color:var(--gray);padding:60px;">No vehicles in this class.</p>`;
    return;
  }
  grid.innerHTML = filtered.map(v => `
    <div class="fleet-detail-card fade-up">
      <div class="fleet-detail-image">
        ${v.image ? `<img src="${v.image}" alt="${v.name}" loading="lazy" />` : `<span style="font-size:5rem;">${v.emoji}</span>`}
        ${v.badge ? `<span class="fleet-badge">${v.badge}</span>` : ''}
      </div>
      <div class="fleet-detail-body">
        <div class="category">${v.category}</div>
        <h3>${v.name}</h3>
        <div class="fleet-specs">
          <div class="spec"><span class="spec-label">Passengers</span><span class="spec-value">Up to ${v.seats}</span></div>
          <div class="spec"><span class="spec-label">Luggage</span><span class="spec-value">${v.luggage} pieces</span></div>
          <div class="spec"><span class="spec-label">From</span><span class="spec-value" style="color:var(--gold);font-weight:600;">$${v.base}</span></div>
          <div class="spec"><span class="spec-label">Per km</span><span class="spec-value">$${v.perKm.toFixed(2)}</span></div>
        </div>
        <p style="font-size:0.875rem;color:var(--gray);line-height:1.7;margin-bottom:16px;">${v.desc}</p>
        <div class="fleet-amenities">${v.amenities.map(a => `<span class="amenity"><span>✓</span>${a}</span>`).join('')}</div>
        <a href="booking.html?vehicle=${v.id}" class="btn btn-primary" style="width:100%;justify-content:center;">Book Now</a>
      </div>
    </div>`).join('');
  grid.querySelectorAll('.fade-up').forEach((el, i) => setTimeout(() => el.classList.add('visible'), i * 50));
}

function initFleetPage() {
  const pills = document.querySelectorAll('.filter-pill');
  if (!pills.length) return;
  renderFullFleet('all');
  pills.forEach(pill => pill.addEventListener('click', () => {
    pills.forEach(p => p.classList.remove('active'));
    pill.classList.add('active');
    renderFullFleet(pill.dataset.filter);
  }));
}

/* =====================================================
   BOOKING ENGINE
   ===================================================== */
const BOOKING = {
  step: 1,
  vehicleId: null,
  payMethod: 'card',
  serverDistance: null,   // km from /api/quote (Mapbox or server estimate)
  distanceSource: null,   // 'mapbox' | 'estimate'
};

/* Deterministic pseudo-distance from two location strings (8–46 km). */
function estimateDistance(a, b) {
  if (!a || !b) return 0;
  const s = (a + '|' + b).toLowerCase().replace(/\s+/g, '');
  let hash = 0;
  for (let i = 0; i < s.length; i++) hash = (hash * 31 + s.charCodeAt(i)) >>> 0;
  return 8 + (hash % 39);
}

function money(n) { return '$' + n.toFixed(2); }

/* Compute fare breakdown for current form state. */
function computeFare() {
  const service = val('serviceType') || 'airport';
  const vehicle = FLEET.find(v => v.id === BOOKING.vehicleId) || FLEET[0];
  const pickup = val('pickup');
  const dropoff = val('dropoff');

  let distance = 0;
  let fare;

  if (service === 'hourly') {
    const hours = parseInt(val('duration') || '2', 10);
    fare = vehicle.base * hours;
    return { service, vehicle, distance: 0, hours, fare: round2(fare), tax: round2(fare * 0.15), total: round2(fare * 1.15) };
  }

  let source = 'estimate';
  if (BOOKING.serverDistance != null) {
    // Authoritative distance from the server (Mapbox or server-side estimate).
    distance = BOOKING.serverDistance;
    source = BOOKING.distanceSource || 'estimate';
  } else {
    distance = estimateDistance(pickup, dropoff);
    if (service === 'intercity' && distance) distance += 40;
  }
  fare = Math.max(vehicle.base, vehicle.base + distance * vehicle.perKm);
  return { service, vehicle, distance, source, hours: 0, fare: round2(fare), tax: round2(fare * 0.15), total: round2(fare * 1.15) };
}

function round2(n) { return Math.round(n * 100) / 100; }
function val(id) { const el = document.getElementById(id); return el ? el.value.trim() : ''; }
function setText(id, text) { const el = document.getElementById(id); if (el) el.textContent = text; }

function updateSummary() {
  if (!document.getElementById('orderSummary')) return;
  const f = computeFare();

  setText('sumService', SERVICE_LABELS[f.service] || 'Airport Transfer');
  setText('sumPickup', val('pickup') || '—');
  setText('sumDropoff', val('dropoff') || '—');

  const date = val('rideDate'), time = val('rideTime');
  if (date && time) {
    const d = new Date(date + 'T' + time);
    if (!isNaN(d)) setText('sumDateTime', d.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }));
  } else {
    setText('sumDateTime', '—');
  }

  const passEl = document.getElementById('passengers');
  setText('sumPassengers', passEl ? passEl.value : '1');
  setText('sumVehicle', BOOKING.vehicleId ? f.vehicle.name : 'Not selected');

  // Distance / duration row
  const distRow = document.getElementById('sumDistanceRow');
  if (distRow) {
    if (f.service === 'hourly') {
      distRow.style.display = '';
      setText('sumDistanceLabel', 'Duration');
      setText('sumDistance', f.hours + ' hours');
    } else if (f.distance) {
      distRow.style.display = '';
      const live = f.source === 'mapbox';
      setText('sumDistanceLabel', live ? 'Distance' : 'Est. distance');
      setText('sumDistance', (live ? '' : '~') + (Math.round(f.distance * 10) / 10) + ' km');
    } else {
      distRow.style.display = 'none';
    }
  }

  setText('sumBase', money(f.fare));
  setText('sumTax', money(f.tax));
  setText('sumTotal', money(f.total));
}

/* Fetch the authoritative quote (real distance + price) from the server and
   refresh the UI, so the displayed price always matches what will be charged.
   Falls back silently to the local estimate if the server is unreachable. */
let _quoteTimer = null;
function scheduleQuote() {
  clearTimeout(_quoteTimer);
  _quoteTimer = setTimeout(refreshQuote, 500);
}

async function refreshQuote() {
  const service = val('serviceType') || 'airport';
  const pickup = val('pickup'), dropoff = val('dropoff');
  if (service === 'hourly' || !pickup || !dropoff) {
    BOOKING.serverDistance = null;
    BOOKING.distanceSource = null;
    updateSummary();
    return;
  }
  try {
    const r = await fetch('/api/quote', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service, vehicleId: BOOKING.vehicleId || 1, pickup, dropoff }),
    });
    if (!r.ok) throw new Error('quote failed');
    const q = await r.json();
    BOOKING.serverDistance = q.distance;
    BOOKING.distanceSource = q.distance_source;
  } catch (e) {
    BOOKING.serverDistance = null;   // fall back to local estimate
    BOOKING.distanceSource = null;
  }
  updateSummary();
  if (BOOKING.step === 2) renderVehicleList();
}

/* ---------- Validation helpers ---------- */
function clearError(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.remove('invalid');
  const grp = el.closest('.form-group');
  const err = grp && grp.querySelector('.field-error');
  if (err) err.remove();
}

function setError(id, msg) {
  const el = document.getElementById(id);
  if (!el) return false;
  el.classList.add('invalid');
  const grp = el.closest('.form-group');
  if (grp && !grp.querySelector('.field-error')) {
    const div = document.createElement('div');
    div.className = 'field-error';
    div.textContent = msg;
    grp.appendChild(div);
  }
  return false;
}

function isEmail(v) { return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(v); }
function isPhone(v) { return v.replace(/[^\d]/g, '').length >= 7; }

function validateStep1() {
  let ok = true;
  ['pickup', 'dropoff', 'rideDate', 'rideTime'].forEach(clearError);

  if (!val('pickup')) { setError('pickup', 'Enter a pick-up location'); ok = false; }
  const hourly = (val('serviceType') === 'hourly');
  if (!hourly && !val('dropoff')) { setError('dropoff', 'Enter a drop-off location'); ok = false; }

  const date = val('rideDate'), time = val('rideTime');
  if (!date) { setError('rideDate', 'Choose a date'); ok = false; }
  if (!time) { setError('rideTime', 'Choose a time'); ok = false; }

  if (date && time) {
    const when = new Date(date + 'T' + time);
    if (when.getTime() < Date.now() + 30 * 60000) { setError('rideTime', 'Pick a time at least 30 min from now'); ok = false; }
  }
  if (!ok) showToast('Please complete the highlighted fields', '⚠');
  return ok;
}

function validateStep2() {
  if (!BOOKING.vehicleId) { showToast('Please select a vehicle to continue', '⚠'); return false; }
  return true;
}

function validateStep3() {
  let ok = true;
  ['firstName', 'lastName', 'email', 'phone'].forEach(clearError);
  if (!val('firstName')) { setError('firstName', 'Required'); ok = false; }
  if (!val('lastName')) { setError('lastName', 'Required'); ok = false; }
  if (!val('email')) { setError('email', 'Required'); ok = false; }
  else if (!isEmail(val('email'))) { setError('email', 'Enter a valid email'); ok = false; }
  if (!val('phone')) { setError('phone', 'Required'); ok = false; }
  else if (!isPhone(val('phone'))) { setError('phone', 'Enter a valid phone number'); ok = false; }
  if (!ok) showToast('Please complete the highlighted fields', '⚠');
  return ok;
}

function validateStep4() {
  // Card details are entered on Stripe's secure page, never on our form,
  // so there is nothing to validate locally for the card path.
  return true;
}

function goToStep(step, force) {
  // Validate forward transitions (skipped when forced, e.g. returning from Stripe)
  if (!force && step > BOOKING.step) {
    if (BOOKING.step === 1 && !validateStep1()) return;
    if (BOOKING.step === 2 && !validateStep2()) return;
    if (BOOKING.step === 3 && !validateStep3()) return;
  }

  for (let i = 1; i <= 5; i++) {
    const el = document.getElementById('step' + i);
    if (el) el.style.display = 'none';
  }
  const target = document.getElementById('step' + step);
  if (target) target.style.display = 'block';

  document.querySelectorAll('.booking-step').forEach(s => {
    const n = parseInt(s.dataset.step, 10);
    s.classList.toggle('active', n === step);
    s.classList.toggle('completed', n < step);
    const dot = s.querySelector('.step-dot');
    if (dot) dot.textContent = n < step ? '✓' : n;
  });

  BOOKING.step = step;
  if (step === 2) renderVehicleList();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function renderVehicleList() {
  const list = document.getElementById('vehicleList');
  if (!list) return;
  const passengers = parseInt((document.getElementById('passengers')?.value || '1'), 10) || 1;
  const f = computeFare();
  list.innerHTML = FLEET.map(v => {
    const fare = f.service === 'hourly'
      ? v.base * (f.hours || 2)
      : Math.max(v.base, v.base + f.distance * v.perKm);
    const tooSmall = v.seats < passengers;
    const selected = BOOKING.vehicleId === v.id;
    return `
    <div class="vehicle-option" onclick="${tooSmall ? '' : `selectVehicle(${v.id})`}"
      style="display:flex;align-items:center;gap:20px;padding:18px;background:var(--dark-3);
             border:1px solid ${selected ? 'var(--gold)' : 'rgba(255,255,255,0.08)'};
             border-radius:var(--radius);cursor:${tooSmall ? 'not-allowed' : 'pointer'};
             opacity:${tooSmall ? '0.45' : '1'};transition:all 0.2s;">
      ${v.image
        ? `<img src="${v.image}" alt="${v.name}" loading="lazy" style="width:72px;height:54px;object-fit:cover;border-radius:6px;flex-shrink:0;" />`
        : `<div style="font-size:2.4rem;flex-shrink:0;">${v.emoji}</div>`}
      <div style="flex:1;min-width:0;">
        <div style="font-weight:600;margin-bottom:3px;">${v.name}</div>
        <div style="font-size:0.78rem;color:var(--gray);">${v.category} · ${v.seats} seats · ${v.luggage} bags${tooSmall ? ' · too small for party' : ''}</div>
      </div>
      <div style="text-align:right;flex-shrink:0;">
        <div style="font-size:1.25rem;font-weight:600;color:var(--gold);">${money(round2(fare * 1.15))}</div>
        <div style="font-size:0.72rem;color:var(--gray);">incl. tax</div>
      </div>
      <div style="width:22px;height:22px;border-radius:50%;border:2px solid ${selected ? 'var(--gold)' : 'var(--gray-dark)'};
                  background:${selected ? 'var(--gold)' : 'transparent'};flex-shrink:0;
                  display:flex;align-items:center;justify-content:center;font-size:0.7rem;color:var(--black);">${selected ? '✓' : ''}</div>
    </div>`;
  }).join('');
}

function selectVehicle(id) {
  BOOKING.vehicleId = id;
  renderVehicleList();
  updateSummary();
}

function setPayMethod(method) {
  BOOKING.payMethod = method;
  ['card', 'paypal', 'apple', 'invoice'].forEach(m => {
    const btn = document.getElementById('pay' + m.charAt(0).toUpperCase() + m.slice(1));
    if (btn) {
      btn.style.borderColor = m === method ? 'var(--gold)' : '';
      btn.style.color = m === method ? 'var(--gold)' : '';
    }
  });
  const cardForm = document.getElementById('cardForm');
  const altForm = document.getElementById('altPayForm');
  if (cardForm) cardForm.style.display = method === 'card' ? 'block' : 'none';
  if (altForm) altForm.style.display = method === 'card' ? 'none' : 'block';
  const altLabel = document.getElementById('altPayLabel');
  if (altLabel) altLabel.textContent = { paypal: 'PayPal', apple: 'Apple Pay', invoice: 'invoice (net 14 days)' }[method] || '';
}

/* ---------- Persistence ---------- */
function getBookings() {
  try { return JSON.parse(localStorage.getItem(LS_BOOKINGS) || '[]'); } catch (e) { return []; }
}
function saveBookings(arr) {
  try { localStorage.setItem(LS_BOOKINGS, JSON.stringify(arr)); } catch (e) {}
}

function buildBooking() {
  const f = computeFare();
  const date = val('rideDate'), time = val('rideTime');
  return {
    ref: '#LX-' + Math.random().toString(36).substring(2, 8).toUpperCase(),
    service: SERVICE_LABELS[f.service] || 'Airport Transfer',
    serviceKey: f.service,
    pickup: val('pickup') || 'Not specified',
    dropoff: val('dropoff') || 'Not specified',
    date, time,
    dateISO: (date && time) ? date + 'T' + time : '',
    passengers: document.getElementById('passengers')?.value || '1',
    vehicleId: f.vehicle.id,
    vehicle: f.vehicle.name,
    vehicleEmoji: f.vehicle.emoji,
    distance: f.distance,
    hours: f.hours,
    total: f.total,
    payMethod: BOOKING.payMethod,
    passenger: (val('firstName') + ' ' + val('lastName')).trim(),
    email: val('email'),
    phone: val('phone'),
    status: 'upcoming',
    createdAt: Date.now(),
  };
}

/* Persist booking + show the confirmation screen. */
function finalizeBooking(booking) {
  const all = getBookings();
  if (!all.some(b => b.ref === booking.ref)) {
    all.unshift(booking);
    saveBookings(all);
  }

  // Push to the shared server pool so drivers can see & accept it.
  try {
    fetch('/api/bookings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(Object.assign({}, booking, { status: 'available' })),
    }).catch(() => {});
  } catch (e) { /* offline / file:// — ignore */ }
  setText('bookingRef', booking.ref);
  setText('confService', booking.service);
  setText('confPickup', booking.pickup);
  setText('confDropoff', booking.dropoff);
  setText('confVehicle', booking.vehicle);
  setText('confTotal', money(booking.total));

  const stepsBar = document.getElementById('bookingSteps');
  if (stepsBar) stepsBar.style.opacity = '0.4';
  const summary = document.getElementById('orderSummary');
  if (summary) summary.style.display = 'none';

  goToStep(5, true);
}

/* Create a Stripe Checkout Session on the server and redirect to it. */
async function startCheckout(booking) {
  const btn = document.getElementById('payBtn');
  const original = btn ? btn.innerHTML : '';
  if (btn) { btn.disabled = true; btn.innerHTML = 'Redirecting to secure checkout…'; }
  try {
    const resp = await fetch('/api/create-checkout-session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        service: booking.serviceKey,
        vehicleId: booking.vehicleId,
        pickup: booking.pickup,
        dropoff: booking.dropoff,
        hours: booking.hours,
        ref: booking.ref,
        email: booking.email,
      }),
    });
    if (!resp.ok) throw new Error('checkout session failed');
    const data = await resp.json();
    if (typeof data.total === 'number') booking.total = data.total; // server is source of truth
    sessionStorage.setItem('luxlane_pending', JSON.stringify(booking));
    window.location.href = data.url;
  } catch (e) {
    // No payment server (e.g. page opened directly from disk) -> demo fallback.
    if (btn) { btn.disabled = false; btn.innerHTML = original; }
    showToast('Payment server offline — finalizing in demo mode.', 'ℹ');
    finalizeBooking(booking);
    showToast('Booking ' + booking.ref + ' confirmed! Saved to My Trips.', '🎉');
  }
}

function confirmBooking() {
  if (!validateStep4()) return;
  const booking = buildBooking();
  if (BOOKING.payMethod === 'card') {
    startCheckout(booking);
    return;
  }
  // PayPal / invoice -> demo confirmation (would have their own flows in production)
  finalizeBooking(booking);
  showToast('Booking ' + booking.ref + ' confirmed! Saved to My Trips.', '🎉');
}

/* Handle the redirect back from Stripe (or the mock checkout). */
async function handleCheckoutReturn() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('canceled') === '1') {
    showToast('Payment canceled — you have not been charged.', '⚠');
    history.replaceState({}, '', 'booking.html');
    return false;
  }
  if (params.get('paid') !== '1') return false;

  const pending = JSON.parse(sessionStorage.getItem('luxlane_pending') || 'null');
  const sid = params.get('session_id');
  let paid = true;
  if (sid) {
    try {
      const r = await fetch('/api/checkout-status?session_id=' + encodeURIComponent(sid));
      const s = await r.json();
      paid = (s.payment_status === 'paid');
    } catch (e) { /* keep optimistic if status check unavailable */ }
  }
  if (pending && paid) {
    finalizeBooking(pending);
    sessionStorage.removeItem('luxlane_pending');
    showToast('Payment received — booking ' + pending.ref + ' confirmed!', '🎉');
    history.replaceState({}, '', 'booking.html');
    return true;
  }
  return false;
}

async function initBookingPage() {
  if (!document.getElementById('bookingSteps')) return;

  // If we're returning from Stripe checkout, finalize and stop.
  if (await handleCheckoutReturn()) return;

  // Default date = tomorrow, time = 09:00
  const dateEl = document.getElementById('rideDate');
  if (dateEl) {
    const t = new Date(); t.setDate(t.getDate() + 1);
    dateEl.value = t.toISOString().split('T')[0];
    dateEl.min = new Date().toISOString().split('T')[0];
  }
  const timeEl = document.getElementById('rideTime');
  if (timeEl && !timeEl.value) timeEl.value = '09:00';

  // Service-type change toggles duration field + clears vehicle
  const serviceEl = document.getElementById('serviceType');
  const durationGroup = document.getElementById('durationGroup');
  function syncService() {
    const isHourly = serviceEl && serviceEl.value === 'hourly';
    if (durationGroup) durationGroup.style.display = isHourly ? '' : 'none';
    const dropGroup = document.getElementById('dropoffGroup');
    if (dropGroup) dropGroup.style.opacity = isHourly ? '0.5' : '1';
    updateSummary();
  }
  serviceEl && serviceEl.addEventListener('change', syncService);

  // Live updates + clear errors on input
  ['pickup', 'dropoff', 'rideDate', 'rideTime', 'passengers', 'serviceType', 'duration'].forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    const ev = (el.tagName === 'SELECT') ? 'change' : 'input';
    el.addEventListener(ev, () => {
      clearError(id);
      updateSummary();
      if (id === 'pickup' || id === 'dropoff' || id === 'serviceType') scheduleQuote();
    });
  });
  ['firstName', 'lastName', 'email', 'phone', 'cardNumber', 'cardExpiry', 'cardCvc', 'cardName'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', () => clearError(id));
  });

  // Prefill from hero / sessionStorage
  try {
    const pre = JSON.parse(sessionStorage.getItem('luxlane_prefill') || 'null');
    if (pre) {
      if (pre.pickup && document.getElementById('pickup')) document.getElementById('pickup').value = pre.pickup;
      if (pre.dropoff && document.getElementById('dropoff')) document.getElementById('dropoff').value = pre.dropoff;
      if (pre.service && serviceEl) serviceEl.value = pre.service;
      if (pre.datetime) {
        const [d, t] = pre.datetime.split('T');
        if (d && dateEl) dateEl.value = d;
        if (t && timeEl) timeEl.value = t.substring(0, 5);
      }
      sessionStorage.removeItem('luxlane_prefill');
    }
  } catch (e) {}

  // Preselect vehicle from ?vehicle=ID
  const params = new URLSearchParams(window.location.search);
  const vid = parseInt(params.get('vehicle'), 10);
  if (vid && FLEET.some(v => v.id === vid)) BOOKING.vehicleId = vid;

  syncService();
  updateSummary();
  refreshQuote();   // fetch a live quote for any prefilled / preselected route
}

/* =====================================================
   TRIPS PAGE
   ===================================================== */
function deriveStatus(b) {
  if (b.status === 'cancelled') return 'cancelled';
  if (b.dateISO) {
    const when = new Date(b.dateISO);
    if (!isNaN(when) && when.getTime() < Date.now()) return 'completed';
  }
  return 'upcoming';
}

function renderTrips() {
  const wrap = document.getElementById('tripsList');
  if (!wrap) return;
  const bookings = getBookings();

  const countEl = document.getElementById('tripsCount');
  if (countEl) countEl.textContent = bookings.length + (bookings.length === 1 ? ' trip' : ' trips');

  if (!bookings.length) {
    wrap.innerHTML = `
      <div class="trips-empty">
        <div class="icon">🧳</div>
        <h3>No trips yet</h3>
        <p>Your booked rides will appear here. Ready to go somewhere?</p>
        <a href="booking.html" class="btn btn-primary btn-lg">Book Your First Ride</a>
      </div>`;
    return;
  }

  wrap.innerHTML = bookings.map(b => {
    const status = deriveStatus(b);
    const when = b.dateISO ? new Date(b.dateISO) : null;
    const whenStr = (when && !isNaN(when)) ? when.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' }) : 'Date not set';
    return `
      <div class="trip-card">
        <div class="trip-head">
          <div class="trip-ref">Booking reference<strong>${b.ref}</strong></div>
          <span class="trip-status ${status}">${status}</span>
        </div>
        <div class="trip-route">
          <span class="trip-route-icon">📍</span>
          <div class="loc"><span class="loc-label">Pick-up</span>${b.pickup}</div>
          <span class="trip-route-icon">🏁</span>
          <div class="loc"><span class="loc-label">Drop-off</span>${b.dropoff}</div>
        </div>
        <div class="trip-meta">
          <div class="trip-meta-item"><span class="label">When</span><span class="value">${whenStr}</span></div>
          <div class="trip-meta-item"><span class="label">Service</span><span class="value">${b.service}</span></div>
          <div class="trip-meta-item"><span class="label">Vehicle</span><span class="value">${b.vehicleEmoji || '🚗'} ${b.vehicle}</span></div>
          <div class="trip-meta-item"><span class="label">Passengers</span><span class="value">${b.passengers}</span></div>
          <div class="trip-meta-item"><span class="label">Total</span><span class="value gold">${money(b.total)}</span></div>
        </div>
        <div class="trip-actions">
          ${status === 'upcoming' ? `<a class="btn btn-primary btn-sm" href="track.html?ref=${encodeURIComponent((b.ref || '').replace('#', ''))}">📍 Track Ride</a>` : ''}
          ${status === 'upcoming' ? `<button class="btn btn-outline btn-sm" onclick="cancelTrip('${b.ref}')">Cancel Ride</button>` : ''}
          <a href="booking.html" class="btn btn-dark btn-sm">Book Similar</a>
        </div>
      </div>`;
  }).join('');
}

function cancelTrip(ref) {
  const all = getBookings();
  const b = all.find(x => x.ref === ref);
  if (b) { b.status = 'cancelled'; saveBookings(all); renderTrips(); showToast('Ride ' + ref + ' cancelled.', '✓'); }
}

/* =====================================================
   AUTH (mock) + nav injection
   ===================================================== */
function getUser() {
  try { return JSON.parse(localStorage.getItem(LS_USER) || 'null'); } catch (e) { return null; }
}
function setUser(u) { try { localStorage.setItem(LS_USER, JSON.stringify(u)); } catch (e) {} }
function clearUser() { try { localStorage.removeItem(LS_USER); } catch (e) {} }

function injectAuthUI() {
  const actions = document.querySelector('.navbar-actions');
  const nav = document.querySelector('.navbar-nav');
  if (!actions) return;

  // Add "My Trips" to nav if missing
  if (nav && !nav.querySelector('[data-trips]')) {
    const page = window.location.pathname.split('/').pop() || 'index.html';
    const li = document.createElement('li');
    li.innerHTML = `<a href="trips.html" data-trips class="${page === 'trips.html' ? 'active' : ''}">My Trips</a>`;
    const bookLi = Array.from(nav.querySelectorAll('li')).find(l => l.querySelector('a[href="booking.html"]'));
    if (bookLi) bookLi.after(li); else nav.appendChild(li);
  }

  renderAuthButton();

  // Mobile menu trips link
  const mm = document.getElementById('mobileMenu');
  if (mm && !mm.querySelector('[data-trips]')) {
    const a = document.createElement('a');
    a.href = 'trips.html'; a.textContent = 'My Trips'; a.setAttribute('data-trips', '');
    const bookA = mm.querySelector('a[href="booking.html"]');
    if (bookA) bookA.after(a); else mm.appendChild(a);
  }
}

function renderAuthButton() {
  const actions = document.querySelector('.navbar-actions');
  if (!actions) return;
  const user = getUser();

  // Remove existing injected auth elements
  actions.querySelectorAll('[data-auth]').forEach(el => el.remove());

  if (user) {
    const initials = user.name.split(' ').map(p => p[0]).slice(0, 2).join('').toUpperCase();
    const wrap = document.createElement('div');
    wrap.setAttribute('data-auth', '');
    wrap.style.position = 'relative';
    wrap.innerHTML = `
      <div class="nav-user" id="navUser">
        <div class="nav-user-avatar">${initials}</div>
        <span class="nav-user-name">${user.name.split(' ')[0]}</span>
        <span style="font-size:0.6rem;color:var(--gray);">▼</span>
      </div>
      <div class="nav-dropdown" id="navDropdown">
        <a href="trips.html">🧳 My Trips</a>
        <a href="booking.html">➕ New Booking</a>
        <div class="divider"></div>
        <button id="signOutBtn">↩ Sign Out</button>
      </div>`;
    // Insert before the "Book a Ride" button
    const bookBtn = actions.querySelector('a.btn-primary');
    if (bookBtn) actions.insertBefore(wrap, bookBtn); else actions.appendChild(wrap);

    const navUser = wrap.querySelector('#navUser');
    const dropdown = wrap.querySelector('#navDropdown');
    navUser.addEventListener('click', (e) => { e.stopPropagation(); dropdown.classList.toggle('open'); });
    document.addEventListener('click', () => dropdown.classList.remove('open'));
    wrap.querySelector('#signOutBtn').addEventListener('click', () => {
      const u = getUser();
      if (u && u.token) {
        fetch('/api/auth/logout', { method: 'POST', headers: { Authorization: 'Bearer ' + u.token } }).catch(() => {});
      }
      clearUser(); renderAuthButton(); showToast('Signed out.', '✓');
    });
  } else {
    const btn = document.createElement('button');
    btn.setAttribute('data-auth', '');
    btn.className = 'btn btn-outline btn-sm';
    btn.textContent = 'Sign In';
    btn.addEventListener('click', () => openAuthModal('signin'));
    const bookBtn = actions.querySelector('a.btn-primary');
    if (bookBtn) actions.insertBefore(btn, bookBtn); else actions.appendChild(btn);
  }
}

function buildAuthModal() {
  if (document.getElementById('authModal')) return;
  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.id = 'authModal';
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true">
      <span class="modal-close" id="authClose">✕</span>
      <div class="modal-logo">L</div>
      <h2 id="authTitle">Welcome back</h2>
      <p class="modal-sub" id="authSub">Sign in to manage your trips</p>
      <form id="authForm">
        <div class="form-group" id="nameGroup" style="display:none;">
          <label class="form-label">Full Name</label>
          <input class="form-control" type="text" id="authName" placeholder="John Smith" />
        </div>
        <div class="form-group">
          <label class="form-label">Email</label>
          <input class="form-control" type="email" id="authEmail" placeholder="you@email.com" />
        </div>
        <div class="form-group">
          <label class="form-label">Password</label>
          <input class="form-control" type="password" id="authPass" placeholder="••••••••" />
        </div>
        <button type="submit" class="btn btn-primary" style="width:100%;justify-content:center;margin-top:8px;" id="authSubmit">Sign In</button>
      </form>
      <p class="modal-switch" id="authSwitch">New to Luxlane? <a id="authToggle">Create an account</a></p>
    </div>`;
  document.body.appendChild(overlay);

  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeAuthModal(); });
  overlay.querySelector('#authClose').addEventListener('click', closeAuthModal);
  overlay.querySelector('#authToggle').addEventListener('click', () => {
    openAuthModal(overlay.dataset.mode === 'signin' ? 'signup' : 'signin');
  });
  overlay.querySelector('#authForm').addEventListener('submit', handleAuthSubmit);
}

function openAuthModal(mode) {
  buildAuthModal();
  const overlay = document.getElementById('authModal');
  overlay.dataset.mode = mode;
  const signup = mode === 'signup';
  document.getElementById('authTitle').textContent = signup ? 'Create account' : 'Welcome back';
  document.getElementById('authSub').textContent = signup ? 'Join Luxlane for seamless travel' : 'Sign in to manage your trips';
  document.getElementById('nameGroup').style.display = signup ? '' : 'none';
  document.getElementById('authSubmit').textContent = signup ? 'Create Account' : 'Sign In';
  document.getElementById('authSwitch').innerHTML = signup
    ? `Already have an account? <a id="authToggle">Sign in</a>`
    : `New to Luxlane? <a id="authToggle">Create an account</a>`;
  document.getElementById('authToggle').addEventListener('click', () => openAuthModal(signup ? 'signin' : 'signup'));
  overlay.classList.add('open');
  setTimeout(() => document.getElementById(signup ? 'authName' : 'authEmail')?.focus(), 100);
}

function closeAuthModal() {
  const overlay = document.getElementById('authModal');
  if (overlay) overlay.classList.remove('open');
}

async function handleAuthSubmit(e) {
  e.preventDefault();
  const overlay = document.getElementById('authModal');
  const signup = overlay.dataset.mode === 'signup';
  const email = document.getElementById('authEmail').value.trim();
  const pass = document.getElementById('authPass').value;
  const name = document.getElementById('authName').value.trim();

  if (!isEmail(email)) { showToast('Enter a valid email', '⚠'); return; }
  if (pass.length < 6) { showToast('Password must be at least 6 characters', '⚠'); return; }
  if (signup && !name) { showToast('Enter your name', '⚠'); return; }

  const submitBtn = document.getElementById('authSubmit');
  const original = submitBtn ? submitBtn.textContent : '';
  if (submitBtn) { submitBtn.disabled = true; submitBtn.textContent = 'Please wait…'; }

  try {
    const endpoint = signup ? '/api/auth/register' : '/api/auth/login';
    const res = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password: pass, role: 'customer' }),
    });
    const data = await res.json();
    if (!res.ok) { throw new Error(data.error || 'Something went wrong.'); }
    setUser({ token: data.token, name: data.user.name, email: data.user.email, role: data.user.role });
    closeAuthModal();
    renderAuthButton();
    showToast((signup ? 'Welcome to Luxlane, ' : 'Welcome back, ') + data.user.name.split(' ')[0] + '!', '👋');
  } catch (err) {
    showToast(err.message || 'Sign-in failed. Is the server running?', '⚠');
  } finally {
    if (submitBtn) { submitBtn.disabled = false; submitBtn.textContent = original; }
  }
}

/* Validate the stored session on load; refresh the display name or sign out. */
async function validateSession() {
  const u = getUser();
  if (!u || !u.token) return;
  try {
    const res = await fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + u.token } });
    if (res.ok) {
      const data = await res.json();
      setUser({ token: u.token, name: data.user.name, email: data.user.email, role: data.user.role });
      renderAuthButton();
    } else if (res.status === 401) {
      clearUser(); renderAuthButton();
    }
  } catch (e) { /* server unreachable — keep showing cached user */ }
}

/* =====================================================
   INIT
   ===================================================== */
document.addEventListener('DOMContentLoaded', () => {
  initChrome();
  injectAuthUI();
  validateSession();
  initHomeFleet();
  initFleetPage();
  initBookingPage();
  renderTrips();
});

// Expose handlers used by inline onclick/onsubmit
window.handleHeroBook = handleHeroBook;
window.goToStep = goToStep;
window.selectVehicle = selectVehicle;
window.setPayMethod = setPayMethod;
window.confirmBooking = confirmBooking;
window.updateSummary = updateSummary;
window.cancelTrip = cancelTrip;
window.openAuthModal = openAuthModal;
