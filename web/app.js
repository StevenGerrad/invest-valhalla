// ── 状态 ──────────────────────────────────────────
const state = {
  sessionId: localStorage.getItem('valhalla_session') || null,
  sessions: JSON.parse(localStorage.getItem('valhalla_sessions') || '{}'),
  isProcessing: false,
  activeSources: [],
};

// ── DOM ────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const messageList = $('#message-list');
const userInput = $('#user-input');
const btnSend = $('#btn-send');
const btnNewChat = $('#btn-new-chat');
const sessionList = $('#session-list');
const statsInfo = $('#stats-info');

// ── 初始化 ─────────────────────────────────────────
function init() {
  renderSessions();
  renderWelcome();
  loadStats();
  btnSend.addEventListener('click', sendMessage);
  userInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  btnNewChat.addEventListener('click', newChat);
}

function renderWelcome() {
  messageList.innerHTML = `
    <div class="welcome">
      <h1>💎 史诗级韭菜</h1>
      <p>一个大学生，风控专业，10万元本金开始炒股。<br>自称"韭菜"，倡导价值投资。</p>
      <div class="suggestions">
        <button onclick="askSuggestion('PE估值是什么？')">PE估值是什么？</button>
        <button onclick="askSuggestion('你怎么管理仓位？')">你怎么管理仓位？</button>
        <button onclick="askSuggestion('为什么看好电影板块？')">为什么看好电影板块？</button>
        <button onclick="askSuggestion('最近市场怎么样？')">最近市场怎么样？</button>
      </div>
    </div>`;
}

// ── 流式发送 ──────────────────────────────────────
async function sendMessage() {
  if (state.isProcessing) return;
  const text = userInput.value.trim();
  if (!text) return;

  state.isProcessing = true;
  userInput.value = '';
  btnSend.disabled = true;

  if (messageList.querySelector('.welcome')) messageList.innerHTML = '';

  // 用户消息
  appendUserMsg(text);

  // Agent 消息容器
  const agentEl = appendAgentContainer();

  // 打开 SSE 连接
  const params = new URLSearchParams({
    message: text,
    session_id: state.sessionId || '',
    mid: '322005137',
  });
  const url = `/chat/stream?${params}`;

  try {
    const eventSource = new EventSource(url);
    let reasoningEl = null;
    let textEl = agentEl.querySelector('.agent-text');

    // 统一 onmessage: SSE 无 event: 行, 所有数据走默认 message 通道
    eventSource.onmessage = (e) => {
      const data = JSON.parse(e.data);
      switch (data.type) {
        case 'connected':
        case 'step':
        case 'ping':
          break; // 心跳/状态, 忽略

        case 'session':
          state.sessionId = data.session_id;
          localStorage.setItem('valhalla_session', state.sessionId);
          break;

        case 'sources':
          state.activeSources = data.sources || [];
          break;

        case 'reasoning':
          if (!reasoningEl) {
            reasoningEl = createReasoningPanel(agentEl);
          }
          reasoningEl.querySelector('.reasoning-body').textContent += data.content;
          scrollBottom();
          break;

        case 'text':
          if (reasoningEl) {
            reasoningEl.querySelector('.reasoning-body').style.display = 'none';
            reasoningEl.querySelector('.reasoning-header').textContent =
              '💭 思考过程 (已完成)';
          }
          textEl.textContent += data.content;
          scrollBottom();
          break;

        case 'done':
          eventSource.close();
          finishAgentMessage(agentEl, state.activeSources);
          updateSessionMeta(state.sessionId, text);
          renderSessions();
          state.isProcessing = false;
          btnSend.disabled = false;
          userInput.focus();
          break;

        case 'error':
          textEl.textContent += `\n\n[错误: ${data.message}]`;
          eventSource.close();
          state.isProcessing = false;
          btnSend.disabled = false;
          break;
      }
    };

    eventSource.onerror = (e) => {
      if (e.target.readyState === EventSource.CONNECTING) {
        return; // 自动重连, 忽略
      }
      const reason = e.target.readyState === EventSource.CLOSED
        ? '服务器关闭了连接' : '连接超时或网络异常';
      textEl.textContent += `\n\n[连接中断: ${reason}]`;
      eventSource.close();
      state.isProcessing = false;
      btnSend.disabled = false;
    };

  } catch (err) {
    agentEl.querySelector('.agent-text').textContent = '出错了：' + err.message;
    state.isProcessing = false;
    btnSend.disabled = false;
  }

  scrollBottom();
}

function createReasoningPanel(agentEl) {
  const el = document.createElement('div');
  el.className = 'reasoning-panel';
  el.innerHTML = `
    <div class="reasoning-header" onclick="toggleReasoning(this)">▶ �� 思考过程</div>
    <div class="reasoning-body" style="display:block"></div>`;
  const bubble = agentEl.querySelector('.bubble');
  bubble.insertBefore(el, bubble.querySelector('.agent-text'));
  return el;
}

