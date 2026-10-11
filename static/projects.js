/* Keeps the Minecraft card on /projects fresh: polls /api/minecraft every 30 s and updates
   the [data-mc] block. The server renders the first values, so without JS it's a snapshot. */
(function () {
  var box = document.querySelector('[data-mc]');
  if (!box) return;
  var dot = box.querySelector('[data-mc-dot]');
  var state = box.querySelector('[data-mc-k="state"]');
  var detail = box.querySelector('[data-mc-k="detail"]');

  function paint(d) {
    if (!d.enabled) return;
    dot.className = 'dot ' + (d.online ? 'up' : 'down');
    state.textContent = d.online ? 'online' : 'offline';
    detail.textContent = d.online
      ? d.players + '/' + d.max_players + ' players' + (d.version ? ' · ' + d.version : '') + ' · ' + d.latency_ms + ' ms'
      : '';
  }

  function poll() {
    fetch('/api/minecraft', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) paint(d); })
      .catch(function () {});
  }

  setInterval(poll, 30000);
})();
