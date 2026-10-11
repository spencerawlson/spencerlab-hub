/* Keeps the Minecraft card on /projects fresh: polls /api/minecraft every 30 s and updates
   the Java and Bedrock rows of the [data-mc] block. The server renders the first values, so without JS it's a snapshot. */
(function () {
  var box = document.querySelector('[data-mc]');
  if (!box) return;
  function row(ed, online, text) {
    var r = box.querySelector('[data-mc-ed="' + ed + '"]');
    if (!r) return;
    r.querySelector('.dot').className = 'dot ' + (online ? 'up' : 'down');
    r.querySelector('[data-mc-k="state"]').textContent = online ? 'online' : 'offline';
    r.querySelector('[data-mc-k="detail"]').textContent = online ? text : '';
  }

  function paint(d) {
    if (!d.enabled) return;
    row('java', d.online, d.players + '/' + d.max_players + ' players' +
        (d.version ? ' · ' + d.version : '') + ' · ' + d.latency_ms + ' ms');
    var b = d.bedrock;
    if (b) row('bedrock', b.online, 'phones & consoles · ' + b.version + ' · ' + b.latency_ms + ' ms');
  }

  function poll() {
    fetch('/api/minecraft', { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) paint(d); })
      .catch(function () {});
  }

  setInterval(poll, 30000);
})();
