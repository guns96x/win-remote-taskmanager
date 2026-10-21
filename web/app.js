/**
 * Windows Task Manager for Android - Client Application
 */

// Application State
const state = {
  connected: false,
  activeTab: 'tab-processes',
  activeMetric: 'cpu',
  showCpuCores: false,
  sortBy: 'cpu',
  sortReverse: true,
  category: 'all',
  searchQuery: '',
  updateInterval: 1.0,
  metrics: null,
  processes: [],
  totalProcesses: 0,
  systemInfo: null,
  selectedProcess: null
};

// DOM References
const elements = {
  hostBadge: document.getElementById('host-badge'),
  liveIndicator: document.getElementById('live-indicator'),
  liveText: document.getElementById('live-text'),
  summaryCpu: document.getElementById('summary-cpu'),
  summaryRam: document.getElementById('summary-ram'),
  summaryDisk: document.getElementById('summary-disk'),
  summaryNet: document.getElementById('summary-net'),
  summaryGpu: document.getElementById('summary-gpu'),
  summaryAsusMode: document.getElementById('summary-asus-mode'),
  chipAsus: document.getElementById('chip-asus'),
  asusActiveModePill: document.getElementById('asus-active-mode-pill'),
  screenStatusPill: document.getElementById('screen-status-pill'),
  screenToggleBtn: document.getElementById('screen-toggle-btn'),
  screenBtnIcon: document.getElementById('screen-btn-icon'),
  screenBtnText: document.getElementById('screen-btn-text'),
  kbdLevelPill: document.getElementById('kbd-level-pill'),
  kbdToggleBtn: document.getElementById('kbd-toggle-btn'),
  batteryStatusPill: document.getElementById('battery-status-pill'),
  batteryPctText: document.getElementById('battery-pct-text'),
  batteryProgressBar: document.getElementById('battery-progress-bar'),
  keepawakeBadge: document.getElementById('keepawake-badge'),
  searchInput: document.getElementById('process-search-input'),
  searchClearBtn: document.getElementById('search-clear-btn'),
  processesTbody: document.getElementById('processes-tbody'),
  countAll: document.getElementById('count-all'),
  countApp: document.getElementById('count-app'),
  countBg: document.getElementById('count-bg'),
  countWin: document.getElementById('count-win'),
  mainChartCanvas: document.getElementById('main-chart-canvas'),
  mainChartWrapper: document.getElementById('main-chart-wrapper'),
  coresGridContainer: document.getElementById('cores-grid-container'),
  toggleCoresBtn: document.getElementById('toggle-cores-btn'),
  toggleCoresLabel: document.getElementById('toggle-cores-label'),
  cpuViewToggleContainer: document.getElementById('cpu-view-toggle-container'),
  detailTitle: document.getElementById('detail-title'),
  detailSubtitle: document.getElementById('detail-subtitle'),
  specsGrid: document.getElementById('specs-grid'),
  processModal: document.getElementById('process-modal'),
  confirmModal: document.getElementById('confirm-modal'),
  confirmTitle: document.getElementById('confirm-title'),
  confirmDesc: document.getElementById('confirm-desc'),
  confirmOkBtn: document.getElementById('confirm-ok-btn'),
  confirmCancelBtn: document.getElementById('confirm-cancel-btn'),
  toast: document.getElementById('toast'),
  toastMessage: document.getElementById('toast-message'),
  qrUrlText: document.getElementById('qr-url-text'),
  copyUrlBtn: document.getElementById('copy-url-btn'),
  fullSystemSpecs: document.getElementById('full-system-specs')
};

// WebSocket Handler
let ws = null;
let reconnectTimer = null;

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const wsUrl = `${protocol}//${window.location.host}/ws/live`;

  ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    state.connected = true;
    updateConnectionUI(true);
    sendClientConfig();
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      handleWsMessage(data);
    } catch (e) {
      console.error('WS parse error:', e);
    }
  };

  ws.onclose = () => {
    state.connected = false;
    updateConnectionUI(false);
    clearTimeout(reconnectTimer);
    reconnectTimer = setTimeout(connectWebSocket, 2000);
  };

  ws.onerror = (err) => {
    console.error('WS error:', err);
    ws.close();
  };
}

function sendClientConfig() {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({
      type: 'config',
      interval: state.updateInterval,
      processes_enabled: (state.activeTab === 'tab-processes'),
      sort_by: state.sortBy,
      reverse: state.sortReverse,
      search: state.searchQuery,
      category: state.category
    }));
  }
}

function updateConnectionUI(isConnected) {
  if (isConnected) {
    elements.liveIndicator.className = 'live-pill connected';
    elements.liveText.textContent = 'Наживо';
  } else {
    elements.liveIndicator.className = 'live-pill disconnected';
    elements.liveText.textContent = 'Підключення...';
  }
}

