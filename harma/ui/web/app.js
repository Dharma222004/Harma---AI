/**
 * Harma Control Center — Frontend Client
 * Unified UI, Real-time WebSocket Event Stream, and Human-in-the-loop Controls.
 * Version: 2.0.0 (Redesign)
 */

(function () {
  'use strict';

  // --- STATE ---
  const state = {
    connected: false,
    agentStatus: 'idle',
    autonomyMode: 'supervised',
    isEmergencyStopped: false,
    activeTab: 'chat',
    interactionMode: 'chat',
    plans: [],
    confirmations: [],
    tasks: [],
    memory: [],
    integrations: [],
    devices: {},
    permissions: [],
    auditLogs: [],
    events: [],
    eventFilter: 'all',
    memoryCategory: 'all',
  };

  let ws = null;
  let reconnectTimer = null;

  // --- DOM SELECTORS ---
  const elements = {
    appLayout: document.querySelector('.app-layout'),
    sidebarToggle: document.getElementById('sidebar-toggle'),
    sidebar: document.getElementById('sidebar'),
    navBtns: document.querySelectorAll('.nav-btn'),
    panels: document.querySelectorAll('.panel'),
    globalStatusDot: document.getElementById('global-status-dot'),
    globalStatusText: document.getElementById('global-status-text'),
    autonomyModeText: document.getElementById('current-autonomy-mode'),
    emergencyBanner: document.getElementById('emergency-banner'),
    btnEmergencyStop: document.getElementById('btn-emergency-stop'),
    btnEmergencyResume: document.getElementById('btn-emergency-resume'),
    btnHeaderSettings: document.getElementById('btn-header-settings'),
    badgeConfirmations: document.getElementById('badge-confirmations'),
    badgePlans: document.getElementById('badge-plans'),
    mobileBadgeConfirmations: document.getElementById('mobile-badge-confirmations'),
    toastContainer: document.getElementById('toast-container'),

    // Chat
    chatForm: document.getElementById('chat-form'),
    chatInput: document.getElementById('chat-input'),
    chatMessages: document.getElementById('chat-messages'),
    btnSendChat: document.getElementById('btn-send-chat'),
    btnMicToggle: document.getElementById('btn-mic-toggle'),
    btnScrollBottom: document.getElementById('btn-scroll-bottom'),

    // Voice widget
    voiceStatusDot: document.getElementById('voice-status-dot'),
    voiceStatusLabel: document.getElementById('voice-status-label'),
    btnPtt: document.getElementById('btn-push-to-talk'),

    // Home screen
    homeVoiceOrb: document.getElementById('home-voice-orb'),
    homeVoiceState: document.getElementById('home-voice-state'),
    homeQuickInput: document.getElementById('home-quick-input'),
    homeSendBtn: document.getElementById('home-send-btn'),

    // Bottom Navigation & Drawer
    bottomNavBtns: document.querySelectorAll('.bottom-nav-btn'),
    btnMoreDrawer: document.getElementById('btn-more-drawer'),
    moreDrawer: document.getElementById('more-drawer'),
    moreDrawerBtns: document.querySelectorAll('.more-drawer-btn'),

    // Command Palette
    commandPaletteOverlay: document.getElementById('command-palette-overlay'),
    commandPalette: document.getElementById('command-palette'),
    commandInput: document.getElementById('command-input'),
    commandResults: document.getElementById('command-results'),
    commandItems: document.querySelectorAll('.command-item'),

    // Containers
    plansContainer: document.getElementById('plans-container'),
    confirmationsContainer: document.getElementById('confirmations-container'),
    tasksContainer: document.getElementById('tasks-container'),
    memoryContainer: document.getElementById('memory-container'),
    integrationsContainer: document.getElementById('integrations-container'),
    devicesContainer: document.getElementById('devices-container'),
    activityTimeline: document.getElementById('activity-timeline'),
    permissionsBody: document.getElementById('permissions-body'),
    healthGrid: document.getElementById('health-grid'),
    auditBody: document.getElementById('audit-body'),
    performanceContainer: document.getElementById('performance-container'),

    // Modals
    modalTask: document.getElementById('modal-task'),
    btnNewTask: document.getElementById('btn-new-task'),
    btnCloseTaskModal: document.getElementById('btn-close-task-modal'),
    btnCancelTaskModal: document.getElementById('btn-cancel-task-modal'),
    taskForm: document.getElementById('task-form'),

    modalOnboarding: document.getElementById('modal-onboarding'),
    btnStartOnboarding: document.getElementById('btn-start-onboarding'),
    btnCloseOnboarding: document.getElementById('btn-close-onboarding'),
    btnFinishOnboarding: document.getElementById('btn-finish-onboarding'),

    // Memory Search
    memorySearchInput: document.getElementById('memory-search-input'),
    btnMemorySearch: document.getElementById('btn-memory-search'),

    // Refresh buttons
    btnRefreshPlans: document.getElementById('btn-refresh-plans'),
    btnRefreshTasks: document.getElementById('btn-refresh-tasks'),
    btnRefreshIntegrations: document.getElementById('btn-refresh-integrations'),
    btnRefreshDevices: document.getElementById('btn-refresh-devices'),
    btnRefreshHealth: document.getElementById('btn-refresh-health'),
    btnRefreshAudit: document.getElementById('btn-refresh-audit'),
    btnRefreshPerf: document.getElementById('btn-refresh-perf'),
  };

  // --- NOTIFICATION TOAST ---
  function showToast(message, type = 'info') {
    if (!elements.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    elements.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 4000);
  }

  // --- WEBSOCKET CONNECTION ---
  function connectWebSocket() {
    if (ws) {
      try { ws.close(); } catch (e) {}
    }
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/harma`;

    try {
      ws = new WebSocket(wsUrl);
    } catch (e) {
      console.warn('WebSocket connection failed:', e);
      scheduleReconnect();
      return;
    }

    ws.onopen = () => {
      state.connected = true;
      updateConnectionStatus(true);
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    ws.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        handleIncomingEvent(payload);
      } catch (err) {
        console.error('Error parsing WS message:', err);
      }
    };

    ws.onclose = () => {
      state.connected = false;
      updateConnectionStatus(false);
      scheduleReconnect();
    };

    ws.onerror = () => {
      state.connected = false;
      updateConnectionStatus(false);
    };
  }

  function scheduleReconnect() {
    if (!reconnectTimer) {
      reconnectTimer = setTimeout(() => {
        reconnectTimer = null;
        connectWebSocket();
      }, 3000);
    }
  }

  function updateConnectionStatus(isOnline) {
    if (state.isEmergencyStopped) {
      if (elements.globalStatusDot) elements.globalStatusDot.className = 'status-dot paused';
      if (elements.globalStatusText) elements.globalStatusText.textContent = 'Paused';
      return;
    }
    if (isOnline) {
      if (elements.globalStatusDot) elements.globalStatusDot.className = 'status-dot online';
      if (elements.globalStatusText) elements.globalStatusText.textContent = 'Online';
    } else {
      if (elements.globalStatusDot) elements.globalStatusDot.className = 'status-dot';
      if (elements.globalStatusText) elements.globalStatusText.textContent = 'Reconnecting...';
    }
  }

  // --- EVENT HANDLER ---
  function handleIncomingEvent(event) {
    state.events.unshift(event);
    if (state.events.length > 200) state.events.pop();
    renderTimeline();

    const type = event.event_type || '';
    const payload = event.payload || {};

    if (type.startsWith('plan.')) {
      loadPlans();
    } else if (type.startsWith('confirmation.')) {
      loadConfirmations();
      if (type === 'confirmation.required') {
        showToast(`Approval Required: ${payload.action || 'Operation'}`, 'warning');
      }
    } else if (type.startsWith('task.')) {
      loadTasks();
    } else if (type.startsWith('voice.')) {
      updateVoiceWidget(type, payload);
    } else if (type.startsWith('memory.')) {
      loadMemory();
    } else if (type === 'tool.started') {
      showToast(`Executing: ${payload.tool}...`, 'info');
      if (elements.homeVoiceOrb) {
        elements.homeVoiceOrb.className = 'voice-orb state-executing';
      }
    } else if (type === 'tool.completed') {
      showToast(`Tool ${payload.tool} ${payload.success ? 'succeeded' : 'failed'}`, payload.success ? 'success' : 'warning');
      if (elements.homeVoiceOrb) {
        elements.homeVoiceOrb.className = 'voice-orb';
      }
    } else if (type === 'agent.paused') {
      setEmergencyStopped(true);
      showToast('EMERGENCY STOP ACTIVATED: All actions halted.', 'error');
    } else if (type === 'agent.resumed') {
      setEmergencyStopped(false);
      showToast('Operations resumed.', 'success');
    }
  }

  function updateVoiceWidget(type, payload) {
    const isListening = (type === 'voice.listening');
    const isSpeaking = (type === 'voice.speaking');

    // Sidebar Voice Widget
    if (elements.voiceStatusDot) {
      if (isListening) elements.voiceStatusDot.className = 'voice-status-dot listening';
      else if (isSpeaking) elements.voiceStatusDot.className = 'voice-status-dot speaking';
      else elements.voiceStatusDot.className = 'voice-status-dot';
    }
    if (elements.voiceStatusLabel) {
      if (isListening) elements.voiceStatusLabel.textContent = 'Listening...';
      else if (isSpeaking) elements.voiceStatusLabel.textContent = 'Speaking response...';
      else elements.voiceStatusLabel.textContent = 'Ready (PTT)';
    }

    // Home Screen Voice Orb
    if (elements.homeVoiceOrb) {
      if (isListening) elements.homeVoiceOrb.className = 'voice-orb state-listening';
      else if (isSpeaking) elements.homeVoiceOrb.className = 'voice-orb state-speaking';
      else elements.homeVoiceOrb.className = 'voice-orb';
    }
    if (elements.homeVoiceState) {
      if (isListening) elements.homeVoiceState.textContent = 'Listening... Speak now';
      else if (isSpeaking) elements.homeVoiceState.textContent = 'Speaking response...';
      else elements.homeVoiceState.textContent = 'Click to speak, or type below';
    }
  }

  // --- API CALL HELPERS ---
  async function apiGet(endpoint) {
    try {
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return await res.json();
    } catch (err) {
      console.error(`API GET ${endpoint} error:`, err);
      return null;
    }
  }

  async function apiPost(endpoint, data = {}) {
    try {
      const res = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return await res.json();
    } catch (err) {
      console.error(`API POST ${endpoint} error:`, err);
      return { success: false, error: err.message };
    }
  }

  async function apiPatch(endpoint, data = {}) {
    try {
      const res = await fetch(endpoint, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return await res.json();
    } catch (err) {
      console.error(`API PATCH ${endpoint} error:`, err);
      return { success: false, error: err.message };
    }
  }

  async function apiDelete(endpoint) {
    try {
      const res = await fetch(endpoint, { method: 'DELETE' });
      return await res.json();
    } catch (err) {
      console.error(`API DELETE ${endpoint} error:`, err);
      return { success: false, error: err.message };
    }
  }

  // --- LOAD INITIAL STATE ---
  async function refreshAllState() {
    const data = await apiGet('/api/state');
    if (data && data.state) {
      const s = data.state;
      state.agentStatus = s.agent_status;
      state.isEmergencyStopped = s.is_emergency_stopped;
      setEmergencyStopped(s.is_emergency_stopped);

      if (s.confirmations) {
        state.confirmations = s.confirmations;
        renderConfirmations();
      }
      if (s.current_plan) {
        state.plans = [s.current_plan];
        renderPlans();
      }
      if (s.devices) {
        state.devices = s.devices;
        renderDevices();
      }
    }
    loadConfirmations();
    loadPlans();
    loadTasks();
    loadMemory();
    loadIntegrations();
    loadDevices();
    loadPermissions();
    loadAudit();
    loadHealth();
  }

  // --- EMERGENCY STOP ---
  function setEmergencyStopped(isStopped) {
    state.isEmergencyStopped = isStopped;
    if (isStopped) {
      if (elements.emergencyBanner) elements.emergencyBanner.classList.remove('hidden');
      if (elements.globalStatusDot) elements.globalStatusDot.className = 'status-dot paused';
      if (elements.globalStatusText) elements.globalStatusText.textContent = 'Paused';
    } else {
      if (elements.emergencyBanner) elements.emergencyBanner.classList.add('hidden');
      updateConnectionStatus(state.connected);
    }
  }

  async function triggerEmergencyStop() {
    const res = await apiPost('/api/emergency-stop', { reason: 'User initiated from UI' });
    if (res.status === 'paused' || res.emergency_stopped) {
      setEmergencyStopped(true);
      showToast('Harma activity halted immediately.', 'error');
    }
  }

  async function resumeEmergencyStop() {
    const res = await apiPost('/api/emergency-resume', {});
    if (res.status === 'resumed') {
      setEmergencyStopped(false);
      showToast('Harma activity resumed.', 'success');
    }
  }

  // --- CHAT INTERACTION & MODE TOGGLE ---
  function setInteractionMode(mode) {
    state.interactionMode = mode === 'work' ? 'work' : 'chat';

    // Synchronize all segmented toggle buttons across Chat and Home
    document.querySelectorAll('.mode-pill-item').forEach(btn => {
      const isSelected = btn.dataset.mode === state.interactionMode;
      btn.classList.toggle('active', isSelected);
      btn.setAttribute('aria-selected', isSelected ? 'true' : 'false');
    });

    // Update status text badge
    const statusText = document.getElementById('mode-status-text');
    if (statusText) {
      statusText.innerHTML = '';
      statusText.style.display = 'none';
    }

    // Dynamic guidance placeholders
    if (elements.chatInput) {
      elements.chatInput.placeholder = state.interactionMode === 'chat'
        ? 'Ask anything — Harma AI is ready to help...'
        : 'Assign a task — Harma AI will plan, automate, and execute...';
    }
    if (elements.homeQuickInput) {
      elements.homeQuickInput.placeholder = state.interactionMode === 'chat'
        ? 'Ask anything to Harma AI...'
        : 'What task should Harma AI plan and execute?';
    }
  }

  function scrollToChatBottom(smooth = true) {
    if (!elements.chatMessages) return;
    elements.chatMessages.scrollTo({
      top: elements.chatMessages.scrollHeight,
      behavior: smooth ? 'smooth' : 'auto'
    });
  }

  function appendChatMessage(sender, text, type = 'normal', sources = []) {
    if (!elements.chatMessages) return;
    const msg = document.createElement('div');

    if (type === 'system') {
      msg.className = 'message system-msg';
      msg.innerHTML = `<div class="message-body">${escapeHtml(text)}</div>`;
    } else if (type === 'tool') {
      msg.className = 'message tool-msg';
      msg.innerHTML = `
        <div class="message-header">
          <span class="sender-name">TOOL EXECUTION</span>
        </div>
        <div class="message-body">${escapeHtml(text)}</div>
      `;
    } else if (sender === 'user') {
      msg.className = 'message user-msg';
      msg.innerHTML = `
        <div class="message-header">
          <span class="sender-name">You</span>
          <div class="avatar-badge user-avatar">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
          </div>
        </div>
        <div class="message-body">${escapeHtml(text)}</div>
      `;
    } else {
      msg.className = 'message harma-msg';
      let bodyHtml = formatMarkdown(text);
      if (Array.isArray(sources) && sources.length > 0) {
        bodyHtml += `<div class="chat-sources-container">` +
          sources.map(s => {
            const title = escapeHtml(s.title || s.url || 'Source');
            const url = escapeHtml(s.url || '#');
            return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="source-chip" title="${title}">🔗 ${title}</a>`;
          }).join('') +
          `</div>`;
      }
      const isChat = state.interactionMode === 'chat';
      msg.innerHTML = `
        <div class="message-header">
          <div class="avatar-badge harma-avatar">
            <img src="/static/harma-logo.png" alt="Harma AI" class="harma-avatar-img">
          </div>
          <span class="sender-name">Harma AI</span>
          <span class="sender-role-pill ${isChat ? 'live-pill' : ''}">${isChat ? 'Harma AI' : 'Agent Core'}</span>
        </div>
        <div class="message-body markdown-body">${bodyHtml}</div>
      `;
    }

    elements.chatMessages.appendChild(msg);
    scrollToChatBottom(true);
  }

  async function handleSendChat() {
    if (!elements.chatInput) return;
    const text = elements.chatInput.value.trim();
    if (!text) return;

    if (state.isEmergencyStopped) {
      showToast('Cannot send: Harma is currently paused by Emergency Stop.', 'error');
      return;
    }

    appendChatMessage('user', text);
    elements.chatInput.value = '';
    elements.chatInput.style.height = 'auto';

    // Show indicator
    const thinkingMsg = document.createElement('div');
    thinkingMsg.className = 'message harma-msg message-thinking';
    thinkingMsg.id = 'temp-thinking';
    const isChat = state.interactionMode === 'chat';
    thinkingMsg.innerHTML = `
      <div class="message-header">
        <div class="avatar-badge harma-avatar pulse-avatar">
          <img src="/static/harma-logo.png" alt="Harma AI" class="harma-avatar-img">
        </div>
        <span class="sender-name">Harma AI</span>
        <span class="sender-role-pill ${isChat ? 'live-pill' : ''}">${isChat ? 'Harma AI' : 'Agent Core'}</span>
      </div>
      <div class="message-body">
        <div class="thinking-wrapper">
          <div class="thinking-shimmer-bar"></div>
          <span class="thinking-text">${isChat ? 'Harma AI is thinking...' : 'Harma AI is planning agent tasks...'}</span>
        </div>
      </div>
    `;
    elements.chatMessages.appendChild(thinkingMsg);
    scrollToChatBottom(true);

    const res = await apiPost('/api/chat', { message: text, mode: state.interactionMode });
    const temp = document.getElementById('temp-thinking');
    if (temp) temp.remove();

    if (res && res.response && res.response.trim() !== '') {
      appendChatMessage('harma', res.response, 'normal', res.sources || []);
      if (res.plan) {
        state.plans = [res.plan];
        renderPlans();
      }
      if (res.confirmation_required) {
        showToast('Operation requires confirmation! Check Confirmations tab.', 'warning');
      }
    } else if (res && res.error) {
      appendChatMessage('system', `Error: ${res.error}`);
    } else if (res && res.success) {
      appendChatMessage('harma', 'Done! I have completed your request.');
    } else {
      appendChatMessage('system', 'No response received from Harma.');
    }
    scrollToChatBottom(true);
  }

  // --- PLANS VIEW ---
  async function loadPlans() {
    const data = await apiGet('/api/plans');
    if (data && data.plans) {
      state.plans = data.plans;
      renderPlans();
    }
  }

  function renderPlans() {
    if (!elements.plansContainer) return;
    if (!state.plans || state.plans.length === 0) {
      elements.plansContainer.innerHTML = '<div class="empty-state">No active plans executing. Ask Harma to perform a multi-step task!</div>';
      if (elements.badgePlans) elements.badgePlans.style.display = 'none';
      return;
    }

    if (elements.badgePlans) {
      elements.badgePlans.style.display = 'inline';
      elements.badgePlans.textContent = state.plans.length;
    }

    elements.plansContainer.innerHTML = state.plans.map(plan => {
      const steps = plan.steps || [];
      const completedCount = steps.filter(s => s.status === 'completed').length;
      return `
        <div class="plan-card" data-plan-id="${escapeHtml(plan.id)}">
          <div class="plan-header">
            <div>
              <h3>Goal: ${escapeHtml(plan.goal || 'Execution Plan')}</h3>
              <span class="badge ${plan.status === 'completed' ? 'badge-success' : 'badge-warning'}">Status: ${escapeHtml(plan.status || 'running')} (${completedCount}/${steps.length})</span>
            </div>
            <div class="panel-actions">
              ${plan.status === 'running' ? `<button class="btn-secondary btn-plan-pause" data-id="${escapeHtml(plan.id)}">Pause</button>` : ''}
              ${plan.status === 'paused' ? `<button class="btn-primary btn-plan-resume" data-id="${escapeHtml(plan.id)}">Resume</button>` : ''}
              ${['running', 'paused'].includes(plan.status) ? `<button class="btn-secondary btn-plan-cancel" data-id="${escapeHtml(plan.id)}">Cancel</button>` : ''}
            </div>
          </div>
          <ul class="plan-steps-list">
            ${steps.map(s => {
              let icon = '○';
              let cls = 'step-pending';
              if (s.status === 'completed') { icon = '✓'; cls = 'step-completed'; }
              else if (s.status === 'running') { icon = '●'; cls = 'step-running'; }
              else if (s.status === 'failed') { icon = '✕'; cls = 'step-failed'; }

              return `
                <li class="plan-step-item ${cls}">
                  <span class="step-indicator">${icon}</span>
                  <div class="step-details">
                    <div class="step-title">${escapeHtml(s.description || s.tool || 'Step')}</div>
                    ${s.tool ? `<div class="step-tool">Tool: <code>${escapeHtml(s.tool)}</code></div>` : ''}
                    ${s.result ? `<div class="step-result">${escapeHtml(s.result)}</div>` : ''}
                  </div>
                </li>
              `;
            }).join('')}
          </ul>
        </div>
      `;
    }).join('');

    elements.plansContainer.querySelectorAll('.btn-plan-pause').forEach(btn => {
      btn.onclick = () => apiPost(`/api/plans/${btn.dataset.id}/pause`).then(() => loadPlans());
    });
    elements.plansContainer.querySelectorAll('.btn-plan-resume').forEach(btn => {
      btn.onclick = () => apiPost(`/api/plans/${btn.dataset.id}/resume`).then(() => loadPlans());
    });
    elements.plansContainer.querySelectorAll('.btn-plan-cancel').forEach(btn => {
      btn.onclick = () => apiPost(`/api/plans/${btn.dataset.id}/cancel`).then(() => loadPlans());
    });
  }

  // --- CONFIRMATION CENTER ---
  async function loadConfirmations() {
    const data = await apiGet('/api/confirmations');
    if (data && data.confirmations) {
      state.confirmations = data.confirmations;
      renderConfirmations();
    }
  }

  function renderConfirmations() {
    if (!elements.confirmationsContainer) return;
    if (!state.confirmations || state.confirmations.length === 0) {
      elements.confirmationsContainer.innerHTML = '<div class="empty-state">No pending confirmations. Operations are running within safe parameters.</div>';
      if (elements.badgeConfirmations) elements.badgeConfirmations.style.display = 'none';
      if (elements.mobileBadgeConfirmations) elements.mobileBadgeConfirmations.style.display = 'none';
      return;
    }

    if (elements.badgeConfirmations) {
      elements.badgeConfirmations.style.display = 'inline';
      elements.badgeConfirmations.textContent = state.confirmations.length;
    }
    if (elements.mobileBadgeConfirmations) {
      elements.mobileBadgeConfirmations.style.display = 'inline';
      elements.mobileBadgeConfirmations.textContent = state.confirmations.length;
    }

    elements.confirmationsContainer.innerHTML = state.confirmations.map(c => `
      <div class="confirmation-card" data-conf-id="${escapeHtml(c.id)}">
        <div class="confirmation-header">
          <h3>Confirmation Required: ${escapeHtml(c.action)}</h3>
          <span class="confirmation-risk-badge">Risk: ${escapeHtml(c.risk_level || 'HIGH')}</span>
        </div>
        <p><strong>Target:</strong> ${escapeHtml(c.target || 'System')}</p>
        <div class="confirmation-params-box">
          <pre>${escapeHtml(JSON.stringify(c.parameters || {}, null, 2))}</pre>
        </div>
        <p style="color:var(--color-warning); font-size:12px; margin-bottom:12px;">
          ⚠️ <strong>Consequence:</strong> ${escapeHtml(c.consequences || 'Modifies persistent state or external resources.')}
        </p>
        <div class="confirmation-actions">
          <button class="btn-reject btn-conf-reject" data-id="${escapeHtml(c.id)}">Reject Action</button>
          <button class="btn-confirm btn-conf-approve" data-id="${escapeHtml(c.id)}">Approve & Execute</button>
        </div>
      </div>
    `).join('');

    elements.confirmationsContainer.querySelectorAll('.btn-conf-approve').forEach(btn => {
      btn.onclick = async () => {
        const res = await apiPost(`/api/confirmations/${btn.dataset.id}/approve`);
        if (res.success) {
          showToast('Action approved and executed.', 'success');
          loadConfirmations();
        }
      };
    });

    elements.confirmationsContainer.querySelectorAll('.btn-conf-reject').forEach(btn => {
      btn.onclick = async () => {
        const res = await apiPost(`/api/confirmations/${btn.dataset.id}/reject`);
        if (res.success) {
          showToast('Action rejected.', 'info');
          loadConfirmations();
        }
      };
    });
  }

  // --- SCHEDULED TASKS ---
  async function loadTasks() {
    const data = await apiGet('/api/tasks');
    if (data && data.tasks) {
      state.tasks = data.tasks;
      renderTasks();
    }
  }

  function renderTasks() {
    if (!elements.tasksContainer) return;
    if (!state.tasks || state.tasks.length === 0) {
      elements.tasksContainer.innerHTML = '<div class="empty-state">No scheduled tasks active. Use "+ New Task" to schedule automated routines.</div>';
      return;
    }

    elements.tasksContainer.innerHTML = state.tasks.map(t => `
      <div class="card" data-task-id="${escapeHtml(t.id)}">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:12px;">
          <h3 style="font-size:15px; font-weight:600;">${escapeHtml(t.name || 'Automated Routine')}</h3>
          <span class="badge ${t.status === 'active' ? 'badge-success' : 'badge-warning'}">${escapeHtml(t.status || 'active')}</span>
        </div>
        <p style="font-size:13px; color:var(--text-secondary); margin-bottom:12px;">${escapeHtml(t.prompt)}</p>
        <div style="font-size:12px; color:var(--text-muted); margin-bottom:12px;">
          Schedule: <strong>${escapeHtml(t.schedule_type || 'recurring')}</strong> (${escapeHtml(t.schedule_value)})
        </div>
        <div class="panel-actions" style="margin-top:12px;">
          <button class="btn-secondary btn-task-run" data-id="${escapeHtml(t.id)}">Run Now</button>
          <button class="btn-secondary btn-task-delete" data-id="${escapeHtml(t.id)}" style="color:var(--color-danger); border-color:var(--color-danger);">Delete</button>
        </div>
      </div>
    `).join('');

    elements.tasksContainer.querySelectorAll('.btn-task-run').forEach(btn => {
      btn.onclick = async () => {
        const res = await apiPost(`/api/tasks/${btn.dataset.id}/trigger`);
        if (res.success) {
          showToast('Task triggered manually!', 'success');
        }
      };
    });

    elements.tasksContainer.querySelectorAll('.btn-task-delete').forEach(btn => {
      btn.onclick = async () => {
        const res = await apiDelete(`/api/tasks/${btn.dataset.id}`);
        if (res.success) {
          showToast('Task deleted.', 'info');
          loadTasks();
        }
      };
    });
  }

  // --- MEMORY CORE ---
  async function loadMemory(query = '') {
    const endpoint = query ? `/api/memory?q=${encodeURIComponent(query)}` : '/api/memory';
    const data = await apiGet(endpoint);
    if (data && data.memory) {
      state.memory = data.memory;
      renderMemory();
    }
  }

  function renderMemory() {
    if (!elements.memoryContainer) return;
    let list = state.memory || [];
    if (state.memoryCategory && state.memoryCategory !== 'all') {
      list = list.filter(m => m.category === state.memoryCategory);
    }

    if (list.length === 0) {
      elements.memoryContainer.innerHTML = '<div class="empty-state">No matching memories in the neural core. Harma learns automatically as you chat.</div>';
      return;
    }

    elements.memoryContainer.innerHTML = list.map(m => `
      <div class="card" data-memory-id="${escapeHtml(m.id)}">
        <div style="display:flex; justify-content:space-between; margin-bottom:8px;">
          <span class="badge" style="background:var(--elevated-2); color:var(--text-secondary);">${escapeHtml(m.category || 'general')}</span>
          <span style="font-size:11px; color:var(--text-muted);">${escapeHtml(new Date(m.created_at || Date.now()).toLocaleDateString())}</span>
        </div>
        <p style="font-size:13px; line-height:1.5;">${escapeHtml(m.content || m.key_value || '')}</p>
        <div style="display:flex; justify-content:flex-end; margin-top:12px;">
          <button class="btn-secondary btn-mem-delete" data-id="${escapeHtml(m.id)}" style="font-size:11px; padding:4px 8px;">Forget</button>
        </div>
      </div>
    `).join('');

    elements.memoryContainer.querySelectorAll('.btn-mem-delete').forEach(btn => {
      btn.onclick = async () => {
        const res = await apiDelete(`/api/memory/${btn.dataset.id}`);
        if (res.success) {
          showToast('Memory forgotten.', 'info');
          loadMemory();
        }
      };
    });
  }

  // --- MCP INTEGRATIONS ---
  async function loadIntegrations() {
    const data = await apiGet('/api/integrations');
    if (data && data.integrations) {
      state.integrations = data.integrations;
      renderIntegrations();
    }
  }

  function renderIntegrations() {
    if (!elements.integrationsContainer) return;
    if (!state.integrations || state.integrations.length === 0) {
      elements.integrationsContainer.innerHTML = '<div class="empty-state">No MCP integrations configured. Add MCP servers in config.yaml.</div>';
      return;
    }

    elements.integrationsContainer.innerHTML = state.integrations.map(int => `
      <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="font-size:16px; font-weight:600;">${escapeHtml(int.name)}</h3>
          <span class="badge ${int.connected ? 'badge-success' : 'badge-warning'}">
            ${int.connected ? 'Connected' : 'Disconnected'}
          </span>
        </div>
        <p style="font-size:13px; color:var(--text-secondary); margin-bottom:12px;">
          Protocol: <strong>${escapeHtml(int.type || 'MCP STDIO')}</strong>
        </p>
        <div style="font-size:12px; color:var(--text-muted);">
          Tools provided: <strong>${int.tool_count || 0}</strong> active
        </div>
      </div>
    `).join('');
  }

  // --- CONNECTED DEVICES ---
  async function loadDevices() {
    const data = await apiGet('/api/devices');
    if (data && data.devices) {
      state.devices = data.devices;
      renderDevices();
    }
  }

  function renderDevices() {
    if (!elements.devicesContainer) return;
    const devEntries = Object.entries(state.devices || {});
    if (devEntries.length === 0) {
      elements.devicesContainer.innerHTML = '<div class="empty-state">No companion devices connected. Pair your Android phone via ADB or WebSocket client.</div>';
      return;
    }

    elements.devicesContainer.innerHTML = devEntries.map(([id, d]) => `
      <div class="card">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:12px;">
          <h3 style="font-size:16px; font-weight:600;">${escapeHtml(d.name || id)}</h3>
          <span class="badge ${d.connected ? 'badge-success' : 'badge-warning'}">
            ${d.connected ? 'Online' : 'Offline'}
          </span>
        </div>
        <p style="font-size:13px; color:var(--text-secondary);">Type: <strong>${escapeHtml(d.device_type || 'Android Mobile')}</strong></p>
        <p style="font-size:13px; color:var(--text-secondary);">Battery: <strong>${d.battery_level ? d.battery_level + '%' : 'N/A'}</strong></p>
        <p style="font-size:12px; color:var(--text-muted); margin-top:8px;">Last Active: ${escapeHtml(new Date(d.last_seen || Date.now()).toLocaleTimeString())}</p>
      </div>
    `).join('');
  }

  // --- PERMISSIONS MANAGEMENT ---
  async function loadPermissions() {
    const data = await apiGet('/api/permissions');
    if (data && data.permissions) {
      state.permissions = data.permissions;
      renderPermissions();
    }
  }

  function renderPermissions() {
    if (!elements.permissionsBody) return;
    if (!state.permissions || state.permissions.length === 0) {
      elements.permissionsBody.innerHTML = '<tr><td colspan="4" style="text-align:center;">No custom permission rules configured.</td></tr>';
      return;
    }

    elements.permissionsBody.innerHTML = state.permissions.map(p => `
      <tr>
        <td><strong>${escapeHtml(p.action_type || p.name)}</strong></td>
        <td><span class="badge ${p.risk === 'HIGH' ? 'badge-warning' : 'badge-success'}">${escapeHtml(p.risk || 'NORMAL')}</span></td>
        <td>${p.requires_approval ? 'Explicit Approval Required' : 'Autonomous execution allowed'}</td>
        <td>
          <button class="btn-secondary btn-perm-toggle" data-action="${escapeHtml(p.action_type || p.name)}" data-req="${p.requires_approval ? '0' : '1'}">
            ${p.requires_approval ? 'Allow Autonomous' : 'Enforce Approval'}
          </button>
        </td>
      </tr>
    `).join('');

    elements.permissionsBody.querySelectorAll('.btn-perm-toggle').forEach(btn => {
      btn.onclick = async () => {
        const requires = btn.dataset.req === '1';
        const res = await apiPatch('/api/permissions', {
          action_type: btn.dataset.action,
          requires_approval: requires
        });
        if (res.success) {
          showToast('Permission updated.', 'success');
          loadPermissions();
        }
      };
    });
  }

  // --- ACTIVITY TIMELINE ---
  function renderTimeline() {
    if (!elements.activityTimeline) return;
    let list = state.events || [];
    if (state.eventFilter && state.eventFilter !== 'all') {
      list = list.filter(e => {
        const type = e.event_type || '';
        if (state.eventFilter === 'voice') return type.startsWith('voice.');
        if (state.eventFilter === 'tools') return type.startsWith('tool.');
        if (state.eventFilter === 'security') return type.startsWith('confirmation.') || type.startsWith('agent.');
        return true;
      });
    }

    if (list.length === 0) {
      elements.activityTimeline.innerHTML = '<div class="empty-state">No events recorded. Operations will stream here in real time.</div>';
      return;
    }

    elements.activityTimeline.innerHTML = list.map(ev => `
      <div class="timeline-item">
        <div class="timeline-meta">
          <span>${escapeHtml(new Date(ev.timestamp || Date.now()).toLocaleTimeString())}</span>
          <span class="badge" style="font-size:10px;">${escapeHtml(ev.event_type || 'event')}</span>
        </div>
        <div class="timeline-body">
          ${escapeHtml(JSON.stringify(ev.payload || {}))}
        </div>
      </div>
    `).join('');
  }

  // --- HEALTH MONITOR ---
  async function loadHealth() {
    const data = await apiGet('/api/health');
    if (!elements.healthGrid) return;
    if (!data) {
      elements.healthGrid.innerHTML = '<div class="empty-state">Health check unavailable.</div>';
      return;
    }

    const checks = data.subsystems || {
      'AI Reasoning Engine': 'online',
      'Event Bus': 'online',
      'Voice Assistant': 'ready',
      'Task Scheduler': 'running',
      'Memory Core': 'healthy',
      'Security Guardrails': 'enforced',
    };

    elements.healthGrid.innerHTML = Object.entries(checks).map(([sub, status]) => `
      <div class="health-card">
        <div>
          <h4>${escapeHtml(sub)}</h4>
          <span style="font-size:12px; color:var(--text-muted);">Subsystem operational</span>
        </div>
        <span class="badge ${status === 'online' || status === 'healthy' || status === 'ready' || status === 'running' || status === 'enforced' ? 'badge-success' : 'badge-warning'}">
          ${escapeHtml(status)}
        </span>
      </div>
    `).join('');
  }

  // --- AUDIT HISTORY ---
  async function loadAudit() {
    const data = await apiGet('/api/audit');
    if (!elements.auditBody) return;
    if (!data || !data.audit_logs || data.audit_logs.length === 0) {
      elements.auditBody.innerHTML = '<tr><td colspan="5" style="text-align:center;">No audit records found.</td></tr>';
      return;
    }

    elements.auditBody.innerHTML = data.audit_logs.map(a => `
      <tr>
        <td>${escapeHtml(new Date(a.timestamp).toLocaleTimeString())}</td>
        <td><strong>${escapeHtml(a.action)}</strong></td>
        <td>${escapeHtml(a.target || '-')}</td>
        <td>${a.user_approved ? '✓ Approved' : 'System Auto'}</td>
        <td><span class="badge badge-success">${escapeHtml(a.outcome || 'Success')}</span></td>
      </tr>
    `).join('');
  }

  // --- TAB NAVIGATION ---
  function switchTab(tabId) {
    if (!tabId) return;
    state.activeTab = tabId;

    // Update sidebar nav buttons
    if (elements.navBtns) {
      elements.navBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId || btn.dataset.panel === tabId);
      });
    }

    // Update mobile bottom nav buttons
    if (elements.bottomNavBtns) {
      elements.bottomNavBtns.forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabId);
      });
    }

    // Update panels
    if (elements.panels) {
      elements.panels.forEach(p => {
        p.classList.toggle('active', p.id === `panel-${tabId}`);
      });
    }

    // Auto-load tab data
    if (tabId === 'performance') loadPerformance();
    else if (tabId === 'plans') loadPlans();
    else if (tabId === 'confirmations') loadConfirmations();
    else if (tabId === 'tasks') loadTasks();
    else if (tabId === 'memory') loadMemory();
    else if (tabId === 'integrations') loadIntegrations();
    else if (tabId === 'devices') loadDevices();
    else if (tabId === 'permissions') loadPermissions();
    else if (tabId === 'health') loadHealth();
    else if (tabId === 'audit') loadAudit();

    // On mobile, close sidebar & more drawer
    if (elements.sidebar && window.innerWidth <= 768) {
      elements.sidebar.classList.remove('open');
    }
    if (elements.moreDrawer) {
      elements.moreDrawer.classList.remove('open');
      if (elements.btnMoreDrawer) elements.btnMoreDrawer.setAttribute('aria-expanded', 'false');
    }
  }

  // --- UTILITIES ---
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function formatMarkdown(str) {
    if (!str) return '';

    // If marked.js is available on window, use it
    if (typeof window !== 'undefined' && window.marked && typeof window.marked.parse === 'function') {
      try {
        window.marked.setOptions({
          gfm: true,
          breaks: true
        });
        return window.marked.parse(str);
      } catch (e) {
        console.warn('marked.js parsing failed, using fallback:', e);
      }
    }

    // Comprehensive fallback Markdown parser
    return parseMarkdownFallback(str);
  }

  function parseMarkdownFallback(src) {
    if (!src) return '';

    // Extract and preserve code blocks
    const codeBlocks = [];
    let text = src.replace(/```([a-zA-Z0-9_-]*)\n([\s\S]*?)```/g, (match, lang, code) => {
      const id = `___CODE_BLOCK_${codeBlocks.length}___`;
      codeBlocks.push(`<pre><code class="language-${escapeHtml(lang)}">${escapeHtml(code.trim())}</code></pre>`);
      return id;
    });

    const lines = text.split(/\r?\n/);
    const htmlLines = [];
    let inList = false;
    let listType = null; // 'ul' or 'ol'
    let inTable = false;
    let tableHeaders = [];
    let tableRows = [];

    function closeList() {
      if (inList) {
        htmlLines.push(listType === 'ol' ? '</ol>' : '</ul>');
        inList = false;
        listType = null;
      }
    }

    function closeTable() {
      if (inTable) {
        let tableHtml = '<table>';
        if (tableHeaders.length > 0) {
          tableHtml += '<thead><tr>' + tableHeaders.map(h => `<th>${parseInline(h.trim())}</th>`).join('') + '</tr></thead>';
        }
        if (tableRows.length > 0) {
          tableHtml += '<tbody>' + tableRows.map(row => '<tr>' + row.map(cell => `<td>${parseInline(cell.trim())}</td>`).join('') + '</tr>').join('') + '</tbody>';
        }
        tableHtml += '</table>';
        htmlLines.push(tableHtml);
        inTable = false;
        tableHeaders = [];
        tableRows = [];
      }
    }

    function parseInline(line) {
      let out = escapeHtml(line);
      // Inline code
      out = out.replace(/`([^`]+)`/g, '<code>$1</code>');
      // Bold
      out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      out = out.replace(/__([^_]+)__/g, '<strong>$1</strong>');
      // Italic
      out = out.replace(/\*([^*]+)\*/g, '<em>$1</em>');
      out = out.replace(/_([^_]+)_/g, '<em>$1</em>');
      // Markdown links: [title](url)
      out = out.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
      return out;
    }

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const trimmed = line.trim();

      // Check table row
      if (trimmed.startsWith('|') && trimmed.endsWith('|')) {
        closeList();
        const cells = trimmed.slice(1, -1).split('|');
        if (cells.every(c => /^[\s:-]+$/.test(c))) {
          // separator row, skip
          continue;
        }
        if (!inTable) {
          inTable = true;
          tableHeaders = cells;
        } else {
          tableRows.push(cells);
        }
        continue;
      } else {
        closeTable();
      }

      // Check Horizontal rule
      if (/^(---|\*\*\*|___)$/.test(trimmed)) {
        closeList();
        htmlLines.push('<hr>');
        continue;
      }

      // Check Headings (# to ######)
      const hMatch = trimmed.match(/^(#{1,6})\s+(.*)$/);
      if (hMatch) {
        closeList();
        const level = hMatch[1].length;
        htmlLines.push(`<h${level}>${parseInline(hMatch[2])}</h${level}>`);
        continue;
      }

      // Check Blockquote (> )
      if (trimmed.startsWith('>')) {
        closeList();
        const qContent = trimmed.replace(/^>\s?/, '');
        htmlLines.push(`<blockquote>${parseInline(qContent)}</blockquote>`);
        continue;
      }

      // Check Unordered List (* or -)
      const ulMatch = line.match(/^(\s*)([*+-])\s+(.*)$/);
      if (ulMatch) {
        if (!inList || listType !== 'ul') {
          closeList();
          inList = true;
          listType = 'ul';
          htmlLines.push('<ul>');
        }
        htmlLines.push(`<li>${parseInline(ulMatch[3])}</li>`);
        continue;
      }

      // Check Ordered List (1. 2. etc)
      const olMatch = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
      if (olMatch) {
        if (!inList || listType !== 'ol') {
          closeList();
          inList = true;
          listType = 'ol';
          htmlLines.push('<ol>');
        }
        htmlLines.push(`<li>${parseInline(olMatch[3])}</li>`);
        continue;
      }

      // Plain line / Paragraph
      closeList();
      if (trimmed === '') {
        continue;
      }
      htmlLines.push(`<p>${parseInline(trimmed)}</p>`);
    }

    closeList();
    closeTable();

    let result = htmlLines.join('\n');
    codeBlocks.forEach((block, idx) => {
      result = result.replace(`___CODE_BLOCK_${idx}___`, block);
    });

    return result;
  }

  // --- COMMAND PALETTE ---
  function initCommandPalette() {
    const overlay = elements.commandPaletteOverlay;
    const input = elements.commandInput;
    const results = elements.commandResults;
    if (!overlay || !input || !results) return;

    function openPalette() {
      overlay.classList.remove('hidden');
      input.value = '';
      filterItems('');
      input.focus();
    }

    function closePalette() {
      overlay.classList.add('hidden');
    }

    function getVisibleItems() {
      return Array.from(results.querySelectorAll('.command-item')).filter(el => el.style.display !== 'none');
    }

    function selectIndex(index) {
      const visible = getVisibleItems();
      visible.forEach((el, i) => {
        el.classList.toggle('selected', i === index);
      });
      if (visible[index]) {
        visible[index].scrollIntoView({ block: 'nearest' });
      }
    }

    function filterItems(query) {
      const q = query.toLowerCase().trim();
      const items = results.querySelectorAll('.command-item');
      let foundFirst = false;
      items.forEach(item => {
        const text = item.textContent.toLowerCase();
        const matches = !q || text.includes(q);
        item.style.display = matches ? 'flex' : 'none';
        if (matches && !foundFirst) {
          item.classList.add('selected');
          foundFirst = true;
        } else {
          item.classList.remove('selected');
        }
      });
    }

    function executeItem(item) {
      if (!item) return;
      const action = item.dataset.action;
      const tab = item.dataset.tab;
      closePalette();

      if (action === 'nav' && tab) {
        switchTab(tab);
      } else if (action === 'emergency-stop') {
        triggerEmergencyStop();
      } else if (action === 'new-task') {
        if (elements.modalTask) elements.modalTask.classList.remove('hidden');
      }
    }

    // Input filter
    input.addEventListener('input', () => filterItems(input.value));

    // Keyboard navigation
    input.addEventListener('keydown', (e) => {
      const visible = getVisibleItems();
      const currentIndex = visible.findIndex(el => el.classList.contains('selected'));

      if (e.key === 'ArrowDown') {
        e.preventDefault();
        const next = (currentIndex + 1) % (visible.length || 1);
        selectIndex(next);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        const prev = (currentIndex - 1 + visible.length) % (visible.length || 1);
        selectIndex(prev);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        const selected = visible[currentIndex] || visible[0];
        if (selected) executeItem(selected);
      } else if (e.key === 'Escape') {
        closePalette();
      }
    });

    // Click item
    results.addEventListener('click', (e) => {
      const item = e.target.closest('.command-item');
      if (item) executeItem(item);
    });

    // Click backdrop
    overlay.addEventListener('click', (e) => {
      if (e.target === overlay) closePalette();
    });

    // Global shortcut Ctrl+K / Cmd+K / /
    window.addEventListener('keydown', (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault();
        if (overlay.classList.contains('hidden')) openPalette();
        else closePalette();
      } else if (e.key === '/' && overlay.classList.contains('hidden')) {
        const tag = (document.activeElement && document.activeElement.tagName) || '';
        if (!['INPUT', 'TEXTAREA'].includes(tag)) {
          e.preventDefault();
          openPalette();
        }
      } else if (e.key === 'Escape' && !overlay.classList.contains('hidden')) {
        closePalette();
      }
    });
  }

  // --- HOME SCREEN INTERACTION ---
  function initHomeScreen() {
    const orb = elements.homeVoiceOrb;
    const sendBtn = elements.homeSendBtn;
    const quickInput = elements.homeQuickInput;
    const voiceState = elements.homeVoiceState;

    function sendFromHome() {
      if (!quickInput) return;
      const val = quickInput.value.trim();
      if (!val) return;
      quickInput.value = '';
      quickInput.style.height = 'auto';
      switchTab('chat');
      if (elements.chatInput) {
        elements.chatInput.value = val;
      }
      handleSendChat();
    }

    if (sendBtn) {
      sendBtn.addEventListener('click', sendFromHome);
    }
    if (quickInput) {
      quickInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          sendFromHome();
        }
      });
      quickInput.addEventListener('input', () => {
        quickInput.style.height = 'auto';
        quickInput.style.height = Math.min(quickInput.scrollHeight, 120) + 'px';
      });
    }

    // Capability cards click handlers
    document.querySelectorAll('.capability-card').forEach(card => {
      card.addEventListener('click', () => {
        const prompt = card.dataset.prompt || '';
        if (quickInput) {
          quickInput.value = prompt;
          quickInput.focus();
          quickInput.style.height = 'auto';
          quickInput.style.height = Math.min(quickInput.scrollHeight, 120) + 'px';
        }
      });
    });

    // New Conversation action button
    const btnNewChat = document.getElementById('btn-new-chat');
    if (btnNewChat) {
      btnNewChat.addEventListener('click', () => {
        switchTab('chat');
        if (elements.chatMessages) {
          elements.chatMessages.innerHTML = `
            <div class="message system-msg">
              <div class="message-body">
                Harma AI reasoning core is online and ready to work. What would you like to build or accomplish?
              </div>
            </div>
          `;
        }
        if (elements.chatInput) {
          elements.chatInput.value = '';
          elements.chatInput.focus();
        }
        showToast('Started new conversation', 'info');
      });
    }

    // Voice orb click
    if (orb) {
      let isSimulating = false;
      orb.addEventListener('click', () => {
        if (isSimulating) return;
        isSimulating = true;
        updateVoiceWidget('voice.listening');
        showToast('Listening... Speak to Harma', 'info');

        setTimeout(() => {
          updateVoiceWidget('voice.speaking');
          if (voiceState) voiceState.textContent = 'Processing request...';
          setTimeout(() => {
            updateVoiceWidget('voice.ready');
            isSimulating = false;
            showToast('Voice command ready.', 'success');
          }, 2000);
        }, 2200);
      });
    }
  }

  // --- MOBILE NAVIGATION & DRAWER ---
  function initMobileNav() {
    // Bottom navigation buttons
    if (elements.bottomNavBtns) {
      elements.bottomNavBtns.forEach(btn => {
        btn.addEventListener('click', () => {
          if (btn.dataset.tab) switchTab(btn.dataset.tab);
        });
      });
    }

    // Drawer toggle
    const moreBtn = elements.btnMoreDrawer;
    const moreDrawer = elements.moreDrawer;

    if (moreBtn && moreDrawer) {
      moreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isOpen = moreDrawer.classList.toggle('open');
        moreBtn.setAttribute('aria-expanded', isOpen ? 'true' : 'false');
      });

      // Drawer options
      if (elements.moreDrawerBtns) {
        elements.moreDrawerBtns.forEach(btn => {
          btn.addEventListener('click', () => {
            if (btn.dataset.tab) switchTab(btn.dataset.tab);
            moreDrawer.classList.remove('open');
            moreBtn.setAttribute('aria-expanded', 'false');
          });
        });
      }

      // Close on outside click
      document.addEventListener('click', (e) => {
        if (!moreDrawer.contains(e.target) && e.target !== moreBtn) {
          moreDrawer.classList.remove('open');
          moreBtn.setAttribute('aria-expanded', 'false');
        }
      });
    }
  }

  // --- THEME INITIALIZATION & PERSISTENCE ---
  function initTheme() {
    const themeSelect = document.getElementById('setting-theme');
    const saved = localStorage.getItem('harma_theme');
    if (saved === 'light') {
      document.body.className = 'theme-light';
      if (themeSelect) themeSelect.value = 'light';
    } else {
      document.body.className = 'theme-dark';
      if (themeSelect) themeSelect.value = 'dark';
    }

    if (themeSelect) {
      themeSelect.addEventListener('change', (e) => {
        document.body.className = e.target.value === 'light' ? 'theme-light' : 'theme-dark';
        localStorage.setItem('harma_theme', e.target.value);
        showToast(`Theme changed to ${e.target.value}`, 'info');
      });
    }
  }

  // --- EVENT LISTENERS & SETUP ---
  function setupEventListeners() {
    // Nav buttons
    elements.navBtns.forEach(btn => {
      btn.addEventListener('click', () => switchTab(btn.dataset.tab || btn.dataset.panel));
    });

    // Mobile / Desktop sidebar toggle
    if (elements.sidebarToggle) {
      elements.sidebarToggle.addEventListener('click', () => {
        if (window.innerWidth <= 768) {
          if (elements.sidebar) elements.sidebar.classList.toggle('open');
        } else {
          if (elements.appLayout) elements.appLayout.classList.toggle('sidebar-collapsed');
        }
      });
    }

    // Emergency Stop
    if (elements.btnEmergencyStop) elements.btnEmergencyStop.addEventListener('click', triggerEmergencyStop);
    if (elements.btnEmergencyResume) elements.btnEmergencyResume.addEventListener('click', resumeEmergencyStop);

    // Settings icon
    if (elements.btnHeaderSettings) elements.btnHeaderSettings.addEventListener('click', () => switchTab('settings'));

    // Chat form submit
    if (elements.chatForm) elements.chatForm.addEventListener('submit', handleSendChat);
    if (elements.btnSendChat) {
      elements.btnSendChat.addEventListener('click', (e) => {
        e.preventDefault();
        handleSendChat();
      });
    }

    // Mode pill toggle ([Chat | ✦ Work])
    document.querySelectorAll('.mode-pill-item').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.preventDefault();
        const mode = btn.dataset.mode || 'chat';
        setInteractionMode(mode);
      });
    });
    if (elements.chatInput) {
      elements.chatInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
          e.preventDefault();
          handleSendChat();
        }
      });
      elements.chatInput.addEventListener('input', () => {
        elements.chatInput.style.height = 'auto';
        elements.chatInput.style.height = Math.min(elements.chatInput.scrollHeight, 160) + 'px';
      });
    }

    // Scroll to bottom button
    if (elements.chatMessages && elements.btnScrollBottom) {
      elements.chatMessages.addEventListener('scroll', () => {
        const threshold = 140;
        const distanceFromBottom = elements.chatMessages.scrollHeight - elements.chatMessages.scrollTop - elements.chatMessages.clientHeight;
        if (distanceFromBottom > threshold) {
          elements.btnScrollBottom.classList.remove('hidden');
        } else {
          elements.btnScrollBottom.classList.add('hidden');
        }
      });
      elements.btnScrollBottom.addEventListener('click', () => {
        scrollToChatBottom(true);
      });
    }

    // Push to talk button
    if (elements.btnPtt) {
      elements.btnPtt.addEventListener('mousedown', () => {
        updateVoiceWidget('voice.listening');
      });
      elements.btnPtt.addEventListener('mouseup', () => {
        updateVoiceWidget('voice.ready');
        showToast('Voice command recorded. Processing STT...', 'info');
      });
    }

    // Task modal
    if (elements.btnNewTask && elements.modalTask) {
      elements.btnNewTask.addEventListener('click', () => elements.modalTask.classList.remove('hidden'));
    }
    if (elements.btnCloseTaskModal && elements.modalTask) {
      elements.btnCloseTaskModal.addEventListener('click', () => elements.modalTask.classList.add('hidden'));
    }
    if (elements.btnCancelTaskModal && elements.modalTask) {
      elements.btnCancelTaskModal.addEventListener('click', () => elements.modalTask.classList.add('hidden'));
    }
    if (elements.taskForm) {
      elements.taskForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const task = {
          name: document.getElementById('task-name').value,
          prompt: document.getElementById('task-prompt').value,
          schedule_type: document.getElementById('task-schedule-type').value,
          schedule_value: document.getElementById('task-schedule-value').value,
        };
        const res = await apiPost('/api/tasks', task);
        if (res.success) {
          showToast('Scheduled task created!', 'success');
          if (elements.modalTask) elements.modalTask.classList.add('hidden');
          elements.taskForm.reset();
          loadTasks();
        }
      });
    }

    // Onboarding modal
    if (elements.btnStartOnboarding && elements.modalOnboarding) {
      elements.btnStartOnboarding.addEventListener('click', () => elements.modalOnboarding.classList.remove('hidden'));
    }
    if (elements.btnCloseOnboarding && elements.modalOnboarding) {
      elements.btnCloseOnboarding.addEventListener('click', () => elements.modalOnboarding.classList.add('hidden'));
    }
    if (elements.btnFinishOnboarding && elements.modalOnboarding) {
      elements.btnFinishOnboarding.addEventListener('click', () => {
        elements.modalOnboarding.classList.add('hidden');
        showToast('Harma setup completed successfully!', 'success');
      });
    }

    // Memory Search & Filter tabs
    if (elements.btnMemorySearch && elements.memorySearchInput) {
      elements.btnMemorySearch.addEventListener('click', () => loadMemory(elements.memorySearchInput.value.trim()));
      elements.memorySearchInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') loadMemory(elements.memorySearchInput.value.trim());
      });
    }
    document.querySelectorAll('.memory-categories-tabs .subtab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        document.querySelectorAll('.memory-categories-tabs .subtab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        state.memoryCategory = btn.dataset.category;
        loadMemory();
      });
    });

    // Activity timeline filter pills
    document.querySelectorAll('#activity-filters .filter-pill').forEach(pill => {
      pill.addEventListener('click', () => {
        document.querySelectorAll('#activity-filters .filter-pill').forEach(p => p.classList.remove('active'));
        pill.classList.add('active');
        state.eventFilter = pill.dataset.filter;
        renderTimeline();
      });
    });

    // Autonomy radio change
    document.querySelectorAll('input[name="autonomy_mode"]').forEach(radio => {
      radio.addEventListener('change', (e) => {
        const mode = e.target.value;
        if (elements.autonomyModeText) {
          elements.autonomyModeText.textContent = mode.charAt(0).toUpperCase() + mode.slice(1);
        }
        apiPatch('/api/autonomy', { mode }).then(() => showToast(`Autonomy set to ${mode}`, 'info'));
      });
    });

    // Refresh buttons
    if (elements.btnRefreshPlans) elements.btnRefreshPlans.onclick = () => loadPlans();
    if (elements.btnRefreshTasks) elements.btnRefreshTasks.onclick = () => loadTasks();
    if (elements.btnRefreshIntegrations) elements.btnRefreshIntegrations.onclick = () => loadIntegrations();
    if (elements.btnRefreshDevices) elements.btnRefreshDevices.onclick = () => loadDevices();
    if (elements.btnRefreshHealth) elements.btnRefreshHealth.onclick = () => loadHealth();
    if (elements.btnRefreshAudit) elements.btnRefreshAudit.onclick = () => loadAudit();
    if (elements.btnRefreshPerf) elements.btnRefreshPerf.onclick = () => loadPerformance();

    const perfBtn = document.getElementById('btn-refresh-perf');
    if (perfBtn) perfBtn.onclick = () => loadPerformance();
  }

  // --- PERFORMANCE DASHBOARD ---
  async function loadPerformance() {
    const container = elements.performanceContainer || document.getElementById('performance-container');
    if (!container) return;

    const data = await apiGet('/api/performance');
    if (!data || !data.performance) {
      container.innerHTML = '<p class="empty-state">No performance data yet. Send a message to Harma first.</p>';
      return;
    }

    const p = data.performance;
    if (p.total_requests === 0) {
      container.innerHTML = '<p class="empty-state">No requests recorded yet.</p>';
      return;
    }

    const tl = p.total_latency || {};
    const ll = p.llm_latency || {};
    const tol = p.tool_latency || {};
    const avg = p.per_request_avg || {};
    const traces = p.recent_traces || [];

    function ms(v) { return v != null ? `${v} ms` : 'N/A'; }
    function num(v) { return v != null ? v.toFixed(1) : 'N/A'; }

    container.innerHTML = `
      <div class="perf-stats-grid">
        <div class="perf-card">
          <div class="perf-card-title">Total Requests</div>
          <div class="perf-card-value">${p.total_requests}</div>
        </div>
        <div class="perf-card">
          <div class="perf-card-title">P50 Latency</div>
          <div class="perf-card-value">${ms(tl.p50_ms)}</div>
        </div>
        <div class="perf-card">
          <div class="perf-card-title">P95 Latency</div>
          <div class="perf-card-value">${ms(tl.p95_ms)}</div>
        </div>
        <div class="perf-card">
          <div class="perf-card-title">P99 Latency</div>
          <div class="perf-card-value">${ms(tl.p99_ms)}</div>
        </div>
        <div class="perf-card">
          <div class="perf-card-title">Avg AI Latency</div>
          <div class="perf-card-value">${ms(ll.avg_ms)}</div>
        </div>
        <div class="perf-card">
          <div class="perf-card-title">Avg Tool Latency</div>
          <div class="perf-card-value">${ms(tol.avg_ms)}</div>
        </div>
        <div class="perf-card">
          <div class="perf-card-title">AI Calls / Req</div>
          <div class="perf-card-value">${num(avg.llm_calls)}</div>
        </div>
        <div class="perf-card">
          <div class="perf-card-title">Tool Calls / Req</div>
          <div class="perf-card-value">${num(avg.tool_calls)}</div>
        </div>
        <div class="perf-card">
          <div class="perf-card-title">Screenshots / Req</div>
          <div class="perf-card-value">${num(avg.screenshots)}</div>
        </div>
        <div class="perf-card">
          <div class="perf-card-title">Avg Tokens In</div>
          <div class="perf-card-value">${num(avg.tokens_in)}</div>
        </div>
      </div>

      <div class="perf-traces-title">Recent Request Traces</div>
      <div class="perf-traces-table-wrap">
        <table class="perf-traces-table">
          <thead>
            <tr>
              <th>Request ID</th>
              <th>Total</th>
              <th>AI Reasoning</th>
              <th>Tool Exec</th>
              <th>AI Calls</th>
              <th>Tools Selected</th>
              <th>Screenshots</th>
            </tr>
          </thead>
          <tbody>
            ${traces.map(t => {
              const d = t.durations_ms || {};
              const c = t.counts || {};
              const totalClass = d.total_ms < 3000 ? 'perf-fast' : d.total_ms < 8000 ? 'perf-medium' : 'perf-slow';
              return `<tr>
                <td class="perf-req-id">${escapeHtml(t.request_id)}</td>
                <td class="${totalClass}">${d.total_ms != null ? d.total_ms + ' ms' : '-'}</td>
                <td>${d.llm_ms != null ? d.llm_ms + ' ms' : '-'}</td>
                <td>${d.tool_execution_ms != null ? d.tool_execution_ms + ' ms' : '-'}</td>
                <td>${c.llm_calls ?? '-'}</td>
                <td>${c.selected_tools ?? '-'} / ${c.total_tools ?? '-'}</td>
                <td>${c.screenshots ?? 0}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    `;
  }

  // --- INIT ---
  function init() {
    setupEventListeners();
    initMobileNav();
    initCommandPalette();
    initHomeScreen();
    initTheme();
    setInteractionMode(state.interactionMode || 'chat');
    connectWebSocket();
    refreshAllState();
  }

  window.addEventListener('DOMContentLoaded', init);
})();
