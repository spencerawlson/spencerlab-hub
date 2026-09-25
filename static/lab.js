/* Keeps the live lab panel fresh: polls /api/lab, updates every [data-k] value, redraws the
   [data-spark] sparklines, and turns [data-rel] timestamps into "2m ago". The server renders
   the first values, so without JS the panel is just a snapshot. */
(function () {
  var panel = document.querySelector('[data-lab]');
  if (!panel && !document.querySelector('[data-rel]')) return;

  function ago(iso) {
    var t = Date.parse(iso);
    if (isNaN(t)) return null;
    var s = Math.max(0, Math.round((Date.now() - t) / 1000));
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    if (s < 86400) return Math.round(s / 3600) + 'h ago';
    return Math.round(s / 86400) + 'd ago';
  }
  function duration(s) {
    var d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
    return d ? d + 'd ' + h + 'h' : (h ? h + 'h ' + m + 'm' : m + 'm');
  }
  function pct(v) { return v == null ? '—' : Math.round(v) + '%'; }
  function updown(v) { return v === true ? 'up' : (v === false ? 'down' : 'n/a'); }

  function spark(svg, values) {
    var pts = values.filter(function (v) { return v != null; });
    if (pts.length < 2) { svg.innerHTML = ''; return; }
    var max = Math.max.apply(null, pts), min = Math.min.apply(null, pts);
    var span = Math.max(max - min, max * 0.15, 1), step = 100 / (pts.length - 1);
    var line = pts.map(function (v, i) {
      return (i * step).toFixed(1) + ',' + (22 - ((v - min) / span) * 20).toFixed(1);
    }).join(' ');
    svg.innerHTML = '<polyline points="0,24 ' + line + ' 100,24" class="fill"/>' +
                    '<polyline points="' + line + '" class="line"/>';
  }

  function rel() {
    document.querySelectorAll('[data-rel]').forEach(function (el) {
      var a = ago(el.getAttribute('datetime'));
      if (a) el.textContent = a;
    });
  }

  function paint(d) {
    if (!panel) return;
    var n = d.now || {};
    var set = function (k, text) { var el = panel.querySelector('[data-k="' + k + '"]'); if (el) el.textContent = text; };
    set('cpu', pct(n.cpu)); set('memory', pct(n.memory)); set('disk', pct(n.disk));
    set('latency_ms', n.latency_ms == null ? '—' : n.latency_ms + ' ms');
    ['edge_ok', 'tunnel', 'site'].forEach(function (k) {
      set(k, updown(n[k]));
      var b = panel.querySelector('[data-k="' + k + '"]');
      var dot = b && b.parentNode.querySelector('.dot');
      if (dot) dot.className = 'dot ' + (n[k] === true ? 'up' : (n[k] === false ? 'down' : 'unk'));
    });
    if (d.uptime && d.uptime.host_s) set('uptime', duration(d.uptime.host_s));
    var bar = panel.querySelector('[data-bar="disk"]');
    if (bar && n.disk != null) bar.style.width = n.disk + '%';
    var at = panel.querySelector('[data-k="at"]');
    if (at && d.at) { at.setAttribute('datetime', d.at); at.textContent = ago(d.at); }
    panel.querySelectorAll('[data-spark]').forEach(function (svg) {
      spark(svg, (d.history || {})[svg.getAttribute('data-spark')] || []);
    });
  }

  function poll() {
    fetch('/api/lab', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) paint(d); })
      .catch(function () {});
  }

  rel();
  if (panel) { poll(); setInterval(poll, 30000); }
  setInterval(rel, 10000);
})();
