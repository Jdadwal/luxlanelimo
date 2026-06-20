/* ===========================
   LUXLANE DRIVER — APP LOGIC
   =========================== */
'use strict';

const LS_DRIVER = 'luxlane_driver';
const POLL_MS = 5000;

const state = {
  driver: null,      // { id, name }
  online: false,
  view: 'rides',
  available: [],     // unassigned pool
  mine: [],          // rides assigned to this driver
  pollTimer: null,
};

/* ---------- helpers ---------- */
const $ = (id) => document.getElementById(id);
function money(n) { return '$' + Number(n || 0).toFixed(2); }
function api(path, opts) {
  return fetch(path, Object.assign({ headers: { 'Content-Type': 'application/json' } }, opts))
    .then(r => r.json());
}
function whenStr(iso) {
  if (!iso) return 'Time TBD';
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function mapsLink(addr) {
  return 'https://www.google.com/maps/dir/?api=1&destination=' + encodeURIComponent(addr || '');
}
function toast(msg, icon) {
  document.querySelectorAll('.toast').forEach(t => t.remove());
  const t = document.createElement('div');
  t.className = 'toast';
  t.innerHTML = '<span class="toast-icon">' + (icon || '✓') + '</span><span>' + msg + '</span>';
  document.body.appendChild(t);
  setTimeout(() => { t.classList.add('hide'); setTimeout(() => t.remove(), 300); }, 3200);
}

/* ---------- auth ---------- */
function loadDriver() {
  try { state.driver = JSON.parse(localStorage.getItem(LS_DRIVER) || 'null'); } catch (e) {}
}
function showLogin(show) {
  $('login').classList.toggle('hidden', !show);
}

let authMode = 'signin'; // 'signin' | 'signup'
function setAuthMode(mode) {
  authMode = mode;
  const signup = mode === 'signup';
  $('driverNameGroup').style.display = signup ? '' : 'none';
  $('driverAuthSub').textContent = signup ? 'Create your driver account' : 'Sign in to start accepting rides';
  $('driverAuthSubmit').textContent = signup ? 'Create Account' : 'Sign In';
  $('driverAuthSwitch').innerHTML = signup
    ? 'Already registered? <a id="driverAuthToggle" style="color:var(--gold);font-weight:600;cursor:pointer;">Sign in</a>'
    : 'New driver? <a id="driverAuthToggle" style="color:var(--gold);font-weight:600;cursor:pointer;">Create an account</a>';
  $('driverAuthToggle').addEventListener('click', () => setAuthMode(signup ? 'signin' : 'signup'));
}
$('driverAuthToggle').addEventListener('click', () => setAuthMode('signup'));

$('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const signup = authMode === 'signup';
  const name = $('driverName').value.trim();
  const email = $('driverEmail').value.trim();
  const password = $('driverPassword').value;
  if (signup && !name) { toast('Enter your name', '⚠'); return; }
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) { toast('Enter a valid email', '⚠'); return; }
  if (password.length < 6) { toast('Password must be at least 6 characters', '⚠'); return; }

  const btn = $('driverAuthSubmit');
  btn.disabled = true; btn.textContent = 'Please wait…';
  try {
    const res = await api(signup ? '/api/auth/register' : '/api/auth/login',
      { method: 'POST', body: JSON.stringify({ name, email, password, role: 'driver' }) });
    if (res.error) { toast(res.error, '⚠'); return; }
    state.driver = { id: res.user.id, name: res.user.name, email: res.user.email, token: res.token };
    localStorage.setItem(LS_DRIVER, JSON.stringify(state.driver));
    showLogin(false);
    initSession();
    toast((signup ? 'Welcome, ' : 'Welcome back, ') + res.user.name.split(' ')[0] + '!', '👋');
  } catch (err) {
    toast('Could not reach the server.', '⚠');
  } finally {
    btn.disabled = false;
    setAuthMode(authMode); // reset button label
  }
});

$('logoutBtn').addEventListener('click', () => {
  if (state.driver && state.driver.token) {
    api('/api/auth/logout', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + state.driver.token } }).catch(() => {});
  }
  setOnline(false);
  localStorage.removeItem(LS_DRIVER);
  state.driver = null;
  showLogin(true);
});

async function validateDriverSession() {
  if (!state.driver || !state.driver.token) return;
  try {
    const res = await fetch('/api/auth/me', { headers: { Authorization: 'Bearer ' + state.driver.token } });
    if (res.status === 401) {
      localStorage.removeItem(LS_DRIVER); state.driver = null; showLogin(true);
    }
  } catch (e) { /* server unreachable — keep cached session */ }
}

/* ---------- online toggle ---------- */
function setOnline(on) {
  state.online = on;
  $('onlineSwitch').classList.toggle('on', on);
  $('onlineSwitch').setAttribute('aria-checked', on ? 'true' : 'false');
  $('onlineLabel').textContent = on ? 'Online' : 'Offline';
  $('onlineLabel').classList.toggle('on', on);
  const banner = $('statusBanner');
  banner.classList.toggle('online', on);
  banner.textContent = on
    ? '🟢 You\'re online — new ride requests will appear below.'
    : 'You\'re offline. Go online to receive ride requests.';
  if (on) { refresh(); startPolling(); } else { stopPolling(); renderRides(); }
}
$('onlineSwitch').addEventListener('click', () => setOnline(!state.online));

