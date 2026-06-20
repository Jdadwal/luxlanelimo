/* ===========================
   LUXLANE — LIVE RIDE TRACKING
   =========================== */
'use strict';

const POLL_MS = 2000;

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(location.search);
const REF = (params.get('ref') || '').replace('#', '');

let timer = null;
let routeLen = 0;
const base = $('routeBase');
const prog = $('routeProg');
const car = $('carMarker');

function initRoute() {
  routeLen = base.getTotalLength();
  prog.style.strokeDasharray = routeLen;
  prog.style.strokeDashoffset = routeLen; // nothing traveled yet
}

function setProgress(p) {
  p = Math.max(0, Math.min(1, p || 0));
  // traveled portion
  prog.style.strokeDashoffset = routeLen * (1 - p);
  // car position along the path
  const pt = base.getPointAtLength(routeLen * p);
  car.setAttribute('transform', 'translate(' + pt.x.toFixed(1) + ',' + pt.y.toFixed(1) + ')');
}

function initials(name) {
  return (name || 'D').trim().split(/\s+/).map(w => w[0]).slice(0, 2).join('').toUpperCase();
}
function plateFrom(ref) {
  const s = (ref || 'LX0000').replace(/[^A-Z0-9]/gi, '').toUpperCase();
  return 'LUX ' + s.slice(-4);
}

const STATUS_TEXT = {
  assigned: () => 'Your chauffeur is <span class="em">on the way</span> to pick you up',
  arrived: () => 'Your chauffeur has <span class="em">arrived</span> at the pick-up',
  on_trip: () => 'On the way to your <span class="em">destination</span>',
  completed: () => 'Trip <span class="em">completed</span>',
};

function render(d) {
  $('trackRef').textContent = '#' + d.ref;

  // route labels depend on the current leg
  if (d.leg === 'approach') {
    $('startLabel').textContent = "Chauffeur's start";
    $('endLabel').textContent = 'Your pick-up';
    $('trackPickup').textContent = 'En route';
    $('trackDropoff').textContent = d.pickup || '—';
  } else {
    $('startLabel').textContent = 'Pick-up';
    $('endLabel').textContent = 'Destination';
    $('trackPickup').textContent = d.pickup || '—';
    $('trackDropoff').textContent = d.dropoff || '—';
  }

  const assigned = !!d.driverName;
  // cards
  $('waitingCard').style.display = (!assigned && d.status !== 'completed') ? 'block' : 'none';
  $('doneCard').style.display = (d.status === 'completed') ? 'block' : 'none';
  $('etaCard').style.display = (assigned && d.status !== 'completed') ? 'block' : 'none';

  // driver card
  if (assigned) {
    $('driverAvatar').textContent = initials(d.driverName);
    $('driverName').textContent = d.driverName;
    $('driverMeta').textContent = (d.vehicleEmoji || '🚗') + ' ' + (d.vehicle || '') + ' · ⭐ 4.9';
    const plate = $('driverPlate');
    plate.style.display = 'inline-block';
    plate.textContent = plateFrom(d.ref);
    const call = $('driverCall');
    call.classList.remove('disabled');
    call.href = 'tel:+15550100';
  } else {
    $('driverAvatar').textContent = '…';
    $('driverName').textContent = 'Assigning chauffeur…';
    $('driverMeta').textContent = (d.vehicleEmoji || '🚗') + ' ' + (d.vehicle || '');
  }

  // ETA + status + progress
  if (assigned && d.status !== 'completed') {
    $('etaStatus').innerHTML = (STATUS_TEXT[d.status] || (() => 'Tracking your ride'))();
    if (d.status === 'arrived') {
      $('etaNum').textContent = '0';
      $('etaUnit').textContent = 'arrived — meet your chauffeur';
    } else {
      $('etaNum').textContent = (d.etaMin != null ? d.etaMin : '—');
      $('etaUnit').textContent = 'min away';
    }
  }

  // progress bar + map
  $('etaBar').style.width = Math.round((d.progress || 0) * 100) + '%';
  setProgress(d.progress);

  if (d.status === 'completed') {
    setProgress(1);
    $('etaBar').style.width = '100%';
    stop();
  }
}

async function poll() {
  try {
    const r = await fetch('/api/rides/track?ref=' + encodeURIComponent(REF));
    if (r.status === 404) { showNotFound(); return; }
    const d = await r.json();
    if (!d.found) { showNotFound(); return; }
    render(d);
  } catch (e) { /* keep last state on transient errors */ }
}

function showNotFound() {
  $('etaCard').style.display = 'none';
  $('waitingCard').style.display = 'block';
  $('waitingCard').querySelector('.eta-status').textContent = '🔎 Ride not found';
  $('waitingCard').querySelector('.text-gray').textContent =
    'We couldn\'t find this ride. It may not have been booked on this server yet.';
  stop();
}

function stop() { if (timer) { clearInterval(timer); timer = null; } }

function start() {
  initRoute();
  if (!REF) { showNotFound(); return; }
  poll();
  timer = setInterval(poll, POLL_MS);
}

// pause polling when tab hidden (saves battery/requests), resume on return
document.addEventListener('visibilitychange', () => {
  if (document.hidden) stop();
  else if (!timer) start();
});

start();
