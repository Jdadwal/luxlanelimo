/* ===========================
   LUXLANE — AI CONCIERGE WIDGET
   Floating chat that answers questions about rates, fleet, areas,
   and booking. Talks to /api/concierge (Claude when configured,
   scripted answers otherwise).
   =========================== */
(function () {
  'use strict';
  if (window.__luxConcierge) return;        // guard against double-init
  window.__luxConcierge = true;

  var company = { name: 'Luxlane Limo', phone: '', phoneE164: '', whatsapp: '', email: '' };
  var history = [];
  var booting = true;

  function esc(s) { return (s || '').replace(/[&<>]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]; }); }

  // ---- build DOM ----
  var launcher = document.createElement('button');
  launcher.className = 'cc-launcher';
  launcher.setAttribute('aria-label', 'Open concierge chat');
  launcher.innerHTML = '<span class="cc-launch-ico">💬</span>';

  var panel = document.createElement('div');
  panel.className = 'cc-panel';
  panel.innerHTML =
    '<div class="cc-head">' +
      '<div class="cc-head-id"><div class="cc-avatar">L</div>' +
        '<div><div class="cc-title">Concierge</div><div class="cc-status"><span class="cc-dot"></span> Online · replies instantly</div></div>' +
      '</div>' +
      '<button class="cc-close" aria-label="Close">✕</button>' +
    '</div>' +
    '<div class="cc-body" id="ccBody"></div>' +
    '<div class="cc-quick" id="ccQuick"></div>' +
    '<form class="cc-input" id="ccForm">' +
      '<input id="ccText" type="text" autocomplete="off" placeholder="Ask about rates, vehicles, booking…" />' +
      '<button type="submit" aria-label="Send">➤</button>' +
    '</form>';

  document.body.appendChild(launcher);
  document.body.appendChild(panel);

  var body = panel.querySelector('#ccBody');
  var quick = panel.querySelector('#ccQuick');
  var form = panel.querySelector('#ccForm');
  var input = panel.querySelector('#ccText');

  function addMsg(text, who) {
    var el = document.createElement('div');
    el.className = 'cc-msg ' + (who === 'me' ? 'cc-me' : 'cc-bot');
    el.innerHTML = esc(text).replace(/\n/g, '<br>');
    body.appendChild(el);
    body.scrollTop = body.scrollHeight;
    return el;
  }

  function typing(on) {
    var ex = body.querySelector('.cc-typing');
    if (on && !ex) {
      var t = document.createElement('div');
      t.className = 'cc-msg cc-bot cc-typing';
      t.innerHTML = '<span></span><span></span><span></span>';
      body.appendChild(t);
      body.scrollTop = body.scrollHeight;
    } else if (!on && ex) { ex.remove(); }
  }

  function setQuick(items) {
    quick.innerHTML = '';
    items.forEach(function (q) {
      var b = document.createElement('button');
      b.className = 'cc-chip';
      b.textContent = q;
      b.addEventListener('click', function () { send(q); });
      quick.appendChild(b);
    });
  }

  function contactRow() {
    if (!company.phoneE164) return;
    var row = document.createElement('div');
    row.className = 'cc-contact';
    row.innerHTML =
      '<a href="tel:' + company.phoneE164 + '">📞 Call</a>' +
      (company.whatsapp ? '<a href="https://wa.me/' + company.whatsapp + '" target="_blank" rel="noopener">💚 WhatsApp</a>' : '') +
      (company.email ? '<a href="mailto:' + company.email + '">✉️ Email</a>' : '');
    body.appendChild(row);
  }

  var open = false;
  function toggle(show) {
    open = (show === undefined) ? !open : show;
    panel.classList.toggle('open', open);
    launcher.classList.toggle('hidden', open);
    if (open) {
      if (booting) { greet(); booting = false; }
      setTimeout(function () { input.focus(); }, 150);
    }
  }
  launcher.addEventListener('click', function () { toggle(true); });
  panel.querySelector('.cc-close').addEventListener('click', function () { toggle(false); });

  function greet() {
    addMsg('👋 Welcome to ' + company.name + '! I can help with rates, our fleet, airport & cross-border trips, Niagara tours, and booking. What can I help you with?', 'bot');
    contactRow();
    setQuick(['View rates', 'Airport transfer', 'Cross-border trip', 'Book a ride']);
  }

  async function send(text) {
    text = (text || '').trim();
    if (!text) return;
    addMsg(text, 'me');
    history.push({ role: 'user', content: text });
    input.value = '';
    setQuick([]);
    typing(true);
    try {
      var res = await fetch('/api/concierge', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history: history.slice(0, -1) })
      });
      var data = await res.json();
      typing(false);
      var reply = data.reply || 'Sorry, I had trouble with that. Please call us and we\'ll help right away.';
      addMsg(reply, 'bot');
      history.push({ role: 'assistant', content: reply });
      if (/book|reserve/i.test(text)) {
        var cta = document.createElement('a');
        cta.className = 'cc-cta'; cta.href = 'booking.html'; cta.textContent = 'Open the booking page →';
        body.appendChild(cta); body.scrollTop = body.scrollHeight;
      }
    } catch (e) {
      typing(false);
      addMsg('I\'m having trouble connecting. Please ' + (company.phoneE164 ? 'call ' + company.phone : 'try again') + '.', 'bot');
    }
  }

  form.addEventListener('submit', function (e) { e.preventDefault(); send(input.value); });

  // ---- load company contact from /api/config ----
  fetch('/api/config').then(function (r) { return r.json(); }).then(function (c) {
    if (c && c.company) {
      company = Object.assign(company, c.company);
      var av = panel.querySelector('.cc-avatar');
      if (av && company.name) av.textContent = company.name.trim().charAt(0).toUpperCase();
    }
  }).catch(function () {});
})();
