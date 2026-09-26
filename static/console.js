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
    ['clear', 'clear the screen']
  ];

  var cmds = {
    help: function () {
      print(['Available commands:'].concat(HELP.map(function (h) {
        return [' • ', hl(pad(h[0], 12)), h[1]];
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
        ['RSS      ', { t: '/feed.xml', href: '/feed.xml' }],
        ['ABOUT    ', { t: '/about', href: '/about' }]
      ]);
    },
    clear: function () { hist.textContent = ''; }
  };

  function run(raw) {
    var line = (raw || '').trim();
    if (!line) return;
    past.push(line); at = past.length;
    var sp = line.indexOf(' ');
    var name = (sp < 0 ? line : line.slice(0, sp)).toLowerCase();
    var arg = sp < 0 ? '' : line.slice(sp + 1).trim();
    if (name === 'clear') return cmds.clear();
    echo(line);
    if (cmds.hasOwnProperty(name)) cmds[name](arg);
    else print([{ t: 'command not found: ' + name, cls: 'bad' }, ['Type ', hl('help'), ' for the command list.']]);
  }

  input.addEventListener('keydown', function (e) {
    if (e.key === 'Enter') { run(input.value); input.value = ''; }
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