/* ---------- tabs ---------- */
$('tabbar').addEventListener('click', (e) => {
  const tab = e.target.closest('.tab');
  if (!tab) return;
  switchView(tab.dataset.view);
});
function switchView(view) {
  state.view = view;
  document.querySelectorAll('.tabbar .tab').forEach(t => t.classList.toggle('active', t.dataset.view === view));
  document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + view));
  if (view === 'earn') renderEarnings();
}

/* ---------- data ---------- */
async function refresh() {
  if (!state.driver) return;
  try {
    const [pool, mine] = await Promise.all([
      api('/api/rides?status=available'),
      api('/api/rides?driver=' + encodeURIComponent(state.driver.id)),
    ]);
    state.available = pool.rides || [];
    state.mine = mine.rides || [];
    renderRides();
    renderActive();
    updateBadges();
    if (state.view === 'earn') renderEarnings();
  } catch (e) { /* offline-friendly */ }
}
function startPolling() {
  stopPolling();
  state.pollTimer = setInterval(() => { if (state.online) refresh(); }, POLL_MS);
}
function stopPolling() { if (state.pollTimer) clearInterval(state.pollTimer); state.pollTimer = null; }

/* ---------- actions ---------- */
async function acceptRide(ref) {
  const res = await api('/api/rides/accept', {
    method: 'POST',
    body: JSON.stringify({ ref, driverId: state.driver.id, driverName: state.driver.name }),
  });
  if (res.error) { toast(res.error, '⚠'); refresh(); return; }
  toast('Ride ' + ref + ' accepted!', '🚘');
  await refresh();
  switchView('active');
}
async function advanceRide(ref, status, label) {
  const res = await api('/api/rides/status', {
    method: 'POST',
    body: JSON.stringify({ ref, driverId: state.driver.id, status }),
  });
  if (res.error) { toast(res.error, '⚠'); return; }
  toast(label, status === 'completed' ? '💰' : '✓');
  await refresh();
  if (status === 'completed') switchView('earn');
}
window.acceptRide = acceptRide;
window.advanceRide = advanceRide;

/* ---------- rendering ---------- */
function routeBlock(b) {
  return (
    '<div class="ride-route">' +
      '<div class="dot"><span class="pin">📍</span><span class="line"></span><span class="pin">🏁</span></div>' +
      '<div>' +
        '<div class="addr"><small>Pick-up</small>' + (b.pickup || '—') + '</div>' +
        '<div class="addr"><small>Drop-off</small>' + (b.dropoff || '—') + '</div>' +
      '</div>' +
    '</div>'
  );
}

function renderRides() {
  const list = $('ridesList');
  $('ridesSub').textContent = state.online
    ? (state.available.length + ' ride' + (state.available.length === 1 ? '' : 's') + ' available now')
    : 'Go online to see ride requests.';

  if (!state.online) {
    list.innerHTML = '<div class="empty"><div class="ic">😴</div><p>You\'re offline.<br/>Flip the switch up top to start earning.</p></div>';
    return;
  }
  if (!state.available.length) {
    list.innerHTML = '<div class="empty"><div class="ic">🔎</div><p>No rides available right now.<br/>New requests will appear automatically.</p></div>';
    return;
  }
  list.innerHTML = state.available.map(b =>
    '<div class="ride-card">' +
      '<div class="ride-top">' +
        '<div><div class="ride-when">' + whenStr(b.dateISO) + '</div><div class="ride-service">' + (b.vehicleEmoji || '🚗') + ' ' + (b.service || 'Ride') + ' · ' + (b.vehicle || '') + '</div></div>' +
        '<div class="ride-earn"><div class="amt">' + money(b.driverEarn) + '</div><div class="lbl">you earn</div></div>' +
      '</div>' +
      routeBlock(b) +
      '<div class="ride-meta">' +
        '<span>👤 <b>' + (b.passengers || 1) + '</b></span>' +
        (b.distance ? '<span>📏 <b>~' + b.distance + ' km</b></span>' : '') +
        '<span>💵 fare <b>' + money(b.total) + '</b></span>' +
      '</div>' +
      '<div class="ride-actions">' +
        '<button class="btn btn-primary" onclick="acceptRide(\'' + b.ref + '\')">Accept Ride</button>' +
      '</div>' +
    '</div>'
  ).join('');
}

const FLOW = {
  assigned: { next: 'arrived', label: "I've Arrived", done: 1 },
  arrived: { next: 'on_trip', label: 'Start Trip', done: 2 },
  on_trip: { next: 'completed', label: 'Complete Trip', done: 3 },
};

