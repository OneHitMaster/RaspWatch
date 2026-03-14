(function () {
  'use strict';

  const STORAGE_KEY = 'rpimonitor_settings';
  const BYTES = ['B', 'KB', 'MB', 'GB', 'TB'];
  const DEFAULT_REFRESH_MS = 3000;
  const DEFAULT_THEME = 'dark';

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
          theme: s.theme || DEFAULT_THEME,
          log_lines: s.log_lines || 200,
          log_default_source: s.log_default_source || 'journal',
        };
      }
    } catch (e) {}
    return {
      refresh_interval_sec: 3,
      theme: DEFAULT_THEME,
      log_lines: 200,
      log_default_source: 'journal',
    };
  }

  function saveSettingsLocal(s) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(s));
    } catch (e) {}
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme === 'light' ? 'light' : 'dark');
  }

  var refreshIntervalId = null;
  var logsAutoRefreshId = null;

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

  function showPage(pageId) {
    document.querySelectorAll('.page').forEach(function (p) { p.classList.remove('active'); });
    document.querySelectorAll('.nav-link').forEach(function (a) { a.classList.remove('active'); });
    var page = document.getElementById('page-' + pageId);
    var link = document.querySelector('.nav-link[data-page="' + pageId + '"]');
    if (page) page.classList.add('active');
    if (link) link.classList.add('active');
    if (pageId === 'dashboard') tick();
    if (pageId === 'logs') loadLogs();
    if (pageId === 'settings') initSettingsPage();
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
    if (ref) ref.value = s.refresh_interval_sec;
    if (theme) theme.value = s.theme;
    if (logLines) logLines.value = s.log_lines;
  }

  function saveSettingsFromForm() {
    var ref = parseInt(document.getElementById('setting-refresh').value, 10) || 3;
    var theme = document.getElementById('setting-theme').value;
    var logLines = parseInt(document.getElementById('setting-log-lines').value, 10) || 200;
    var s = { refresh_interval_sec: ref, theme: theme, log_lines: logLines };
    saveSettingsLocal(s);
    applyTheme(theme);
    applyRefreshInterval(ref);
    initSettingsPage();
  }

  function applyRefreshInterval(sec) {
    if (refreshIntervalId) clearInterval(refreshIntervalId);
    var ms = Math.max(1000, (sec || 3) * 1000);
    refreshIntervalId = setInterval(tick, ms);
    var label = document.getElementById('refresh-label');
    if (label) label.textContent = 'Aktualisierung alle ' + sec + 's';
  }

  function start() {
    var s = getSettings();
    applyTheme(s.theme);
    applyRefreshInterval(s.refresh_interval_sec);
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

    var saveBtn = document.getElementById('setting-save');
    if (saveBtn) saveBtn.addEventListener('click', saveSettingsFromForm);
    var saveServerBtn = document.getElementById('setting-save-server');
    if (saveServerBtn) {
      saveServerBtn.addEventListener('click', function () {
        var ref = parseInt(document.getElementById('setting-refresh').value, 10) || 3;
        var theme = document.getElementById('setting-theme').value;
        var logLines = parseInt(document.getElementById('setting-log-lines').value, 10) || 200;
        fetch('api/settings', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_interval_sec: ref, log_lines: logLines, theme: theme }),
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