function handleWsMessage(data) {
  if (data.type === 'init') {
    state.systemInfo = data.system;
    state.metrics = data.metrics;
    state.processes = data.processes || [];
    state.totalProcesses = data.total_processes || 0;
    renderSystemInfo();
    if (data.metrics && data.metrics.asus) {
      updateAsusUI(data.metrics.asus);
    }
    updateAll();
  } else if (data.type === 'tick') {
    state.metrics = data.metrics;
    if (data.processes) {
      state.processes = data.processes;
      state.totalProcesses = data.total_processes || state.processes.length;
    }
    if (data.metrics && data.metrics.asus) {
      updateAsusUI(data.metrics.asus);
    }
    updateAll();
  } else if (data.type === 'asus_update') {
    if (data.asus) {
      updateAsusUI(data.asus);
    }
  } else if (data.type === 'asus_action_result') {
    if (data.result && data.result.success) {
      if (data.action === 'perf') {
        showToast(`Режим змінено: ${data.result.mode_name}`);
      } else if (data.action === 'keyboard' || data.action === 'keyboard_toggle') {
        showToast(`Підсвітка клавіатури: рівень ${data.result.level}`);
      } else if (data.action.startsWith('screen_')) {
        showToast(data.result.message || 'Стан екрана оновлено');
      } else if (data.action === 'hibernate') {
        showToast(data.result.message || 'Перехід у гібернацію');
      }
    } else if (data.result && data.result.error) {
      showToast(`Помилка: ${data.result.error}`);
    }
  } else if (data.type === 'kill_result') {
    if (data.result.success) {
      showToast(data.result.message);
      closeProcessModal();
    } else {
      showToast(`Помилка: ${data.result.error}`);
    }
  } else if (data.type === 'power_result') {
    if (data.result.success) {
      showToast(`Команду виконано: ${data.action}`);
    } else {
      showToast(`Помилка: ${data.result.error}`);
    }
  }
}