function renderActive() {
  const list = $('activeList');
  const active = state.mine.filter(b => b.status !== 'completed' && b.status !== 'cancelled');
  if (!active.length) {
    list.innerHTML = '<div class="empty"><div class="ic">🚘</div><p>No active rides yet.<br/>Accept one from the Rides tab.</p></div>';
    return;
  }
  list.innerHTML = active.map(b => {
    const step = FLOW[b.status] || FLOW.assigned;
    const navAddr = b.status === 'on_trip' ? b.dropoff : b.pickup;
    return (
      '<div class="ride-card">' +
        '<div class="ride-top">' +
          '<div><div class="ride-when">' + whenStr(b.dateISO) + '</div><div class="ride-service">#' + b.ref + ' · ' + (b.vehicle || '') + '</div></div>' +
          '<span class="ride-pill ' + b.status + '">' + b.status.replace('_', ' ') + '</span>' +
        '</div>' +
        '<div class="stepper">' +
          '<div class="seg ' + (step.done >= 1 ? 'done' : '') + '"></div>' +
          '<div class="seg ' + (step.done >= 2 ? 'done' : '') + '"></div>' +
          '<div class="seg ' + (step.done >= 3 ? 'done' : '') + '"></div>' +
        '</div>' +
        routeBlock(b) +
        '<div class="ride-meta">' +
          '<span>👤 ' + (b.passenger || 'Guest') + '</span>' +
          (b.phone ? '<span>📞 ' + b.phone + '</span>' : '') +
          '<span>💰 <b>' + money(b.driverEarn) + '</b></span>' +
        '</div>' +
        '<div class="ride-actions">' +
          '<a class="btn btn-dark" href="' + mapsLink(navAddr) + '" target="_blank" rel="noopener">🧭 Navigate</a>' +
          '<button class="btn btn-primary" onclick="advanceRide(\'' + b.ref + '\',\'' + step.next + '\',\'' + step.label + ' ✓\')">' + step.label + '</button>' +
        '</div>' +
      '</div>'
    );
  }).join('');
}

function renderEarnings() {
  const done = state.mine.filter(b => b.status === 'completed');
  const total = done.reduce((s, b) => s + Number(b.driverEarn || 0), 0);
  $('earnTotal').textContent = money(total);
  $('earnTrips').textContent = done.length;
  $('earnAvg').textContent = done.length ? money(total / done.length) : '$0';
  const list = $('earnList');
  if (!done.length) {
    list.innerHTML = '<div class="empty"><div class="ic">💰</div><p>No completed trips yet.<br/>Your payouts will show here.</p></div>';
    return;
  }
  list.innerHTML = done.map(b =>
    '<div class="ride-card" style="padding:14px 16px;">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;">' +
        '<div><div style="font-size:0.85rem;font-weight:600;">' + (b.pickup || '') + ' → ' + (b.dropoff || '') + '</div>' +
        '<div style="font-size:0.72rem;color:var(--gray);margin-top:2px;">#' + b.ref + ' · ' + whenStr(b.dateISO) + '</div></div>' +
        '<div style="color:#6ec878;font-weight:600;">' + money(b.driverEarn) + '</div>' +
      '</div>' +
    '</div>'
  ).join('');
}

function updateBadges() {
  const avail = state.online ? state.available.length : 0;
  const active = state.mine.filter(b => b.status !== 'completed' && b.status !== 'cancelled').length;
  const rb = $('ridesBadge'), ab = $('activeBadge');
  rb.style.display = avail ? 'flex' : 'none'; rb.textContent = avail;
  ab.style.display = active ? 'flex' : 'none'; ab.textContent = active;
}

/* ---------- live location streaming (best-effort GPS) ----------
   Pushes the driver's real position for any active ride, but only if the
   browser already granted geolocation (no disruptive permission prompts).
   When no GPS is streamed, the server synthesizes progress from elapsed time,
   so customer tracking works either way. */
function pushLocation(coords) {
  const active = state.mine.filter(b => b.status === 'assigned' || b.status === 'arrived' || b.status === 'on_trip');
  active.forEach(b => {
    api('/api/rides/location', {
      method: 'POST',
      body: JSON.stringify({
        ref: b.ref, driverId: state.driver.id,
        lat: coords.latitude, lon: coords.longitude,
        leg: b.status === 'on_trip' ? 'trip' : 'approach',
      }),
    }).catch(() => {});
  });
}

function startLocationStream() {
  if (!('geolocation' in navigator) || !('permissions' in navigator)) return;
  navigator.permissions.query({ name: 'geolocation' }).then(p => {
    if (p.state !== 'granted') return; // don't prompt; server synthesis covers the demo
    navigator.geolocation.watchPosition(
      (pos) => pushLocation(pos.coords),
      () => {},
      { enableHighAccuracy: true, maximumAge: 5000 }
    );
  }).catch(() => {});
}

/* ---------- session ---------- */
function initSession() {
  $('profName').textContent = state.driver.name;
  $('profId').textContent = 'ID: ' + state.driver.id;
  $('profAvatar').textContent = state.driver.name.trim().charAt(0).toUpperCase() || 'D';
  refresh();
  startLocationStream();
}

function boot() {
  loadDriver();
  if (state.driver && state.driver.token) { showLogin(false); initSession(); validateDriverSession(); }
  else { showLogin(true); }
}
boot();

/* ---------- PWA service worker ---------- */
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  });
}
