/* ===========================
   LUXLANE — ADMIN DASHBOARD
   View & manage all bookings.
   =========================== */
'use strict';

const LS_ADMIN = 'luxlane_admin_token';
let TOKEN = null;
let DATA = { bookings: [], stats: {}, drivers: [] };
let FILTER = 'all';
let SEARCH = '';
let pollTimer = null;

const $ = (id) => document.getElementById(id);
const money = (n) => '$' + Number(n || 0).toFixed(2);

function authHeaders() { return { 'Content-Type': 'application/json', Authorization: 'Bearer ' + TOKEN }; }
function whenStr(iso) {
  if (!iso) return 'Time TBD';
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function esc(s) { return (s || '').toString().replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }

const STATUSES = ['available', 'assigned', 'arrived', 'on_trip', 'completed', 'cancelled'];
const STATUS_LABEL = { available: 'Unassigned', assigned: 'Assigned', arrived: 'Arrived', on_trip: 'On trip', completed: 'Completed', cancelled: 'Cancelled' };

/* ---------- auth ---------- */
function showApp(show) {
  $('adminApp').style.display = show ? '' : 'none';
  $('adminLogin').style.display = show ? 'none' : 'flex';
}

$('adminLoginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const password = $('adminPassword').value;
  try {
    const res = await fetch('/api/admin/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ password }) });
    const data = await res.json();
    if (!res.ok) { alert(data.error || 'Login failed'); return; }
    TOKEN = data.token;
    try { localStorage.setItem(LS_ADMIN, TOKEN); } catch (e) {}
    showApp(true); load(); startPolling();
  } catch (err) { alert('Could not reach the server.'); }
});

$('adminLogout').addEventListener('click', () => {
  TOKEN = null; try { localStorage.removeItem(LS_ADMIN); } catch (e) {}
  stopPolling(); showApp(false);
});
$('adminRefresh').addEventListener('click', load);
$('adminSearch').addEventListener('input', (e) => { SEARCH = e.target.value.toLowerCase(); render(); });

/* ---------- data ---------- */
async function load() {
  try {
    const res = await fetch('/api/admin/bookings', { headers: authHeaders() });
    if (res.status === 401) { stopPolling(); showApp(false); return; }
    DATA = await res.json();
    render();
  } catch (e) { /* keep last view on transient errors */ }
}
function startPolling() { stopPolling(); pollTimer = setInterval(load, 8000); }
function stopPolling() { if (pollTimer) clearInterval(pollTimer); pollTimer = null; }

async function updateBooking(ref, patch) {
  try {
    const res = await fetch('/api/admin/update', { method: 'POST', headers: authHeaders(), body: JSON.stringify(Object.assign({ ref }, patch)) });
    if (!res.ok) { const d = await res.json(); alert(d.error || 'Update failed'); return; }
    await load();
  } catch (e) { alert('Could not reach the server.'); }
}
window.updateBooking = updateBooking;

function changeStatus(ref, sel) { updateBooking(ref, { status: sel.value }); }
function assignDriver(ref, inp) { const v = inp.value.trim(); if (v !== '') updateBooking(ref, { driverName: v }); }
function cancelBooking(ref) { if (confirm('Cancel booking ' + ref + '?')) updateBooking(ref, { status: 'cancelled' }); }
window.changeStatus = changeStatus;
window.assignDriver = assignDriver;
window.cancelBooking = cancelBooking;

/* ---------- render ---------- */
function renderStats() {
  const s = DATA.stats || {};
  const cards = [
    { n: s.total || 0, l: 'Total Bookings' },
    { n: money(s.revenue), l: 'Revenue (completed)', gold: true },
    { n: s.upcoming || 0, l: 'Active / Upcoming' },
    { n: s.completed || 0, l: 'Completed' },
    { n: s.cancelled || 0, l: 'Cancelled' },
  ];
  $('adminStats').innerHTML = cards.map(c =>
    '<div class="admin-stat"><div class="n' + (c.gold ? ' gold' : '') + '">' + c.n + '</div><div class="l">' + c.l + '</div></div>').join('');
}

function renderFilters() {
  const counts = { all: DATA.bookings.length };
  STATUSES.forEach(st => counts[st] = DATA.bookings.filter(b => b.status === st).length);
  const tabs = [['all', 'All']].concat(STATUSES.map(st => [st, STATUS_LABEL[st]]));
  $('adminFilters').innerHTML = tabs.map(([key, label]) =>
    '<button class="admin-filter' + (FILTER === key ? ' active' : '') + '" data-f="' + key + '">' + label +
    ' <span>' + (counts[key] || 0) + '</span></button>').join('');
  $('adminFilters').querySelectorAll('.admin-filter').forEach(btn =>
    btn.addEventListener('click', () => { FILTER = btn.dataset.f; render(); }));
}

function matchesSearch(b) {
  if (!SEARCH) return true;
  return [b.ref, b.passenger, b.pickup, b.dropoff, b.driverName, b.email, b.phone, b.vehicle]
    .some(v => (v || '').toString().toLowerCase().includes(SEARCH));
}

function render() {
  renderStats();
  renderFilters();
  let rows = DATA.bookings.filter(b => (FILTER === 'all' || b.status === FILTER) && matchesSearch(b));
  const list = $('adminList');
  if (!rows.length) {
    list.innerHTML = '<div class="admin-empty">No bookings match this view.</div>';
    return;
  }
  list.innerHTML = rows.map(b => {
    const statusOptions = STATUSES.map(st =>
      '<option value="' + st + '"' + (b.status === st ? ' selected' : '') + '>' + STATUS_LABEL[st] + '</option>').join('');
    return (
      '<div class="admin-card">' +
        '<div class="admin-card-main">' +
          '<div class="admin-ref">#' + esc(b.ref) + ' <span class="admin-pill ' + esc(b.status) + '">' + (STATUS_LABEL[b.status] || esc(b.status)) + '</span></div>' +
          '<div class="admin-when">' + esc(whenStr(b.dateISO)) + ' · ' + esc(b.service || '') + '</div>' +
          '<div class="admin-route"><span>📍 ' + esc(b.pickup || '—') + '</span><span>🏁 ' + esc(b.dropoff || '—') + '</span></div>' +
          '<div class="admin-meta">' +
            '<span>👤 ' + esc(b.passenger || 'Guest') + '</span>' +
            (b.phone ? '<span>📞 ' + esc(b.phone) + '</span>' : '') +
            (b.email ? '<span>✉️ ' + esc(b.email) + '</span>' : '') +
            '<span>' + esc(b.vehicleEmoji || '🚗') + ' ' + esc(b.vehicle || '') + '</span>' +
            '<span>👥 ' + esc(b.passengers || '1') + '</span>' +
            '<span class="gold">' + money(b.total) + '</span>' +
          '</div>' +
        '</div>' +
        '<div class="admin-card-actions">' +
          '<label class="admin-act-lbl">Status</label>' +
          '<select class="form-control admin-sel" onchange="changeStatus(\'' + esc(b.ref) + '\', this)">' + statusOptions + '</select>' +
          '<label class="admin-act-lbl">Driver</label>' +
          '<input class="form-control admin-sel" list="adminDrivers" value="' + esc(b.driverName || '') + '" placeholder="Assign driver" ' +
            'onchange="assignDriver(\'' + esc(b.ref) + '\', this)" />' +
          (b.status !== 'cancelled' ? '<button class="btn btn-outline btn-sm" onclick="cancelBooking(\'' + esc(b.ref) + '\')" style="margin-top:8px;">Cancel</button>' : '') +
        '</div>' +
      '</div>'
    );
  }).join('') +
  '<datalist id="adminDrivers">' + (DATA.drivers || []).map(d => '<option value="' + esc(d) + '">').join('') + '</datalist>';
}

/* ---------- boot ---------- */
(function boot() {
  try { TOKEN = localStorage.getItem(LS_ADMIN); } catch (e) {}
  if (TOKEN) { showApp(true); load().then(() => { if ($('adminApp').style.display !== 'none') startPolling(); }); }
  else { showApp(false); }
})();