function toggleReasoning(header) {
  const body = header.nextElementSibling;
  const isHidden = body.style.display === 'none';
  body.style.display = isHidden ? 'block' : 'none';
  header.textContent = (isHidden ? '▼' : '▶') + header.textContent.slice(1);
}

// ── 消息渲染 ──────────────────────────────────────
function appendUserMsg(text) {
  messageList.insertAdjacentHTML('beforeend', `
    <div class="msg user"><div class="bubble">${escapeHtml(text)}</div></div>`);
}

function appendAgentContainer() {
  const el = document.createElement('div');
  el.className = 'msg agent';
  el.innerHTML = `
    <div class="avatar">💎 韭菜</div>
    <div class="bubble">
      <div class="agent-text"></div>
      <div class="sources"></div>
    </div>`;
  messageList.appendChild(el);
  return el;
}

function finishAgentMessage(agentEl, sources) {
  const sourcesEl = agentEl.querySelector('.sources');
  if (!sources || !sources.length) return;
  let html = `<div class="sources-header" onclick="toggleSources(this)">▶ 参考来源 (${sources.length})</div>`;
  html += `<div class="sources-body" style="display:none">`;
  sources.forEach((s, i) => {
    const ts = formatTime(s.start_time);
    html += `<div class="source-item">${i + 1}. `;
    html += s.url ? `<a href="${s.url}" target="_blank">${escapeHtml(s.heading)}</a>` : escapeHtml(s.heading);
    html += ` @${ts}<span class="score">(${(s.score * 100).toFixed(1)}%)</span></div>`;
  });
  html += `</div>`;
  sourcesEl.innerHTML = html;
}

function scrollBottom() {
  messageList.scrollTop = messageList.scrollHeight;
}

// ── 工具 ──────────────────────────────────────────
function escapeHtml(s) {
  const div = document.createElement('div');
  div.textContent = s;
  return div.innerHTML;
}

function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

function toggleSources(header) {
  const body = header.nextElementSibling;
  const isHidden = body.style.display === 'none';
  body.style.display = isHidden ? 'block' : 'none';
  header.textContent = (isHidden ? '▼' : '▶') + header.textContent.slice(1);
}

// ── 会话管理 ──────────────────────────────────────
function newChat() {
  state.sessionId = null;
  localStorage.removeItem('valhalla_session');
  state.activeSources = [];
  renderWelcome();
  renderSessions();
}

function updateSessionMeta(sid, firstMsg) {
  const sessions = JSON.parse(localStorage.getItem('valhalla_sessions') || '{}');
  sessions[sid] = {
    title: firstMsg.slice(0, 20),
    time: new Date().toLocaleString('zh-CN'),
  };
  localStorage.setItem('valhalla_sessions', JSON.stringify(sessions));
  state.sessions = sessions;
}

function renderSessions() {
  const sessions = JSON.parse(localStorage.getItem('valhalla_sessions') || '{}');
  const entries = Object.entries(sessions);
  if (!entries.length) {
    sessionList.innerHTML = '<div style="padding:16px;color:#666;font-size:13px">暂无对话记录</div>';
    return;
  }
  sessionList.innerHTML = entries
    .sort((a, b) => b[1].time.localeCompare(a[1].time))
    .map(([sid, meta]) => `
      <div class="session-item ${sid === state.sessionId ? 'active' : ''}" onclick="switchSession('${sid}')">
        <span class="title">${escapeHtml(meta.title)}</span>
        <span class="delete" onclick="deleteSession(event, '${sid}')">✕</span>
      </div>`).join('');
}

function switchSession(sid) {
  state.sessionId = sid;
  localStorage.setItem('valhalla_session', sid);
  renderSessions();
  messageList.innerHTML = '';
  appendAgentContainer().querySelector('.agent-text').textContent =
    `继续之前的对话…(session: ${sid})`;
}

function deleteSession(e, sid) {
  e.stopPropagation();
  const sessions = JSON.parse(localStorage.getItem('valhalla_sessions') || '{}');
  delete sessions[sid];
  localStorage.setItem('valhalla_sessions', JSON.stringify(sessions));
  if (state.sessionId === sid) { state.sessionId = null; localStorage.removeItem('valhalla_session'); renderWelcome(); }
  renderSessions();
}

function askSuggestion(text) {
  userInput.value = text;
  sendMessage();
}

async function loadStats() {
  try {
    const resp = await fetch('/stats');
    const data = await resp.json();
    statsInfo.textContent = `${data.videos} 个视频 · ${data.chunks} 个索引`;
  } catch { statsInfo.textContent = '统计获取失败'; }
}

init();
