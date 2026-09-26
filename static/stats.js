/* The private visitor dashboard. Asks for the stats token, reads /api/visitors with it as a
   bearer header, and draws: KPI tiles, the world map (same silhouette, projection and bubble
   sizing as the Aegis CloudOps Cloud Map), views per day, top lists and recent visits.
   Every node is built with the DOM from data (never innerHTML): the log holds user agents,
   referrers and paths that visitors control. */
(function () {
  var root = document.querySelector('[data-stats]');
  if (!root) return;
  var KEY = 'spencerlab.statsToken';
  var $ = function (sel) { return root.querySelector(sel); };
  var gate = $('[data-gate]'), dash = $('[data-dash]'), msg = $('[data-gate-msg]');
  var days = 30, data = null, selected = null;

  function el(tag, attrs, kids) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === 'text') n.textContent = attrs[k];
      else if (k === 'on') Object.keys(attrs.on).forEach(function (ev) { n.addEventListener(ev, attrs.on[ev]); });
      else if (k === 'style') n.style.cssText = attrs[k];
      else n.setAttribute(k, attrs[k]);
    });
    (kids || []).forEach(function (c) { if (c != null) n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c); });
    return n;
  }
  function svgEl(tag, attrs) {
    var n = document.createElementNS('http://www.w3.org/2000/svg', tag);
    Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    return n;
  }
  function fmt(n) { return (n || 0).toLocaleString(); }
  function token() { try { return sessionStorage.getItem(KEY); } catch (e) { return null; } }
  function setToken(t) { try { t ? sessionStorage.setItem(KEY, t) : sessionStorage.removeItem(KEY); } catch (e) {} }

  // --- loading -------------------------------------------------------------------------
  function load() {
    var t = token();
    if (!t) return showGate();
    $('[data-updated]').textContent = 'loading…';
    fetch('/api/visitors?days=' + days + '&recent=200', { headers: { Authorization: 'Bearer ' + t }, cache: 'no-store' })
      .then(function (r) {
        if (r.status === 401) { setToken(null); throw new Error('That token was not accepted.'); }
        if (r.status === 503) throw new Error('Stats are off on the server: HUB_STATS_TOKEN is not set.');
        if (!r.ok) throw new Error('The server answered ' + r.status + '.');
        return r.json();
      })
      .then(function (d) { data = d; selected = null; gate.hidden = true; dash.hidden = false; render(); })
      .catch(function (e) { showGate(e.message); });
  }
  function showGate(err) {
    dash.hidden = true; gate.hidden = false;
    if (err) { msg.textContent = err; msg.classList.add('bad'); }
  }
  gate.addEventListener('submit', function (e) {
    e.preventDefault();
    var input = gate.querySelector('input');
    setToken(input.value.trim()); input.value = '';
    msg.classList.remove('bad');
    load();
  });
  root.querySelectorAll('[data-days]').forEach(function (b) {
    b.addEventListener('click', function () {
      days = +b.getAttribute('data-days');
      root.querySelectorAll('[data-days]').forEach(function (x) { x.setAttribute('aria-pressed', String(x === b)); });
      load();
    });
  });
  $('[data-refresh]').addEventListener('click', load);
  $('[data-signout]').addEventListener('click', function () {
    setToken(null); data = null; msg.textContent = 'Locked. Enter the token to view the dashboard again.';
    msg.classList.remove('bad'); showGate();
  });

  // --- render --------------------------------------------------------------------------
  function render() {
    $('[data-kpi="views"]').textContent = fmt(data.views);
    $('[data-kpi="visitors"]').textContent = fmt(data.visitors);
    $('[data-kpi="countries"]').textContent = fmt((data.countries || []).filter(function (c) { return c.k !== 'unknown'; }).length);
    $('[data-kpi="bots"]').textContent = fmt(data.bot_views);
    $('[data-updated]').textContent = 'as of ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    renderMap(); renderLocations(); renderDaily(); renderTops(); renderRecent();
  }

  // Equirectangular -> % of the 2:1 box. Identical to proj() in Aegis CloudMap.jsx.
  function proj(lon, lat) {
    return { x: Math.max(2, Math.min(98, ((lon + 180) / 360) * 100)),
             y: Math.max(4, Math.min(96, ((90 - lat) / 180) * 100)) };
  }
  function pointKey(p) { return p.level + ':' + p.label; }

  function renderMap() {
    var layer = $('[data-map-layer]'), pts = data.points || [];
    layer.textContent = '';
    $('[data-map-empty]').hidden = pts.length > 0;
    var max = Math.max.apply(null, [1].concat(pts.map(function (p) { return p.views; })));
    // Biggest first in the list, but drawn smallest-last so small bubbles stay clickable on top.
    pts.slice().reverse().forEach(function (p, i) {
      var rank = pts.length - 1 - i, xy = proj(p.lon, p.lat), key = pointKey(p);
      var size = 18 + Math.round((p.views / max) * 30), isSel = selected === key;
      var what = p.views + ' view' + (p.views === 1 ? '' : 's') + ' · ' + p.visitors + ' visitor' + (p.visitors === 1 ? '' : 's');
      var dot = el('button', {
        type: 'button', class: 'wm-dot' + (isSel ? ' on' : ''), 'aria-pressed': String(isSel),
        'aria-label': p.label + ': ' + what, title: p.label + ' — ' + what,
        style: 'width:' + size + 'px;height:' + size + 'px',
        on: { click: function () { select(isSel ? null : key); } }
      }, [String(p.views)]);
      var kids = [dot];
      if (rank < 8 || isSel) kids.push(el('span', { class: 'wm-tag', text: p.level === 'city' ? p.label.split(',')[0] : p.label }));
      layer.appendChild(el('div', { class: 'wm-pin', style: 'left:' + xy.x + '%;top:' + xy.y + '%;z-index:' + (isSel ? 30 : 10 + i) }, kids));
    });
  }

  function select(key) { selected = key; renderMap(); renderLocations(); }

  function renderLocations() {
    var list = $('[data-loc-list]'), pts = data.points || [];
    list.textContent = '';
    $('[data-loc-count]').textContent = 'Locations (' + pts.length + ')';
    pts.forEach(function (p) {
      var key = pointKey(p);
      list.appendChild(el('button', {
        type: 'button', class: 'st-locrow' + (selected === key ? ' on' : ''),
        on: { click: function () { select(key); } }
      }, [el('span', { class: 'n', text: p.label }), el('span', { class: 'v', text: fmt(p.views) + ' views · ' + fmt(p.visitors) + ' visitors' })]));
    });
    if (!pts.length) list.appendChild(el('div', { class: 'st-none', text: 'None yet.' }));

    var detail = $('[data-loc-detail]'), title = $('[data-loc-title]');
    detail.textContent = '';
    var p = pts.filter(function (q) { return pointKey(q) === selected; })[0];
    if (!p) {
      title.textContent = 'Select a location';
      detail.appendChild(el('div', { class: 'empty', text: 'Tap a bubble or a location to see its recent visits.' }));
      return;
    }
    var city = p.level === 'city' ? p.label.split(',')[0] : null;
    var rows = (data.recent || []).filter(function (r) { return r.country === p.country && (!city || r.city === city); });
    title.textContent = p.label + ' — ' + fmt(p.views) + ' views, ' + fmt(p.visitors) + ' visitors';
    if (!rows.length) {
      detail.appendChild(el('div', { class: 'empty', text: 'No visits from here among the latest 200.' }));
      return;
    }
    detail.appendChild(el('div', { class: 'st-visits' }, rows.slice(0, 40).map(function (r) {
      return el('div', { class: 'st-visit' }, [
        el('span', { class: 'p', text: r.path }),
        el('span', { class: 'm', text: [r.city, r.browser + ' on ' + r.os, r.ip].filter(Boolean).join(' · ') }),
        el('time', { datetime: r.at, text: when(r.at) })
      ]);
    })));
  }

  // Views per day: single series -> one hue, no legend; rounded data-ends, 2px gaps, hover tooltip.
  function renderDaily() {
    var box = $('[data-daily]');
    box.textContent = '';
    var byDay = {};
    (data.daily || []).forEach(function (d) { byDay[d.k] = d; });
    var series = [];
    for (var i = days - 1; i >= 0; i--) {
      var k = new Date(Date.now() - i * 864e5).toISOString().slice(0, 10);
      series.push({ k: k, views: (byDay[k] || {}).views || 0, visitors: (byDay[k] || {}).visitors || 0 });
    }
    var W = Math.max(280, box.clientWidth || 800), H = 200, padL = 36, padB = 24, padT = 10;
    var max = Math.max(4, Math.max.apply(null, series.map(function (s) { return s.views; })));
    var step = Math.pow(10, Math.floor(Math.log10(max))), top = Math.ceil(max / step) * step;
    var plotW = W - padL, plotH = H - padB - padT, slot = plotW / series.length, bw = Math.max(1, slot - 2);
    var svg = svgEl('svg', { viewBox: '0 0 ' + W + ' ' + H, width: '100%', height: H, role: 'img',
      'aria-label': 'Page views per day over the last ' + days + ' days' });
    [0, 0.5, 1].forEach(function (f) {
      var y = padT + plotH - f * plotH;
      svg.appendChild(svgEl('line', { x1: padL, x2: W, y1: y, y2: y, class: 'st-gridline' }));
      var t = svgEl('text', { x: padL - 8, y: y + 4, class: 'st-axis', 'text-anchor': 'end' });
      t.textContent = fmt(Math.round(top * f)); svg.appendChild(t);
    });
    var tip = el('div', { class: 'st-tip', hidden: '' });
    series.forEach(function (s, i) {
      var h = s.views ? Math.max(2, (s.views / top) * plotH) : 0, x = padL + i * slot + 1, y = padT + plotH - h;
      if (h) {
        var r = Math.min(4, bw / 2, h);
        svg.appendChild(svgEl('path', { class: 'st-barmark', d:
          'M' + x + ',' + (padT + plotH) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y +
          'H' + (x + bw - r) + 'Q' + (x + bw) + ',' + y + ' ' + (x + bw) + ',' + (y + r) + 'V' + (padT + plotH) + 'Z' }));
      }
      var hit = svgEl('rect', { x: padL + i * slot, y: padT, width: slot, height: plotH, class: 'st-hit' });
      hit.addEventListener('mouseenter', function () {
        tip.hidden = false;
        tip.textContent = '';
        tip.appendChild(el('b', { text: s.k }));
        tip.appendChild(el('span', { text: fmt(s.views) + ' views · ' + fmt(s.visitors) + ' visitors' }));
        var px = ((padL + (i + 0.5) * slot) / W) * box.clientWidth;
        tip.style.left = Math.min(Math.max(px, 70), box.clientWidth - 70) + 'px';
      });
      hit.addEventListener('mouseleave', function () { tip.hidden = true; });
      svg.appendChild(hit);
      var every = Math.ceil(series.length / 6);
      if (i % every === 0 || i === series.length - 1) {
        var lab = svgEl('text', { x: padL + (i + 0.5) * slot, y: H - 6, class: 'st-axis', 'text-anchor': 'middle' });
        lab.textContent = s.k.slice(5); svg.appendChild(lab);
      }
    });
    box.appendChild(svg); box.appendChild(tip);
  }

  function renderTops() {
    ['pages', 'referrers', 'countries', 'browsers', 'os', 'devices'].forEach(function (name) {
      var box = root.querySelector('[data-top="' + name + '"]'), rows = (data[name] || []).slice(0, 8);
      box.textContent = '';
      if (!rows.length) return box.appendChild(el('div', { class: 'st-none', text: 'None yet.' }));
      var max = rows[0].views || 1;
      rows.forEach(function (r) {
        var label = name === 'countries' ? (r.name || r.k) : r.k;
        box.appendChild(el('div', { class: 'st-row', title: label + ': ' + r.views + ' views, ' + r.visitors + ' visitors' }, [
          el('span', { class: 'n', text: label }),
          el('span', { class: 'b' }, [el('i', { style: 'width:' + Math.max(2, (r.views / max) * 100) + '%' })]),
          el('span', { class: 'v', text: fmt(r.views) })
        ]));
      });
    });
  }

  function when(iso) {
    var d = new Date(iso), s = Math.round((Date.now() - d) / 1000);
    if (s < 60) return s + 's ago';
    if (s < 3600) return Math.round(s / 60) + 'm ago';
    if (s < 86400) return Math.round(s / 3600) + 'h ago';
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' }) + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }

  function renderRecent() {
    var body = $('[data-recent]');
    body.textContent = '';
    (data.recent || []).forEach(function (r) {
      var place = [r.city, r.region, r.country].filter(Boolean).join(', ') || 'unknown';
      body.appendChild(el('tr', { class: r.bot ? 'bot' : '' }, [
        el('td', {}, [el('time', { datetime: r.at, title: r.at, text: when(r.at) })]),
        el('td', { class: 'mono' }, [r.path, r.status >= 400 ? el('span', { class: 'st-code', text: String(r.status) }) : null]),
        el('td', { text: place }),
        el('td', { class: 'mono', text: r.ip || '' }),
        el('td', {}, [r.bot ? el('span', { class: 'chip status', text: 'bot' }) : null, (r.bot ? ' ' : '') + r.device + ' · ' + r.browser + ' · ' + r.os]),
        el('td', { text: r.ref_host || (r.utm_source ? 'utm: ' + r.utm_source : 'direct') })
      ]));
    });
    if (!(data.recent || []).length) body.appendChild(el('tr', {}, [el('td', { colspan: '6', class: 'st-none', text: 'No visits in this range yet.' })]));
  }

  var resizeT;
  window.addEventListener('resize', function () {
    clearTimeout(resizeT);
    resizeT = setTimeout(function () { if (data && !dash.hidden) renderDaily(); }, 150);
  });

  load();
})();