function updateAsusUI(asus) {
  if (!asus) return;
  state.asus = asus;

  // 1. Performance Mode Buttons & Badge
  document.querySelectorAll('.asus-mode-btn').forEach(btn => {
    const m = parseInt(btn.getAttribute('data-mode'), 10);
    if (m === asus.perf_mode_id) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  if (elements.asusActiveModePill) {
    elements.asusActiveModePill.className = `mode-pill ${asus.perf_mode_key || 'turbo'}`;
    const icon = asus.perf_mode_id === 1 ? '🚀' : (asus.perf_mode_id === 2 ? '🌿' : '⚖️');
    elements.asusActiveModePill.textContent = `${icon} ${asus.perf_mode_name}`;
  }

  if (elements.summaryAsusMode) {
    elements.summaryAsusMode.textContent = asus.perf_mode_name;
  }

  // 2. Screen Controls
  if (elements.screenStatusPill && elements.screenToggleBtn) {
    if (asus.monitor_sleeping) {
      elements.screenStatusPill.className = 'status-pill screen-off';
      elements.screenStatusPill.textContent = '💤 Екран вимкнено (ноутбук онлайн)';
      elements.screenToggleBtn.className = 'screen-btn-primary is-sleeping';
      if (elements.screenBtnIcon) elements.screenBtnIcon.textContent = '☀️';
      if (elements.screenBtnText) elements.screenBtnText.textContent = 'Увімкнути екран';
    } else {
      elements.screenStatusPill.className = 'status-pill screen-on';
      elements.screenStatusPill.textContent = '🟢 Екран увімкнено';
      elements.screenToggleBtn.className = 'screen-btn-primary';
      if (elements.screenBtnIcon) elements.screenBtnIcon.textContent = '🌙';
      if (elements.screenBtnText) elements.screenBtnText.textContent = 'Вимкнути екран (ПК онлайн)';
    }
  }

  // 3. Keyboard Backlight
  if (elements.kbdLevelPill) {
    elements.kbdLevelPill.textContent = `Рівень: ${asus.keyboard_level}`;
  }
  document.querySelectorAll('.kbd-level-btn').forEach(btn => {
    const lvl = parseInt(btn.getAttribute('data-level'), 10);
    if (lvl === asus.keyboard_level) {
      btn.classList.add('active');
    } else {
      btn.classList.remove('active');
    }
  });

  // 4. Battery & Power
  if (elements.batteryPctText) {
    elements.batteryPctText.textContent = `${asus.battery_percent}%`;
  }
  if (elements.batteryProgressBar) {
    elements.batteryProgressBar.style.width = `${Math.min(100, Math.max(0, asus.battery_percent))}%`;
  }
  if (elements.batteryStatusPill) {
    if (asus.is_charging) {
      elements.batteryStatusPill.textContent = '⚡ Заряджається';
      elements.batteryStatusPill.className = 'status-pill ac-connected';
    } else if (asus.is_ac_plugged) {
      elements.batteryStatusPill.textContent = '🔌 Підключено до мережі';
      elements.batteryStatusPill.className = 'status-pill ac-connected';
    } else {
      elements.batteryStatusPill.textContent = '🔋 Робота від батареї';
      elements.batteryStatusPill.className = 'status-pill battery-only';
    }
  }
  if (elements.keepawakeBadge) {
    elements.keepawakeBadge.textContent = asus.keep_awake_active
      ? '🛡️ Захист від засинання: Активний'
      : 'Захист вимкнено';
  }
}

function updateAll() {
  updateSummaryStrip();
  if (state.activeTab === 'tab-processes') {
    renderProcessesTable();
  } else if (state.activeTab === 'tab-performance') {
    renderPerformanceTab();
  }
}

// Summary Strip
function updateSummaryStrip() {
  if (!state.metrics) return;
  const m = state.metrics;
  elements.summaryCpu.textContent = `${Math.round(m.cpu.total)}% ${m.cpu.temp_c ? '• ' + m.cpu.temp_c + '°C' : ''}`;
  elements.summaryRam.textContent = `${Math.round(m.memory.percent)}%`;
  elements.summaryDisk.textContent = `${(m.disk.read_speed_mb + m.disk.write_speed_mb).toFixed(1)} МБ/с`;
  elements.summaryNet.textContent = `${m.network.kbps_recv > 1024 ? (m.network.mbps_recv).toFixed(1) + ' Мбіт/с' : Math.round(m.network.kbps_recv) + ' Кбіт/с'}`;
  elements.summaryGpu.textContent = `${Math.round(m.gpu.load || 0)}% • ${m.gpu.temp_c || 0}°C`;
}

// Processes Tab Rendering
function renderProcessesTable() {
  const procs = state.processes;
  const counts = { all: state.totalProcesses, app: 0, background: 0, windows: 0 };

  procs.forEach(p => {
    if (p.category in counts) counts[p.category]++;
  });

  elements.countAll.textContent = state.totalProcesses;
  elements.countApp.textContent = counts.app;
  elements.countBg.textContent = counts.background;
  elements.countWin.textContent = counts.windows;

  let filtered = procs;
  if (state.category !== 'all') {
    filtered = procs.filter(p => p.category === state.category);
  }

  if (state.searchQuery) {
    const q = state.searchQuery.toLowerCase();
    filtered = filtered.filter(p => p.name.toLowerCase().includes(q) || String(p.pid).includes(q));
  }

  const tbody = elements.processesTbody;
  let html = '';

  for (let i = 0; i < filtered.length; i++) {
    const p = filtered[i];
    const cpuHeat = getHeatClass(p.cpu, 15, 40, 75);
    const memHeat = getHeatClass(p.memory_mb, 1200, 3500, 8000);

    const initial = (p.name.charAt(0) || 'P').toUpperCase();

    html += `
      <tr class="proc-row" data-pid="${p.pid}">
        <td class="col-name">
          <div class="proc-name-cell">
            <div class="proc-icon-box">${initial}</div>
            <div class="proc-meta">
              <span class="proc-title">${escapeHtml(p.name)}</span>
              <span class="proc-sub">PID: ${p.pid}</span>
            </div>
          </div>
        </td>
        <td class="col-cpu ${cpuHeat}">${p.cpu.toFixed(1)}%</td>
        <td class="col-mem ${memHeat}">${p.memory_mb.toFixed(0)} МБ</td>
        <td class="col-disk">${p.disk_mbps > 0 ? p.disk_mbps.toFixed(1) : '0'}</td>
        <td class="col-action">
          <button class="quick-kill-btn" data-kill-pid="${p.pid}" data-name="${escapeHtml(p.name)}" title="Зняти завдання">✕</button>
        </td>
      </tr>
    `;
  }

  tbody.innerHTML = html;
}

function getHeatClass(val, medThresh, highThresh, extThresh) {
  if (val >= extThresh) return 'heat-extreme';
  if (val >= highThresh) return 'heat-high';
  if (val >= medThresh) return 'heat-med';
  return '';
}

// Performance Tab Rendering
function renderPerformanceTab() {
  if (!state.metrics) return;
  const m = state.metrics;
  const hist = m.history;

  // 1. Update Selector Cards
  document.getElementById('pcard-cpu-val').textContent = `${Math.round(m.cpu.total)}%`;
  document.getElementById('pcard-cpu-sub').textContent = `${m.cpu.temp_c ? m.cpu.temp_c + '°C • ' : ''}${m.cpu.freq_ghz.toFixed(2)} ГГц`;
  drawSparkline('mini-canvas-cpu', hist.cpu, '#0078d4', 100);

  document.getElementById('pcard-mem-val').textContent = `${Math.round(m.memory.percent)}%`;
  document.getElementById('pcard-mem-sub').textContent = `${m.memory.used_gb.toFixed(1)} / ${m.memory.total_gb.toFixed(1)} ГБ`;
  drawSparkline('mini-canvas-memory', hist.memory, '#8764b8', 100);

  const totalDiskSpeed = (m.disk.read_speed_mb + m.disk.write_speed_mb);
  document.getElementById('pcard-disk-val').textContent = `${totalDiskSpeed.toFixed(1)} МБ/с`;
  document.getElementById('pcard-disk-sub').textContent = `Ч: ${m.disk.read_speed_mb.toFixed(1)} | З: ${m.disk.write_speed_mb.toFixed(1)}`;
  drawSparkline('mini-canvas-disk', hist.disk_read, '#107c41', 50);

  document.getElementById('pcard-net-val').textContent = `${m.network.kbps_recv > 1024 ? (m.network.mbps_recv).toFixed(1) + ' Мбіт/с' : Math.round(m.network.kbps_recv) + ' Кбіт/с'}`;
  document.getElementById('pcard-net-sub').textContent = `Надісл: ${m.network.mbps_sent.toFixed(1)} Мбіт/с`;
  drawSparkline('mini-canvas-network', hist.net_in, '#ca5010', 5000);

  document.getElementById('pcard-gpu-val').textContent = `${Math.round(m.gpu.load || 0)}%`;
  document.getElementById('pcard-gpu-sub').textContent = `${m.gpu.temp_c || 0} °C • ${m.gpu.fan_rpm ? m.gpu.fan_rpm + ' RPM' : 'RTX 3050'}`;
  drawSparkline('mini-canvas-gpu', hist.gpu, '#76b900', 100);

  // 2. Render Main Detail View
  renderActiveMetricDetail();
}

function renderActiveMetricDetail() {
  const m = state.metrics;
  const metric = state.activeMetric;

  elements.cpuViewToggleContainer.style.display = (metric === 'cpu') ? 'block' : 'none';

  if (metric === 'cpu') {
    elements.detailTitle.textContent = `${Math.round(m.cpu.total)}% ${m.cpu.freq_ghz.toFixed(2)} ГГц`;
    elements.detailSubtitle.textContent = m.cpu.model;

    if (state.showCpuCores) {
      elements.mainChartWrapper.style.display = 'none';
      elements.coresGridContainer.style.display = 'grid';
      renderCoresGrid(m.cpu.per_core);
    } else {
      elements.mainChartWrapper.style.display = 'block';
      elements.coresGridContainer.style.display = 'none';
      drawMainChart(m.history.cpu, '#0078d4', 100, '%');
    }

    renderCpuSpecs(m);

  } else if (metric === 'memory') {
    elements.mainChartWrapper.style.display = 'block';
    elements.coresGridContainer.style.display = 'none';
    elements.detailTitle.textContent = `${m.memory.used_gb.toFixed(1)} / ${m.memory.total_gb.toFixed(1)} ГБ (${Math.round(m.memory.percent)}%)`;
    elements.detailSubtitle.textContent = `Доступно ${m.memory.available_gb.toFixed(1)} ГБ`;
    drawMainChart(m.history.memory, '#8764b8', 100, '%');
    renderMemorySpecs(m);

  } else if (metric === 'disk') {
    elements.mainChartWrapper.style.display = 'block';
    elements.coresGridContainer.style.display = 'none';
    const totalSpeed = (m.disk.read_speed_mb + m.disk.write_speed_mb);
    elements.detailTitle.textContent = `${totalSpeed.toFixed(1)} МБ/с`;
    elements.detailSubtitle.textContent = `Швидкість читання та запису дисків`;
    const maxVal = Math.max(50, ...m.history.disk_read, ...m.history.disk_write);
    drawMainChart(m.history.disk_read, '#107c41', maxVal, ' МБ/с');
    renderDiskSpecs(m);

  } else if (metric === 'network') {
    elements.mainChartWrapper.style.display = 'block';
    elements.coresGridContainer.style.display = 'none';
    elements.detailTitle.textContent = `Отримання: ${m.network.mbps_recv.toFixed(1)} Мбіт/с`;
    elements.detailSubtitle.textContent = `IPv4: ${m.network.ip} • Хост: ${m.network.hostname}`;
    const maxVal = Math.max(1000, ...m.history.net_in, ...m.history.net_out);
    drawMainChart(m.history.net_in, '#ca5010', maxVal, ' Кбіт/с');
    renderNetworkSpecs(m);

  } else if (metric === 'gpu') {
    elements.mainChartWrapper.style.display = 'block';
    elements.coresGridContainer.style.display = 'none';
    elements.detailTitle.textContent = `${Math.round(m.gpu.load || 0)}%`;
    elements.detailSubtitle.textContent = `${m.gpu.name || 'GPU'} • ${m.gpu.temp_c || 0} °C`;
    drawMainChart(m.history.gpu, '#76b900', 100, '%');
    renderGpuSpecs(m);
  }
}

// Specs Renderers
function renderCpuSpecs(m) {
  const uptime = formatUptime(m.cpu.uptime_sec);
  elements.specsGrid.innerHTML = `
    <div class="spec-item"><span class="spec-label">Температура ЦП</span><span class="spec-val" style="color: #ff7849;">${m.cpu.temp_c || 0} °C</span></div>
    <div class="spec-item"><span class="spec-label">Кулер ЦП</span><span class="spec-val">${m.cpu.fan_rpm || 0} RPM</span></div>
    <div class="spec-item"><span class="spec-label">Режим ASUS</span><span class="spec-val" style="color: #60cdff;">${m.cpu.perf_mode || 'Баланс'}</span></div>
    <div class="spec-item"><span class="spec-label">Швидкість</span><span class="spec-val">${m.cpu.freq_ghz.toFixed(2)} ГГц</span></div>
    <div class="spec-item"><span class="spec-label">Процеси</span><span class="spec-val">${m.cpu.processes_count}</span></div>
    <div class="spec-item"><span class="spec-label">Потоки</span><span class="spec-val">${m.cpu.threads_count || '-'}</span></div>
    <div class="spec-item"><span class="spec-label">Дескриптори</span><span class="spec-val">${m.cpu.handles_count || '-'}</span></div>
    <div class="spec-item"><span class="spec-label">Час роботи</span><span class="spec-val">${uptime}</span></div>
    <div class="spec-item"><span class="spec-label">Логічні ядра</span><span class="spec-val">${m.cpu.cores_logical}</span></div>
    <div class="spec-item"><span class="spec-label">Фізичні ядра</span><span class="spec-val">${m.cpu.cores_physical}</span></div>
  `;
}

function renderMemorySpecs(m) {
  elements.specsGrid.innerHTML = `
    <div class="spec-item"><span class="spec-label">Використано</span><span class="spec-val">${m.memory.used_gb.toFixed(1)} ГБ</span></div>
    <div class="spec-item"><span class="spec-label">Доступно</span><span class="spec-val">${m.memory.available_gb.toFixed(1)} ГБ</span></div>
    <div class="spec-item"><span class="spec-label">Загальний обсяг</span><span class="spec-val">${m.memory.total_gb.toFixed(1)} ГБ</span></div>
    <div class="spec-item"><span class="spec-label">Завантаження</span><span class="spec-val">${m.memory.percent.toFixed(1)}%</span></div>
  `;
}

function renderDiskSpecs(m) {
  let partsHtml = '';
  if (m.disk.partitions) {
    m.disk.partitions.forEach(p => {
      partsHtml += `
        <div class="spec-item">
          <span class="spec-label">${p.device} (${p.mountpoint})</span>
          <span class="spec-val">${p.used_gb} / ${p.total_gb} ГБ (${p.percent}%)</span>
        </div>
      `;
    });
  }
  elements.specsGrid.innerHTML = `
    <div class="spec-item"><span class="spec-label">Читання</span><span class="spec-val">${m.disk.read_speed_mb.toFixed(1)} МБ/с</span></div>
    <div class="spec-item"><span class="spec-label">Запис</span><span class="spec-val">${m.disk.write_speed_mb.toFixed(1)} МБ/с</span></div>
    ${partsHtml}
  `;
}

function renderNetworkSpecs(m) {
  elements.specsGrid.innerHTML = `
    <div class="spec-item"><span class="spec-label">Отримано</span><span class="spec-val">${m.network.mbps_recv.toFixed(2)} Мбіт/с</span></div>
    <div class="spec-item"><span class="spec-label">Відправлено</span><span class="spec-val">${m.network.mbps_sent.toFixed(2)} Мбіт/с</span></div>
    <div class="spec-item"><span class="spec-label">IPv4 Адреса</span><span class="spec-val">${m.network.ip}</span></div>
    <div class="spec-item"><span class="spec-label">Ім'я комп'ютера</span><span class="spec-val">${m.network.hostname}</span></div>
  `;
}

function renderGpuSpecs(m) {
  const g = m.gpu;
  elements.specsGrid.innerHTML = `
    <div class="spec-item"><span class="spec-label">Модель GPU</span><span class="spec-val" style="color:#60cdff;">${g.name || 'NVIDIA GeForce RTX 3050 Laptop GPU'}</span></div>
    <div class="spec-item"><span class="spec-label">Температура GPU</span><span class="spec-val" style="color:#76b900;">${g.temp_c || 0} °C</span></div>
    <div class="spec-item"><span class="spec-label">Кулер GPU</span><span class="spec-val">${g.fan_rpm || 0} RPM</span></div>
    <div class="spec-item"><span class="spec-label">Навантаження 3D</span><span class="spec-val">${g.load ? g.load.toFixed(0) : '0'}%</span></div>
    <div class="spec-item"><span class="spec-label">Пам'ять GPU</span><span class="spec-val">${g.memory_used_mb ? (g.memory_used_mb / 1024).toFixed(1) : 0} / ${g.memory_total_mb ? (g.memory_total_mb / 1024).toFixed(1) : 4.0} ГБ</span></div>
    <div class="spec-item"><span class="spec-label">Версія драйвера</span><span class="spec-val">${g.driver || 'N/A'}</span></div>
  `;
}

// Multi-Core Grid
function renderCoresGrid(perCore) {
  const container = elements.coresGridContainer;
  if (!perCore || !perCore.length) return;

  if (container.children.length !== perCore.length) {
    container.innerHTML = '';
    perCore.forEach((val, idx) => {
      const cell = document.createElement('div');
      cell.className = 'core-cell';
      cell.innerHTML = `
        <span class="core-title">ЦП ${idx}: <b id="core-val-${idx}">0%</b></span>
        <canvas id="core-canvas-${idx}" class="core-canvas" width="80" height="40"></canvas>
      `;
      container.appendChild(cell);
    });
  }

  perCore.forEach((val, idx) => {
    const valEl = document.getElementById(`core-val-${idx}`);
    if (valEl) valEl.textContent = `${Math.round(val)}%`;
    drawSparkline(`core-canvas-${idx}`, [val], '#0078d4', 100);
  });
}

// High-Precision Canvas Chart Rendering (Windows 11 Fluent style)
function drawMainChart(history, colorHex, maxVal, unit) {
  const canvas = elements.mainChartCanvas;
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = rect.width;
  const h = rect.height;

  canvas.width = w * dpr;
  canvas.height = h * dpr;

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  // Background clear
  ctx.fillStyle = '#141414';
  ctx.fillRect(0, 0, w, h);

  // 10x10 Grid Lines
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
  ctx.lineWidth = 1;

  for (let i = 1; i < 10; i++) {
    const y = (h / 10) * i;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(w, y);
    ctx.stroke();

    const x = (w / 10) * i;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, h);
    ctx.stroke();
  }

  if (!history || history.length === 0) return;

  const points = history;
  const n = points.length;
  const dx = w / (n - 1 || 1);

  // Gradient under curve
  const grad = ctx.createLinearGradient(0, 0, 0, h);
  grad.addColorStop(0, hexToRgba(colorHex, 0.35));
  grad.addColorStop(1, hexToRgba(colorHex, 0.0));

  ctx.beginPath();
  ctx.moveTo(0, h);

  for (let i = 0; i < n; i++) {
    const val = Math.max(0, Math.min(maxVal, points[i]));
    const norm = val / maxVal;
    const x = i * dx;
    const y = h - (norm * h);
    if (i === 0) ctx.lineTo(x, y);
    else ctx.lineTo(x, y);
  }

  ctx.lineTo(w, h);
  ctx.closePath();
  ctx.fillStyle = grad;
  ctx.fill();

  // Solid Curve Stroke
  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const val = Math.max(0, Math.min(maxVal, points[i]));
    const norm = val / maxVal;
    const x = i * dx;
    const y = h - (norm * h);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }

  ctx.strokeStyle = colorHex;
  ctx.lineWidth = 2;
  ctx.lineJoin = 'round';
  ctx.stroke();
}

