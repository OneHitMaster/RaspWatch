(function () {
  'use strict';

  const STORAGE_KEY = 'raspwatch_settings';
  const BYTES = ['B', 'KB', 'MB', 'GB', 'TB'];
  const DEFAULT_REFRESH_MS = 3000;
  const DEFAULT_THEME = 'dark';
  var lastActiveAlerts = [];
  var notificationPermissionAsked = false;

  function formatBytes(n) {
    if (n === undefined || n === null || isNaN(n)) return '—';
    if (n === 0) return '0 B';
    var i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), BYTES.length - 1);
    return (n / Math.pow(1024, i)).toFixed(i > 1 ? 2 : 0) + ' ' + BYTES[i];
  }

  function getSettings() {
    try {
      var raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        var s = JSON.parse(raw);
        return {
          refresh_interval_sec: s.refresh_interval_sec || 3,
          theme: s.theme || 'system',
          log_lines: s.log_lines || 200,
          log_default_source: s.log_default_source || 'journal',
          lang: s.lang || (navigator.language && navigator.language.startsWith('en') ? 'en' : 'de'),
        };
      }
    } catch (e) {}
    return {
      refresh_interval_sec: 3,
      theme: 'system',
      log_lines: 200,
      log_default_source: 'journal',
      lang: navigator.language && navigator.language.startsWith('en') ? 'en' : 'de',
    };
  }

  function saveSettingsLocal(s) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    } catch (e) {}
  }

  function getEffectiveTheme(theme) {
    if (theme === 'system') {
      return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
    }
    return theme === 'light' ? 'light' : 'dark';
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', getEffectiveTheme(theme));
  }

  function applyLang(lang) {
    var t = i18n[lang] || i18n.de;
    document.querySelectorAll('[data-i18n]').forEach(function (el) {
      var key = el.getAttribute('data-i18n');
      if (t[key]) el.textContent = t[key];
    });
    var s = getSettings();
    var label = document.getElementById('refresh-label');
    if (label && s.refresh_interval_sec) label.textContent = (t.refreshLabel || 'Aktualisierung alle') + ' ' + s.refresh_interval_sec + 's';
  }

  var refreshIntervalId = null;
  var logsAutoRefreshId = null;
  var eventSource = null;

  var i18n = {
    de: {
      navDashboard: 'Dashboard',
      navStats: 'Statistiken',
      navLogs: 'Logs',
      navSettings: 'Einstellungen',
      refreshLabel: 'Aktualisierung alle',
      lastHour: 'Letzte Stunde',
      last6h: 'Letzte 6 Stunden',
      last24h: 'Letzte 24 Stunden',
      last7d: 'Letzte 7 Tage',
      update: 'Aktualisieren',
      saveLocal: 'Speichern (lokal)',
      saveServer: 'Auf Server speichern',
      settingsHint: 'Lokale Einstellungen werden im Browser gespeichert. Server-Einstellungen in',
      cpuAlert: 'CPU über Schwellwert',
      cpuLowAlert: 'CPU unter Schwellwert',
      tempAlert: 'Temperatur über Schwellwert',
      tempLowAlert: 'Temperatur unter Schwellwert',
      diskAlert: 'Speicher über Schwellwert',
      memAlert: 'RAM über Schwellwert',
      alertTriggered: 'Schwellwert überschritten',
    },
    en: {
      navDashboard: 'Dashboard',
      navStats: 'Statistics',
      navLogs: 'Logs',
      navSettings: 'Settings',
      refreshLabel: 'Refresh every',
      lastHour: 'Last hour',
      last6h: 'Last 6 hours',
      last24h: 'Last 24 hours',
      last7d: 'Last 7 days',
      update: 'Update',
      saveLocal: 'Save (local)',
      saveServer: 'Save to server',
      settingsHint: 'Local settings are stored in the browser. Server settings in',
      cpuAlert: 'CPU above threshold',
      cpuLowAlert: 'CPU below threshold',
      tempAlert: 'Temperature above threshold',
      tempLowAlert: 'Temperature below threshold',
      diskAlert: 'Disk above threshold',
      memAlert: 'RAM above threshold',
      alertTriggered: 'threshold exceeded',
    },
  };

  function setLive(ok) {
    var dot = document.getElementById('status-dot');
    if (dot) {
      dot.classList.remove('live', 'error');
      dot.classList.add(ok ? 'live' : 'error');
    }
  }

  function setBar(id, pct) {
    var bar = document.getElementById(id);
    if (!bar) return;
    var n = Math.min(100, Math.max(0, Number(pct) || 0));
    bar.style.width = n + '%';
    bar.classList.remove('high', 'critical');
    if (n >= 90) bar.classList.add('critical');
    else if (n >= 75) bar.classList.add('high');
  }

  function setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text ?? '—';
  }

  function renderStatic(data) {
    setText('hostname', data.hostname);
    setText('model', data.model);
    setText('os-release', data.os_release || '—');
    setText('cpu-model', data.cpu_model || '—');
    setText('system-kernel', data.system || '—');
  }

  function renderDynamic(data) {
    var cpu = data.cpu || {};
    var load = data.load || {};
    var mem = data.memory || {};
    var swap = data.swap || {};
    var disk = data.disk || {};
    var diskIo = data.disk_io || {};
    var temp = data.temperature || {};
    var uptime = data.uptime || {};
    var net = data.network || {};
    var volt = data.voltage || {};
    var processes = data.processes || [];

    setText('cpu-value', (cpu.usage_percent != null ? cpu.usage_percent + ' %' : '—'));
    setBar('cpu-bar', cpu.usage_percent);
    setText('load-1', load.load_1 != null ? load.load_1.toFixed(2) : '—');
    setText('load-5', load.load_5 != null ? load.load_5.toFixed(2) : '—');
    setText('load-15', load.load_15 != null ? load.load_15.toFixed(2) : '—');
    setText('cpu-cores', cpu.cores ?? '—');

    setText('mem-value', (mem.usage_percent != null ? mem.usage_percent + ' %' : '—'));
    setBar('mem-bar', mem.usage_percent);
    setText('mem-used', mem.used_mb ?? '—');
    setText('mem-total', mem.total_mb ?? '—');

    setText('swap-value', (swap.usage_percent != null ? swap.usage_percent + ' %' : '—'));
    setBar('swap-bar', swap.usage_percent);
    setText('swap-used', swap.used_mb ?? '—');
    setText('swap-total', swap.total_mb ?? '—');

    setText('disk-value', (disk.usage_percent != null ? disk.usage_percent + ' %' : '—'));
    setBar('disk-bar', disk.usage_percent);
    setText('disk-used', disk.used_gb ?? '—');
    setText('disk-total', disk.total_gb ?? '—');

    setText('disk-read', diskIo.read_mb != null ? diskIo.read_mb + ' MB' : '—');
    setText('disk-write', diskIo.write_mb != null ? diskIo.write_mb + ' MB' : '—');

    setText('temp-cpu', temp.cpu != null ? temp.cpu + ' °C' : '—');
    setText('temp-pmic', temp.pmic != null ? temp.pmic + ' °C' : '—');
    setText('temp-rp1', temp.rp1 != null ? temp.rp1 + ' °C' : '—');

    setText('uptime', uptime.formatted ?? '—');

    setText('net-rx', formatBytes(net.rx_bytes));
    setText('net-tx', formatBytes(net.tx_bytes));

    var ifaces = net.interfaces || [];
    var ifacesEl = document.getElementById('net-ifaces');
    if (ifacesEl) {
      if (ifaces.length) {
        ifacesEl.innerHTML = ifaces.slice(0, 5).map(function (i) {
          return '<div class="net-iface"><span>' + i.name + '</span> ↓' + formatBytes(i.rx_bytes) + ' ↑' + formatBytes(i.tx_bytes) + '</div>';
        }).join('');
        ifacesEl.style.display = 'block';
      } else {
        ifacesEl.style.display = 'none';
      }
    }

    var voltageBody = document.getElementById('voltage-body');
    var cardVoltage = document.getElementById('card-voltage');
    if (voltageBody && cardVoltage) {
      var volts = Object.keys(volt);
      if (volts.length === 0) {
        cardVoltage.classList.add('empty');
      } else {
        cardVoltage.classList.remove('empty');
        voltageBody.innerHTML = volts.map(function (k) {
          var v = volt[k];
          var label = k.replace(/_/g, ' ').toUpperCase();
          return '<div class="volt-row"><span>' + label + '</span><strong>' + (v != null ? v + ' V' : '—') + '</strong></div>';
        }).join('');
      }
    }

    var listEl = document.getElementById('process-list');
    if (listEl) {
      if (processes.length) {
        listEl.innerHTML = processes.slice(0, 12).map(function (p) {
          var rss = p.rss_kb ? (p.rss_kb / 1024).toFixed(1) + ' MB' : '—';
          return '<div class="process-row"><span class="proc-name" title="' + (p.comm || '') + '">' + (p.name || p.comm || '?') + '</span><span class="proc-pid">' + p.pid + '</span><span class="proc-rss">' + rss + '</span></div>';
        }).join('');
      } else {
        listEl.innerHTML = '<div class="meta">Keine Daten</div>';
      }
    }

    var alertBadge = document.getElementById('alert-badge');
    var active = data.alerts_active || [];
    if (alertBadge) {
      alertBadge.style.display = active.length ? 'inline-flex' : 'none';
      alertBadge.textContent = active.length;
    }
    var notifyNow = data.alerts_notify_now || [];
    var playSound = !!data.alerts_sound;
    if (notifyNow.length && typeof Notification !== 'undefined') {
      var t = (i18n[getSettings().lang] || i18n.de);
      var title = 'RaspWatch';
      var show = function () {
        if (playSound) playAlertSound();
        notifyNow.forEach(function (key) {
          var body = alertBody(key, data, t);
          try {
            new Notification(title, { body: body || title, tag: 'raspwatch-' + key });
          } catch (e) {}
        });
      };
      if (Notification.permission === 'granted') show();
      else if (Notification.permission === 'default' && !notificationPermissionAsked) {
        notificationPermissionAsked = true;
        Notification.requestPermission().then(function (p) { if (p === 'granted') show(); });
      }
    }
    lastActiveAlerts = active.slice ? active.slice() : [];
  }

  function alertBody(key, data, t) {
    var cpu = data.cpu && data.cpu.usage_percent;
    var temp = data.temperature && data.temperature.cpu;
    var disk = data.disk && data.disk.usage_percent;
    var mem = data.memory && data.memory.usage_percent;
    if (key === 'cpu_high') return (t.cpuAlert || 'CPU über Schwellwert') + ': ' + (cpu != null ? cpu + ' %' : '');
    if (key === 'cpu_low') return (t.cpuLowAlert || 'CPU unter Schwellwert') + ': ' + (cpu != null ? cpu + ' %' : '');
    if (key === 'temp_high') return (t.tempAlert || 'Temperatur über Schwellwert') + ': ' + (temp != null ? temp + ' °C' : '');
    if (key === 'temp_low') return (t.tempLowAlert || 'Temperatur unter Schwellwert') + ': ' + (temp != null ? temp + ' °C' : '');
    if (key === 'disk_high') return (t.diskAlert || 'Speicher über Schwellwert') + ': ' + (disk != null ? disk + ' %' : '');
    if (key === 'mem_high') return (t.memAlert || 'RAM über Schwellwert') + ': ' + (mem != null ? mem + ' %' : '');
    return key + ' ' + (t.alertTriggered || 'Schwellwert');
  }

  function playAlertSound() {
    try {
      var C = window.AudioContext || window.webkitAudioContext;
      if (!C) return;
      var ctx = new C();
      var osc = ctx.createOscillator();
      var gain = ctx.createGain();
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.frequency.value = 880;
      osc.type = 'sine';
      gain.gain.setValueAtTime(0.15, ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, ctx.currentTime + 0.2);
      osc.start(ctx.currentTime);
      osc.stop(ctx.currentTime + 0.2);
    } catch (e) {}
  }

  function updateAlertLog() {
    fetchJson('api/alerts').then(function (res) {
      var logEl = document.getElementById('alert-log');
      if (!logEl) return;
      var log = res.log || [];
      if (log.length === 0) {
        logEl.innerHTML = 'Keine Alerts.';
        return;
      }
      logEl.innerHTML = log.slice().reverse().slice(0, 10).map(function (e) {
        var t = new Date(e.ts * 1000).toLocaleTimeString();
        var cls = e.event === 'alert' ? 'alert-entry alert' : 'alert-entry resolved';
        return '<div class="' + cls + '">' + t + ' – ' + (e.message || e.type) + '</div>';
      }).join('');
    }).catch(function () {});
  }

  function fetchJson(url) {
    return fetch(url).then(function (r) {
      if (!r.ok) throw new Error(r.statusText);
      return r.json();
    });
  }

  function tick() {
    Promise.all([fetchJson('static.json'), fetchJson('dynamic.json')])
      .then(function (res) {
        renderStatic(res[0]);
        renderDynamic(res[1]);
        setLive(true);
      })
      .catch(function () { setLive(false); });
  }

  function startSSE() {
    if (eventSource || !window.EventSource) return;
    eventSource = new EventSource('api/stream');
    eventSource.onmessage = function (e) {
      try {
        var data = JSON.parse(e.data);
        renderDynamic(data);
        setLive(true);
        if (refreshIntervalId) {
          clearInterval(refreshIntervalId);
          refreshIntervalId = null;
        }
      } catch (err) {}
    };
    eventSource.onerror = function () {
      if (eventSource) {
        eventSource.close();
        eventSource = null;
      }
      if (!refreshIntervalId) applyRefreshInterval(getSettings().refresh_interval_sec);
    };
  }

  function stopSSE() {
    if (eventSource) {
      eventSource.close();
      eventSource = null;
    }
  }

  function showPage(pageId) {
    document.querySelectorAll('.page').forEach(function (p) { p.classList.remove('active'); });
    document.querySelectorAll('.nav-link').forEach(function (a) { a.classList.remove('active'); });
    var page = document.getElementById('page-' + pageId);
    var link = document.querySelector('.nav-link[data-page="' + pageId + '"]');
    if (page) page.classList.add('active');
    if (link) link.classList.add('active');
    if (pageId === 'dashboard') {
      tick();
      startSSE();
      updateAlertLog();
      if (typeof Notification !== 'undefined' && Notification.permission === 'default' && !notificationPermissionAsked) {
        fetchJson('api/settings').then(function (s) {
          if (s.alerts_enabled) {
            notificationPermissionAsked = true;
            Notification.requestPermission();
          }
        }).catch(function () {});
      }
    } else {
      stopSSE();
      if (!refreshIntervalId) applyRefreshInterval(getSettings().refresh_interval_sec);
    }
    if (pageId === 'stats') loadStats();
    if (pageId === 'logs') loadLogs();
    if (pageId === 'settings') initSettingsPage();
  }

  var chartInstances = { cpu: null, mem: null, temp: null };

  function destroyCharts() {
    ['cpu', 'mem', 'temp'].forEach(function (id) {
      var canvas = document.getElementById('chart-' + id);
      if (canvas && typeof Chart !== 'undefined') {
        var existing = Chart.getChart(canvas);
        if (existing) existing.destroy();
        chartInstances[id] = null;
      }
    });
  }

  function loadStats() {
    var period = document.getElementById('stats-period').value || '1h';
    fetchJson('api/history?period=' + encodeURIComponent(period))
      .then(function (res) {
        var data = res.data || [];
        if (data.length === 0) return;
        destroyCharts();
        var labels = data.map(function (d) {
          return new Date(d.ts * 1000).toLocaleTimeString();
        });
        var axisColor = (getComputedStyle(document.documentElement).getPropertyValue('--text-muted') || '#8b909a').trim();
        var gridColor = (getComputedStyle(document.documentElement).getPropertyValue('--border') || '#252a35').trim();
        var chartOpts = {
          responsive: true,
          maintainAspectRatio: true,
          plugins: {
            legend: { display: false, labels: { color: axisColor } },
          },
          scales: {
            x: {
              ticks: { maxTicksLimit: 12, color: axisColor, maxRotation: 45, font: { size: 11 } },
              grid: { color: gridColor },
            },
            y: {
              min: 0,
              ticks: { color: axisColor, maxTicksLimit: 8, font: { size: 11 } },
              grid: { color: gridColor },
            },
          },
          elements: { point: { radius: 0, hitRadius: 6 } },
        };
        var dsOpt = { fill: true, tension: 0.3 };
        var accent = 'rgb(56, 189, 248)';
        var cpuCanvas = document.getElementById('chart-cpu');
        if (cpuCanvas && data.some(function (d) { return d.cpu != null; })) {
          chartInstances.cpu = new Chart(cpuCanvas, {
            type: 'line',
            data: {
              labels: labels,
              datasets: [{ label: 'CPU %', data: data.map(function (d) { return d.cpu; }), borderColor: accent, backgroundColor: 'rgba(56, 189, 248, 0.1)', ...dsOpt }],
            },
            options: chartOpts,
          });
        }
        var memCanvas = document.getElementById('chart-mem');
        if (memCanvas && data.some(function (d) { return d.mem != null; })) {
          chartInstances.mem = new Chart(memCanvas, {
            type: 'line',
            data: {
              labels: labels,
              datasets: [{ label: 'Mem %', data: data.map(function (d) { return d.mem; }), borderColor: accent, backgroundColor: 'rgba(56, 189, 248, 0.1)', ...dsOpt }],
            },
            options: chartOpts,
          });
        }
        var tempCanvas = document.getElementById('chart-temp');
        if (tempCanvas && (data.some(function (d) { return d.temp_cpu != null; }) || data.some(function (d) { return d.temp_pmic != null; }) || data.some(function (d) { return d.temp_rp1 != null; }))) {
          var datasets = [];
          if (data.some(function (d) { return d.temp_cpu != null; })) {
            datasets.push({ label: 'CPU', data: data.map(function (d) { return d.temp_cpu; }), borderColor: 'rgb(56, 189, 248)', fill: false, tension: 0.3, pointRadius: 0, hitRadius: 6 });
          }
          if (data.some(function (d) { return d.temp_pmic != null; })) {
            datasets.push({ label: 'PMIC', data: data.map(function (d) { return d.temp_pmic; }), borderColor: 'rgb(252, 211, 77)', fill: false, tension: 0.3, pointRadius: 0, hitRadius: 6 });
          }
          if (data.some(function (d) { return d.temp_rp1 != null; })) {
            datasets.push({ label: 'RP1', data: data.map(function (d) { return d.temp_rp1; }), borderColor: 'rgb(134, 239, 172)', fill: false, tension: 0.3, pointRadius: 0, hitRadius: 6 });
          }
          chartInstances.temp = new Chart(tempCanvas, {
            type: 'line',
            data: { labels: labels, datasets: datasets },
            options: Object.assign({}, chartOpts, { plugins: { legend: { display: datasets.length > 1, labels: { color: axisColor } } } }),
          });
        }
      })
      .catch(function () { destroyCharts(); });
  }

  function loadLogs() {
    var source = document.getElementById('logs-source').value;
    var lines = parseInt(document.getElementById('logs-lines').value, 10) || 200;
    var content = document.getElementById('logs-content');
    var errEl = document.getElementById('logs-error');
    content.textContent = 'Lade…';
    if (errEl) errEl.textContent = '';
    fetch('api/logs?source=' + encodeURIComponent(source) + '&lines=' + lines)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        if (data.error) {
          if (errEl) errEl.textContent = data.error;
          content.textContent = '';
        } else {
          if (errEl) errEl.textContent = '';
          content.textContent = (data.lines || []).join('\n') || '(leer)';
          content.scrollTop = content.scrollHeight;
        }
      })
      .catch(function (e) {
        if (errEl) errEl.textContent = e.message || 'Fehler';
        content.textContent = '';
      });
  }

  function startLogsAutoRefresh(on) {
    if (logsAutoRefreshId) {
      clearInterval(logsAutoRefreshId);
      logsAutoRefreshId = null;
    }
    if (on) logsAutoRefreshId = setInterval(loadLogs, 5000);
  }

  function initSettingsPage() {
    var s = getSettings();
    var ref = document.getElementById('setting-refresh');
    var theme = document.getElementById('setting-theme');
    var logLines = document.getElementById('setting-log-lines');
    var langSel = document.getElementById('setting-lang');
    if (ref) ref.value = s.refresh_interval_sec;
    if (theme) theme.value = s.theme;
    if (logLines) logLines.value = s.log_lines;
    if (langSel) langSel.value = s.lang || 'de';
    applyLang(s.lang || 'de');
    fetchJson('api/settings').then(function (server) {
      function set(id, val, def) { var el = document.getElementById(id); if (el) el.value = val != null ? val : def; }
      function setCheck(id, val) { var el = document.getElementById(id); if (el) el.checked = !!val; }
      setCheck('setting-alerts-enabled', server.alerts_enabled);
      setCheck('setting-alerts-sound', server.alerts_sound !== false);
      setCheck('setting-cpu-high-enabled', server.cpu_high_enabled !== false);
      set('setting-cpu-high-value', server.cpu_high_value, 90);
      set('setting-cpu-high-interval', server.cpu_high_interval_sec, 0);
      setCheck('setting-cpu-low-enabled', server.cpu_low_enabled);
      set('setting-cpu-low-value', server.cpu_low_value, 10);
      set('setting-cpu-low-interval', server.cpu_low_interval_sec, 0);
      setCheck('setting-temp-high-enabled', server.temp_high_enabled !== false);
      set('setting-temp-high-value', server.temp_high_value, 80);
      set('setting-temp-high-interval', server.temp_high_interval_sec, 0);
      setCheck('setting-temp-low-enabled', server.temp_low_enabled);
      set('setting-temp-low-value', server.temp_low_value, 40);
      set('setting-temp-low-interval', server.temp_low_interval_sec, 5);
      setCheck('setting-disk-high-enabled', server.disk_high_enabled !== false);
      set('setting-disk-high-value', server.disk_high_value, 90);
      set('setting-disk-high-interval', server.disk_high_interval_sec, 0);
      setCheck('setting-mem-high-enabled', server.mem_high_enabled);
      set('setting-mem-high-value', server.mem_high_value, 90);
      set('setting-mem-high-interval', server.mem_high_interval_sec, 0);
      var webhook = document.getElementById('setting-webhook');
      if (webhook) webhook.value = server.webhook_url || '';
    }).catch(function () {});
  }

  function saveSettingsFromForm() {
    var ref = parseInt(document.getElementById('setting-refresh').value, 10) || 3;
    var theme = document.getElementById('setting-theme').value;
    var logLines = parseInt(document.getElementById('setting-log-lines').value, 10) || 200;
    var lang = (document.getElementById('setting-lang') && document.getElementById('setting-lang').value) || 'de';
    var s = { refresh_interval_sec: ref, theme: theme, log_lines: logLines, lang: lang };
    saveSettingsLocal(s);
    applyTheme(theme);
    applyLang(lang);
    applyRefreshInterval(ref);
    initSettingsPage();
  }

  function applyRefreshInterval(sec) {
    if (refreshIntervalId) clearInterval(refreshIntervalId);
    var ms = Math.max(1000, (sec || 3) * 1000);
    refreshIntervalId = setInterval(tick, ms);
    var t = i18n[getSettings().lang] || i18n.de;
    var label = document.getElementById('refresh-label');
    if (label) label.textContent = (t.refreshLabel || 'Aktualisierung alle') + ' ' + sec + 's';
  }

  function start() {
    var s = getSettings();
    applyTheme(s.theme);
    applyLang(s.lang || 'de');
    applyRefreshInterval(s.refresh_interval_sec);
    if (window.matchMedia) {
      window.matchMedia('(prefers-color-scheme: light)').addEventListener('change', function () {
        applyTheme(getSettings().theme);
      });
    }
    tick();

    var port = (window.location.port && window.location.port !== '80') ? window.location.port : '9090';
    var portEl = document.getElementById('port');
    if (portEl) portEl.textContent = port;

    fetchJson('api/settings').then(function (data) {
      if (data.copyright) setText('copyright', data.copyright);
    }).catch(function () {
      setText('copyright', '© 2026 TheD3vil');
    });

    window.addEventListener('hashchange', function () {
      var page = (window.location.hash || '#dashboard').slice(1) || 'dashboard';
      showPage(page);
    });
    var page = (window.location.hash || '#dashboard').slice(1) || 'dashboard';
    showPage(page);

    document.querySelectorAll('.nav-link').forEach(function (a) {
      a.addEventListener('click', function (e) {
        var p = a.getAttribute('data-page');
        if (p) showPage(p);
      });
    });

    var logsRefresh = document.getElementById('logs-refresh');
    if (logsRefresh) logsRefresh.addEventListener('click', loadLogs);
    var logsAuto = document.getElementById('logs-auto');
    if (logsAuto) logsAuto.addEventListener('change', function () { startLogsAutoRefresh(logsAuto.checked); });
    document.getElementById('logs-source').addEventListener('change', loadLogs);
    document.getElementById('logs-lines').addEventListener('change', loadLogs);

    var statsRefresh = document.getElementById('stats-refresh');
    var statsPeriod = document.getElementById('stats-period');
    if (statsRefresh) statsRefresh.addEventListener('click', loadStats);
    if (statsPeriod) statsPeriod.addEventListener('change', loadStats);
    var periodForExport = function () { return document.getElementById('stats-period') && document.getElementById('stats-period').value || '24h'; };
    var csvBtn = document.getElementById('stats-export-csv');
    var jsonBtn = document.getElementById('stats-export-json');
    if (csvBtn) csvBtn.addEventListener('click', function () { window.location.href = 'api/export/history.csv?period=' + encodeURIComponent(periodForExport()); });
    if (jsonBtn) jsonBtn.addEventListener('click', function () { window.location.href = 'api/export/history.json?period=' + encodeURIComponent(periodForExport()); });

    var saveBtn = document.getElementById('setting-save');
    if (saveBtn) saveBtn.addEventListener('click', saveSettingsFromForm);
    var saveServerBtn = document.getElementById('setting-save-server');
    if (saveServerBtn) {
      saveServerBtn.addEventListener('click', function () {
        var g = function (id) { var el = document.getElementById(id); return el ? el.value : ''; };
        var c = function (id) { var el = document.getElementById(id); return el && el.checked; };
        var n = function (id, def) { return parseInt(g(id), 10) || def; };
        var payload = {
          refresh_interval_sec: n('setting-refresh', 3),
          log_lines: n('setting-log-lines', 200),
          theme: document.getElementById('setting-theme') && document.getElementById('setting-theme').value,
          lang: (document.getElementById('setting-lang') && document.getElementById('setting-lang').value) || 'de',
          alerts_enabled: c('setting-alerts-enabled'),
          alerts_sound: c('setting-alerts-sound'),
          cpu_high_enabled: c('setting-cpu-high-enabled'),
          cpu_high_value: n('setting-cpu-high-value', 90),
          cpu_high_interval_sec: n('setting-cpu-high-interval', 0),
          cpu_low_enabled: c('setting-cpu-low-enabled'),
          cpu_low_value: n('setting-cpu-low-value', 10),
          cpu_low_interval_sec: n('setting-cpu-low-interval', 0),
          temp_high_enabled: c('setting-temp-high-enabled'),
          temp_high_value: n('setting-temp-high-value', 80),
          temp_high_interval_sec: n('setting-temp-high-interval', 0),
          temp_low_enabled: c('setting-temp-low-enabled'),
          temp_low_value: n('setting-temp-low-value', 40),
          temp_low_interval_sec: n('setting-temp-low-interval', 5),
          disk_high_enabled: c('setting-disk-high-enabled'),
          disk_high_value: n('setting-disk-high-value', 90),
          disk_high_interval_sec: n('setting-disk-high-interval', 0),
          mem_high_enabled: c('setting-mem-high-enabled'),
          mem_high_value: n('setting-mem-high-value', 90),
          mem_high_interval_sec: n('setting-mem-high-interval', 0),
          webhook_url: (document.getElementById('setting-webhook') && document.getElementById('setting-webhook').value) || '',
        };
        fetch('api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        }).then(function (r) { return r.json(); }).then(function () {
          saveSettingsFromForm();
        }).catch(function () {});
      });
    }

    initSettingsPage();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
