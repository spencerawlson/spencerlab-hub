/* The home-page console: a small command shell over the site's own content. Post and topic
   lists come from the server-rendered #console-data blob; `lab` reads /api/lab live. Every
   line is built with DOM nodes (never innerHTML), so typed input is only ever text. */
(function () {
  var root = document.querySelector('[data-console]');
  if (!root) return;
  var body = root.querySelector('[data-console-body]');
  var hist = root.querySelector('[data-console-history]');
  var input = root.querySelector('[data-console-input]');
  var data = {};
  try { data = JSON.parse(document.getElementById('console-data').textContent); } catch (e) {}
  var posts = data.posts || [], topics = data.topics || [];
  var past = [], at = 0;

  /* A line is a string or an array of parts: "text" | {t, cls} | {t, href}. */
  function part(p) {
    if (typeof p === 'string') return document.createTextNode(p);
    var el = document.createElement(p.href ? 'a' : 'span');
    if (p.href) el.href = p.href;
    if (p.cls) el.className = p.cls;
    el.textContent = p.t;
    return el;
  }
  function print(lines) {
    var out = document.createElement('div');
    out.className = 'out';
    lines.forEach(function (ln, i) {
      if (i) out.appendChild(document.createTextNode('\n'));
      (Array.isArray(ln) ? ln : [ln]).forEach(function (p) { out.appendChild(part(p)); });
    });
    hist.appendChild(out);
    body.scrollTop = body.scrollHeight;
    return out;
  }
  function echo(cmd) {
    var row = document.createElement('div');
    row.className = 'echo';
    row.appendChild(part({ t: 'spencer@lab:~$', cls: 'prompt' }));
    row.appendChild(part({ t: cmd, cls: 'cmd' }));
    hist.appendChild(row);
  }
  function pad(s, n) { s = String(s); while (s.length < n) s += ' '; return s; }
  function hl(t) { return { t: t, cls: 'hl' }; }
  function dim(t) { return { t: t, cls: 'dim' }; }

  var HELP = [
    ['whoami', 'who writes this, and about what'],
    ['posts', 'list recent write-ups'],
    ['open <n>', 'open post number n from the list'],
    ['topics', 'the five disciplines, with post counts'],
    ['lab', 'live telemetry from the server behind this page'],
    ['stack', 'tools and platforms in use'],
    ['search <q>', 'search every post'],
    ['contact', 'where to find me'],
    ['visitors [days]', 'who visited and from where (owner: unlock first)'],
    ['visitors live', 'watch new visits as they happen; stop to end'],
    ['unlock <token>', 'unlock visitor stats with the stats token'],
    ['lock', 'forget the stats token'],
    ['stop', 'stop a running visitors live'],
    ['clear', 'clear the screen']
  ];

  var cmds = {
    help: function () {
      print(['Available commands:'].concat(HELP.map(function (h) {
        return [' • ', hl(pad(h[0], 16)), h[1]];
      })));
    },
    whoami: function () {
      print([
        'spencer — security & infrastructure engineer, documenting a homelab in public.',
        ['FOCUS    ', 'cybersecurity · networking · cloud · SaaS'],
        ['WORK     ', 'build logs, pentest & assessment reports, repairs, admin'],
        ['HOSTING  ', 'homelab VM · FastAPI · Cloudflare Tunnel · 0 inbound ports'],
        ['MORE     ', { t: '/about', href: '/about' }]
      ]);
    },
    posts: function () {
      if (!posts.length) return print(['Nothing published yet.']);
      print(posts.map(function (p, i) {
        return [dim('[' + (i + 1) + '] '), { t: p.t, href: p.u }, dim('  ' + p.c + ' · ' + p.d)];
      }).concat([[dim('Type '), hl('open <n>'), dim(' to read one, or see '), { t: 'all ' + (data.total || posts.length) + ' posts', href: '/posts' }, dim('.')]]));
    },
    ls: function () { cmds.posts(); },
    open: function (arg) {
      var p = posts[parseInt(arg, 10) - 1];
      if (!p) return print([{ t: 'open: no post ' + (arg || '(missing number)') + ' — run posts for the list.', cls: 'bad' }]);
      print(['Opening ', { t: p.t, href: p.u }, ' …']);
      location.href = p.u;
    },
    topics: function () {
      print(topics.map(function (t) {
        return [' • ', { t: pad(t.n, 14), href: t.u }, dim(t.k + ' post' + (t.k === 1 ? '' : 's'))];
      }));
    },
    lab: function () {
      var out = print([dim('fetching /api/lab …')]);
      fetch('/api/lab', { cache: 'no-store' })
        .then(function (r) { if (!r.ok) throw 0; return r.json(); })
        .then(function (d) {
          hist.removeChild(out);
          var n = d.now || {};
          var pct = function (v) { return v == null ? '—' : Math.round(v) + '%'; };
          var up = function (v) { return v === true ? { t: 'up', cls: 'good' } : (v === false ? { t: 'down', cls: 'bad' } : dim('n/a')); };
          var s = d.uptime && d.uptime.host_s, sweep = d.agents && d.agents.sweep;
          var days = s ? Math.floor(s / 86400) + 'd ' + Math.floor((s % 86400) / 3600) + 'h' : '—';
          var agents = !(d.agents && d.agents.online) ? dim('offline')
            : !sweep ? dim('first sweep pending')
            : sweep.attention ? { t: sweep.attention + ' of ' + sweep.results.length + ' flagged (advisory)', cls: 'warnc' }
            : { t: sweep.results.length + '/' + sweep.results.length + ' nominal', cls: 'good' };
          print([
            ['CPU      ', hl(pct(n.cpu)), '      MEMORY  ', hl(pct(n.memory))],
            ['DISK     ', hl(pct(n.disk)), '      EDGE    ', hl(n.latency_ms == null ? '—' : n.latency_ms + ' ms')],
            ['HTTPS    ', up(n.edge_ok), '   TUNNEL  ', up(n.tunnel), '   SITE  ', up(n.site)],
            ['UPTIME   ', days],
            ['AGENTS   ', agents],
            [dim('Full view: '), { t: '/lab', href: '/lab' }]
          ]);
        })
        .catch(function () {
          hist.removeChild(out);
          print([{ t: 'lab: telemetry unavailable right now.', cls: 'bad' }]);
        });
    },
    stack: function () {
      print([
        ['CLOUD    ', 'AWS · Azure · GCP · Terraform'],
        ['INFRA    ', 'Proxmox · GNS3 · Docker · Kubernetes · Linux · systemd'],
        ['NETWORK  ', 'Cloudflare Tunnel · Nginx · ZeroTier · Let\'s Encrypt'],
        ['SECURITY ', 'Kali · Nmap · Metasploit · Burp · GVM'],
        ['CODE     ', 'Python · FastAPI · Go · TypeScript · React · PostgreSQL']
      ]);
    },
    search: function (arg) {
      if (!arg) return print([{ t: 'search: give it something to look for, e.g. search nmap', cls: 'bad' }]);
      print(['Searching for ', hl(arg), ' …']);
      location.href = '/search?q=' + encodeURIComponent(arg);
    },
    contact: function () {
      print([
        ['GITHUB   ', { t: 'github.com/spencerawlson', href: 'https://github.com/spencerawlson' }],
        ['ABOUT    ', { t: '/about', href: '/about' }]
      ]);
    },
    clear: function () { hist.textContent = ''; },

    /* Owner-only: the same token and endpoint as the /stats dashboard. */
    unlock: function (arg) {
      if (!arg) return print([{ t: 'unlock: usage — unlock <stats token>', cls: 'bad' }]);
      var out = print([dim('checking token …')]);
      api('/api/visitors?days=1&recent=0', arg).then(function () {
        hist.removeChild(out);
        setToken(arg);
        print([{ t: 'unlocked', cls: 'good' }, dim(' for this tab. Try '), hl('visitors'), dim(' or '), hl('visitors 30'), dim('.')]);
      }, function (e) { hist.removeChild(out); print([{ t: 'unlock: ' + e.message, cls: 'bad' }]); });
    },
    lock: function () { stopWatch(true); setToken(null); print(['Locked. The stats token is forgotten in this tab.']); },
    stop: function () { if (!stopWatch()) print([dim('Nothing is running.')]); },
    visitors: function (arg) {
      var t = token();
      if (!t) return print([[{ t: 'visitors: locked.', cls: 'warnc' }, ' Run ', hl('unlock <token>'), ' with the stats token, or open ', { t: '/stats', href: '/stats' }, '.']]);
      if (/^(live|watch|-f)$/i.test(arg)) return startWatch(t);
      var days = Math.max(1, Math.min(365, parseInt(arg, 10) || 7));
      var out = print([dim('fetching /api/visitors …')]);
      api('/api/visitors?days=' + days + '&recent=100', t).then(function (d) {
        hist.removeChild(out);
        var list = function (rows, label) {
          return (rows || []).slice(0, 5).map(function (r) { return label(r) + ' ' + r.views; }).join(' · ') || '—';
        };
        var lines = [
          [hl('VISITORS'), dim(' · last ' + (days === 1 ? '24 hours' : days + ' days'))],
          ['VIEWS    ', hl(String(d.views)), '    UNIQUE  ', hl(String(d.visitors)), '    BOTS  ', dim(String(d.bot_views))],
          ['COUNTRY  ', list(d.countries, function (r) { return r.name || r.k; })],
          ['CITIES   ', list((d.points || []).filter(function (p) { return p.level === 'city'; }),
                             function (p) { return p.label.split(',')[0]; })],
          ['FROM     ', list(d.referrers, function (r) { return r.k; })],
          [dim('RECENT (humans; bots hidden)')]
        ];
        var humans = (d.recent || []).filter(function (r) { return !r.bot; });
        humans.slice(0, 12).forEach(function (r) {
          var where = [r.city, r.country].filter(Boolean).join(', ') || 'unknown';
          lines.push([dim(pad(ago(r.at), 9)), pad(where, 20).slice(0, 20), ' ', pad(r.path, 22).slice(0, 22),
                      dim(' ' + r.device + '/' + r.browser + ' · ' + (r.ip || ''))]);
        });
        if (!humans.length) lines.push([dim('  no human visits in this range')]);
        lines.push([dim('Full dashboard: '), { t: '/stats', href: '/stats' }]);
        print(lines);
      }, function (e) { hist.removeChild(out); print([{ t: 'visitors: ' + e.message, cls: 'bad' }]); });
    }
  };
  cmds.who = cmds.visitors;

  /* visitors live: poll the live feed every 5 s and print each new human visit. */
  var watch = null;
  function visitLine(r) {
    var where = [r.city, r.country].filter(Boolean).join(', ') || 'unknown';
    return [{ t: '● ', cls: 'good' }, dim(pad(new Date(r.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }), 10)),
            pad(where, 20).slice(0, 20), ' ', pad(r.path, 22).slice(0, 22), dim(' ' + r.device + '/' + r.browser + ' · ' + (r.ip || ''))];
  }
  function startWatch(t) {
    if (watch) return print([dim('Already watching. Type '), hl('stop'), dim(' to end.')]);
    watch = { cursor: null, active: null, timer: null };
    print([[{ t: 'LIVE', cls: 'good' }, dim(' · new visits appear here as they happen (bots hidden). Type '), hl('stop'), dim(' to end.')]]);
    var poll = function () {
      if (!watch || document.hidden) return;
      api('/api/visitors/live' + (watch.cursor == null ? '' : '?since=' + watch.cursor), token() || t).then(function (d) {
        if (!watch) return;
        if (d.active_now !== watch.active) {
          watch.active = d.active_now;
          print([[dim('active now: '), hl(String(d.active_now)), dim(d.active_now === 1 ? ' person' : ' people')]]);
        }
        d.visits.filter(function (v) { return !v.bot; }).forEach(function (v) { print([visitLine(v)]); });
        watch.cursor = d.last_id;
      }, function (e) { print([{ t: 'live: ' + e.message, cls: 'bad' }]); stopWatch(true); });
    };
    watch.timer = setInterval(poll, 5000);
    poll();
  }
  function stopWatch(quiet) {
    if (!watch) return false;
    clearInterval(watch.timer); watch = null;
    if (!quiet) print([dim('Stopped watching.')]);
    return true;
  }

  var KEY = 'spencerlab.statsToken';
  function token() { try { return sessionStorage.getItem(KEY); } catch (e) { return null; } }
  function setToken(t) { try { t ? sessionStorage.setItem(KEY, t) : sessionStorage.removeItem(KEY); } catch (e) {} }
  function api(url, t) {
    return fetch(url, { headers: { Authorization: 'Bearer ' + t }, cache: 'no-store' }).then(function (r) {
      if (r.status === 401) { if (t === token()) setToken(null); throw new Error('token not accepted.'); }
      if (r.status === 503) throw new Error('stats are off on the server (HUB_STATS_TOKEN not set).');
      if (!r.ok) throw new Error('server answered ' + r.status + '.');
      return r.json();
    });
  }
  function ago(iso) {
    var s = Math.max(0, Math.round((Date.now() - Date.parse(iso)) / 1000));
    return s < 60 ? s + 's ago' : s < 3600 ? Math.round(s / 60) + 'm ago' : s < 86400 ? Math.round(s / 3600) + 'h ago' : Math.round(s / 86400) + 'd ago';
  }

  function run(raw) {
    var line = (raw || '').trim();
    if (!line) return;
    var sp = line.indexOf(' ');
    var name = (sp < 0 ? line : line.slice(0, sp)).toLowerCase();
    var arg = sp < 0 ? '' : line.slice(sp + 1).trim();
    var shown = name === 'unlock' && arg ? 'unlock ' + new Array(Math.min(arg.length, 12) + 1).join('•') : line;
    if (name !== 'unlock') { past.push(line); at = past.length; }
    if (name === 'clear') return cmds.clear();
    echo(shown);
    if (cmds.hasOwnProperty(name)) cmds[name](arg);
    else print([{ t: 'command not found: ' + name, cls: 'bad' }, ['Type ', hl('help'), ' for the command list.']]);
  }

  input.addEventListener('input', function () {
    input.type = /^\s*unlock\s/i.test(input.value) ? 'password' : 'text';   // hide the token as it's typed
  });
  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { run(input.value); input.value = ''; input.type = 'text'; }
    else if (e.key === 'ArrowUp' && at > 0) { e.preventDefault(); input.value = past[--at]; }
    else if (e.key === 'ArrowDown') { e.preventDefault(); at = Math.min(at + 1, past.length); input.value = past[at] || ''; }
  });
  body.addEventListener('click', function (e) {
    if (e.target.tagName !== 'A' && !window.getSelection().toString()) input.focus({ preventScroll: true });
  });
  root.querySelectorAll('[data-cmd]').forEach(function (b) {
    b.addEventListener('click', function () { run(b.getAttribute('data-cmd')); });
  });
})();