function drawSparkline(canvasId, points, colorHex, maxVal) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;

  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = rect.width || 100;
  const h = rect.height || 30;

  canvas.width = w * dpr;
  canvas.height = h * dpr;

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  ctx.clearRect(0, 0, w, h);

  if (!points || !points.length) return;

  const n = points.length;
  const dx = w / (n - 1 || 1);

  ctx.beginPath();
  ctx.moveTo(0, h);

  for (let i = 0; i < n; i++) {
    const norm = Math.max(0, Math.min(maxVal, points[i])) / maxVal;
    const x = i * dx;
    const y = h - (norm * h);
    ctx.lineTo(x, y);
  }

  ctx.lineTo(w, h);
  ctx.closePath();
  ctx.fillStyle = hexToRgba(colorHex, 0.25);
  ctx.fill();

  ctx.beginPath();
  for (let i = 0; i < n; i++) {
    const norm = Math.max(0, Math.min(maxVal, points[i])) / maxVal;
    const x = i * dx;
    const y = h - (norm * h);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.strokeStyle = colorHex;
  ctx.lineWidth = 1.5;
  ctx.stroke();
}

// Helpers
function hexToRgba(hex, alpha) {
  const r = parseInt(hex.slice(1, 3), 16) || 0;
  const g = parseInt(hex.slice(3, 5), 16) || 0;
  const b = parseInt(hex.slice(5, 7), 16) || 0;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function formatUptime(sec) {
  const days = Math.floor(sec / 86400);
  const hours = Math.floor((sec % 86400) / 3600);
  const mins = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (days > 0) return `${days}д ${hours}:${pad(mins)}:${pad(s)}`;
  return `${hours}:${pad(mins)}:${pad(s)}`;
}

function pad(n) {
  return String(n).padStart(2, '0');
}

function escapeHtml(str) {
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function showToast(msg) {
  elements.toastMessage.textContent = msg;
  elements.toast.style.display = 'block';
  setTimeout(() => {
    elements.toast.style.display = 'none';
  }, 2800);
}

// Process Modal & Actions
function openProcessModal(pid) {
  const proc = state.processes.find(p => p.pid === pid);
  if (!proc) return;

  state.selectedProcess = proc;
  document.getElementById('modal-proc-name').textContent = proc.name;
  document.getElementById('modal-proc-pid').textContent = `PID: ${proc.pid} • ${proc.category.toUpperCase()}`;
  document.getElementById('modal-proc-cpu').textContent = `${proc.cpu.toFixed(1)}%`;
  document.getElementById('modal-proc-ram').textContent = `${proc.memory_mb.toFixed(0)} МБ`;
  document.getElementById('modal-proc-disk').textContent = `${proc.disk_mbps.toFixed(1)} МБ/с`;
  document.getElementById('modal-proc-user').textContent = proc.username || '-';
  document.getElementById('modal-proc-status').textContent = proc.status;
  document.getElementById('modal-proc-exe').textContent = proc.exe || 'Системний шлях недоступний';

  const killBtn = document.getElementById('modal-kill-btn');
  if (proc.is_critical) {
    killBtn.disabled = true;
    killBtn.textContent = 'Критичний системний процес';
    killBtn.style.opacity = '0.5';
  } else {
    killBtn.disabled = false;
    killBtn.textContent = 'Зняти завдання';
    killBtn.style.opacity = '1';
  }

  elements.processModal.style.display = 'flex';
}

function closeProcessModal() {
  elements.processModal.style.display = 'none';
  state.selectedProcess = null;
}

function killSelectedProcess(force = false) {
  if (!state.selectedProcess) return;
  const pid = state.selectedProcess.pid;
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify({ type: 'kill', pid: pid, force: force }));
  }
}

// Confirmation Dialog
function showConfirmDialog(title, desc, onOk) {
  elements.confirmTitle.textContent = title;
  elements.confirmDesc.textContent = desc;
  elements.confirmModal.style.display = 'flex';

  const handleOk = () => {
    elements.confirmModal.style.display = 'none';
    elements.confirmOkBtn.removeEventListener('click', handleOk);
    elements.confirmCancelBtn.removeEventListener('click', handleCancel);
    onOk();
  };

  const handleCancel = () => {
    elements.confirmModal.style.display = 'none';
    elements.confirmOkBtn.removeEventListener('click', handleOk);
    elements.confirmCancelBtn.removeEventListener('click', handleCancel);
  };

  elements.confirmOkBtn.addEventListener('click', handleOk);
  elements.confirmCancelBtn.addEventListener('click', handleCancel);
}

// System Specs Rendering
function renderSystemInfo() {
  if (!state.systemInfo) return;
  const s = state.systemInfo;
  elements.hostBadge.textContent = `Tailscale: ${s.tailscale_ip || s.local_ip}`;
  const fullUrl = `http://${s.tailscale_ip || s.local_ip}:${window.location.port || '8899'}`;
  elements.qrUrlText.textContent = fullUrl;

  elements.fullSystemSpecs.innerHTML = `
    <div class="spec-line"><span class="spec-line-k">Комп'ютер</span><span class="spec-line-v">${s.hostname}</span></div>
    <div class="spec-line"><span class="spec-line-k">Мережа</span><span class="spec-line-v">Tailscale VPN (Зашифровано)</span></div>
    <div class="spec-line"><span class="spec-line-k">Tailscale IP</span><span class="spec-line-v">${s.tailscale_ip || s.local_ip}</span></div>
    <div class="spec-line"><span class="spec-line-k">Процесор</span><span class="spec-line-v">${s.cpu_model}</span></div>
    <div class="spec-line"><span class="spec-line-k">Логічні ядра</span><span class="spec-line-v">${s.cores_logical}</span></div>
    <div class="spec-line"><span class="spec-line-k">Фізичні ядра</span><span class="spec-line-v">${s.cores_physical}</span></div>
  `;
}

// Setup Event Listeners
function setupEventListeners() {
  // Bottom Nav
  document.querySelectorAll('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

      btn.classList.add('active');
      const tabId = btn.getAttribute('data-tab');
      document.getElementById(tabId).classList.add('active');
      state.activeTab = tabId;

      sendClientConfig();
      updateAll();
    });
  });

  // Category Pills
  document.querySelectorAll('.cat-pill').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.cat-pill').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.category = btn.getAttribute('data-cat');
      sendClientConfig();
      renderProcessesTable();
    });
  });

  // Table Column Sort
  document.querySelectorAll('.processes-table th.sortable').forEach(th => {
    th.addEventListener('click', () => {
      const sortKey = th.getAttribute('data-sort');
      if (state.sortBy === sortKey) {
        state.sortReverse = !state.sortReverse;
      } else {
        state.sortBy = sortKey;
        state.sortReverse = (sortKey !== 'name');
      }

      document.querySelectorAll('.processes-table th').forEach(h => {
        h.classList.remove('active');
        const arrow = h.querySelector('.sort-indicator');
        if (arrow) arrow.textContent = '';
      });

      th.classList.add('active');
      const arrow = th.querySelector('.sort-indicator');
      if (arrow) arrow.textContent = state.sortReverse ? '▼' : '▲';

      sendClientConfig();
    });
  });

  // Search Input
  elements.searchInput.addEventListener('input', (e) => {
    state.searchQuery = e.target.value.trim();
    elements.searchClearBtn.style.display = state.searchQuery ? 'block' : 'none';
    sendClientConfig();
    renderProcessesTable();
  });

  elements.searchClearBtn.addEventListener('click', () => {
    elements.searchInput.value = '';
    state.searchQuery = '';
    elements.searchClearBtn.style.display = 'none';
    sendClientConfig();
    renderProcessesTable();
  });

  // Table Row Tap / Quick Kill
  elements.processesTbody.addEventListener('click', (e) => {
    const killBtn = e.target.closest('.quick-kill-btn');
    if (killBtn) {
      e.stopPropagation();
      const pid = parseInt(killBtn.getAttribute('data-kill-pid'), 10);
      const name = killBtn.getAttribute('data-name');
      showConfirmDialog('Зняти завдання?', `Завершити процес ${name} (PID: ${pid})?`, () => {
        if (ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'kill', pid: pid, force: false }));
        }
      });
      return;
    }

    const row = e.target.closest('.proc-row');
    if (row) {
      const pid = parseInt(row.getAttribute('data-pid'), 10);
      openProcessModal(pid);
    }
  });

  // Modal Actions
  document.getElementById('modal-close-btn').addEventListener('click', closeProcessModal);
  document.getElementById('modal-kill-btn').addEventListener('click', () => {
    if (state.selectedProcess) {
      killSelectedProcess(false);
    }
  });

  elements.processModal.addEventListener('click', (e) => {
    if (e.target === elements.processModal) closeProcessModal();
  });

  // Performance Cards Selection
  document.querySelectorAll('.perf-card').forEach(card => {
    card.addEventListener('click', () => {
      document.querySelectorAll('.perf-card').forEach(c => c.classList.remove('active'));
      card.classList.add('active');
      state.activeMetric = card.getAttribute('data-metric');
      renderActiveMetricDetail();
    });
  });

  // Toggle CPU Cores View
  elements.toggleCoresBtn.addEventListener('click', () => {
    state.showCpuCores = !state.showCpuCores;
    elements.toggleCoresBtn.classList.toggle('active', state.showCpuCores);
    elements.toggleCoresLabel.textContent = state.showCpuCores ? 'Загальний графік' : 'Логічні ядра (16)';
    renderActiveMetricDetail();
  });

  // Power Actions
  document.querySelectorAll('.power-card').forEach(card => {
    card.addEventListener('click', () => {
      const act = card.getAttribute('data-power');
      if (act === 'lock') {
        sendPower(act);
      } else if (act === 'sleep') {
        showConfirmDialog('Перевести ПК у режим сну?', 'Комп\'ютер перейде в сплячий режим.', () => sendPower(act));
      } else if (act === 'hibernate') {
        showConfirmDialog('Перевести ПК у глибоку гібернацію?', 'Стан системи збережеться на SSD, комп\'ютер повністю вимкнеться (S4).', () => {
          if (ws && ws.readyState === WebSocket.OPEN) {
            ws.send(JSON.stringify({ type: 'asus_hibernate' }));
          }
        });
      } else if (act === 'restart') {
        showConfirmDialog('Перезавантажити ПК?', 'Комп\'ютер перезапуститься через 5 секунд.', () => sendPower(act));
      } else if (act === 'shutdown') {
        showConfirmDialog('Вимкнути ПК?', 'Комп\'ютер завершить роботу через 5 секунд.', () => sendPower(act));
      }
    });
  });

  function sendPower(action) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'power', action: action }));
    }
  }

  // ASUS TUF Hardware Actions
  document.querySelectorAll('.asus-mode-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = parseInt(btn.getAttribute('data-mode'), 10);
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'asus_perf', mode: mode }));
      }
    });
  });

  if (elements.screenToggleBtn) {
    elements.screenToggleBtn.addEventListener('click', () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'asus_screen', action: 'toggle' }));
      }
    });
  }

  document.querySelectorAll('.kbd-level-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const lvl = parseInt(btn.getAttribute('data-level'), 10);
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'asus_keyboard', level: lvl }));
      }
    });
  });

  if (elements.kbdToggleBtn) {
    elements.kbdToggleBtn.addEventListener('click', () => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'asus_keyboard_toggle' }));
      }
    });
  }

  if (elements.chipAsus) {
    elements.chipAsus.addEventListener('click', () => {
      document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      const powerNav = document.querySelector('.nav-item[data-tab="tab-power"]');
      if (powerNav) powerNav.classList.add('active');
      const powerTab = document.getElementById('tab-power');
      if (powerTab) powerTab.classList.add('active');
      state.activeTab = 'tab-power';
      sendClientConfig();
      updateAll();
    });
  }

  // Update Rate Buttons
  document.querySelectorAll('.rate-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.rate-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.updateInterval = parseFloat(btn.getAttribute('data-rate'));
      sendClientConfig();
      showToast(`Інтервал оновлення: ${state.updateInterval} сек`);
    });
  });

  // Copy QR URL
  elements.copyUrlBtn.addEventListener('click', () => {
    const url = elements.qrUrlText.textContent;
    navigator.clipboard.writeText(url).then(() => {
      showToast('Посилання скопійовано!');
    }).catch(() => {
      showToast('Не вдалося скопіювати посилання');
    });
  });

  // Window resize re-renders charts
  window.addEventListener('resize', () => {
    if (state.activeTab === 'tab-performance') {
      renderActiveMetricDetail();
    }
  });
}

// Service Worker Registration for PWA
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js').catch(err => {
      console.log('SW registration error:', err);
    });
  });
}

// Start Application
document.addEventListener('DOMContentLoaded', () => {
  setupEventListeners();
  connectWebSocket();
});
