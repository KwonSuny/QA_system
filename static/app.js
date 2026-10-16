const state = {
  kbs: [],
  activeKbId: null,
  conversations: [],
  activeConversationId: null,
  messages: [],            // {role, content, chunks}
  topK: 4,
  temperature: 0.2,
  editingKbId: null,       // null 表示新建知识库
  editingProviderId: null, // null 表示新增 API 配置
  pendingFile: null,       // 已选择、尚未上传的文件
  pendingDelete: null,     // {type:'kb'|'conv'|'provider'|'user', id}
  pendingPrompt: null,     // 输入弹窗确认回调
  streaming: false,
  token: localStorage.getItem('token') || null,
  currentUser: null,       // {id, username, role}
  providers: [],
  authMode: 'login',       // 'login' | 'register'
};

const $ = (id) => document.getElementById(id);
const messagesEl = $('messages');
const emptyStateEl = $('empty-state');
const kbListEl = $('kb-list');
const convListEl = $('conv-list');

// ---------------- 通用工具 ----------------
function toast(msg, type = '') {
  const el = $('toast');
  el.textContent = msg;
  el.className = 'toast show ' + type;
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove('show'), 2600);
}

function authHeaders() {
  return state.token ? { 'Authorization': 'Bearer ' + state.token } : {};
}

async function request(path, opts = {}) {
  opts.headers = Object.assign({}, opts.headers || {}, authHeaders());
  const res = await fetch(path, opts);
  if (res.status === 401) {
    showLogin();
    throw new Error('未登录或登录已过期');
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.json();
}

function isAdmin() {
  return !!(state.currentUser && state.currentUser.role === 'admin');
}

function escapeHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function mdInline(s) {
  return s
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>')
    .replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
}

function markdown(text) {
  if (!text) return '';
  const lines = String(text).split('\n');
  let html = '';
  let inCode = false;
  let listOpen = null;
  for (let line of lines) {
    const trimmed = line.trim();
    if (trimmed.startsWith('```')) {
      if (inCode) { html += '</code></pre>'; inCode = false; }
      else { html += '<pre><code>'; inCode = true; }
      continue;
    }
    if (inCode) { html += escapeHtml(line) + '\n'; continue; }
    let m = line.match(/^(#{1,4})\s+(.*)/);
    if (m) { html += `<h${m[1].length}>${mdInline(escapeHtml(m[2]))}</h${m[1].length}>`; continue; }
    m = line.match(/^\s*[-*]\s+(.*)/);
    if (m) {
      if (listOpen !== 'ul') { if (listOpen) html += `</${listOpen}>`; html += '<ul>'; listOpen = 'ul'; }
      html += `<li>${mdInline(escapeHtml(m[1]))}</li>`; continue;
    }
    m = line.match(/^\s*\d+[.)]\s+(.*)/);
    if (m) {
      if (listOpen !== 'ol') { if (listOpen) html += `</${listOpen}>`; html += '<ol>'; listOpen = 'ol'; }
      html += `<li>${mdInline(escapeHtml(m[1]))}</li>`; continue;
    }
    if (listOpen) { html += `</${listOpen}>`; listOpen = null; }
    if (trimmed === '') continue;
    html += `<p>${mdInline(escapeHtml(line))}</p>`;
  }
  if (inCode) html += '</code></pre>';
  if (listOpen) html += `</${listOpen}>`;
  return html;
}

function clampInt(v, min, max, dflt) {
  const n = parseInt(v, 10);
  return isNaN(n) ? dflt : Math.min(max, Math.max(min, n));
}
function clampFloat(v, min, max, dflt) {
  const n = parseFloat(v);
  return isNaN(n) ? dflt : Math.min(max, Math.max(min, n));
}

// ---------------- 知识库 ----------------
async function loadKbs() {
  try {
    const data = await request('/api/kbs');
    state.kbs = data.kbs || [];
  } catch (e) {
    toast('加载知识库失败: ' + e.message, 'error');
  }
  renderKbList();
}

function renderKbList() {
  const kw = ($('kb-search').value || '').trim().toLowerCase();
  const list = state.kbs.filter((kb) =>
    !kw || kb.name.toLowerCase().includes(kw) || (kb.description || '').toLowerCase().includes(kw)
  );
  kbListEl.innerHTML = '';
  if (list.length === 0) {
    kbListEl.innerHTML = '<div class="loading-skeleton">' +
      (state.kbs.length ? '无匹配知识库' : '暂无知识库，点击右上角 ＋ 新建') + '</div>';
    return;
  }
  for (const kb of list) {
    const card = document.createElement('div');
    card.className = 'kb-card' + (kb.id === state.activeKbId ? ' active' : '');
    card.innerHTML = `
      <div class="kb-card-name">
        <span>${escapeHtml(kb.name)}</span>
        <div class="kb-actions">
          <button class="icon-btn" data-act="edit" title="编辑">✎</button>
          <button class="icon-btn danger" data-act="del" title="删除">🗑</button>
        </div>
      </div>
      ${kb.description ? `<div class="kb-card-desc">${escapeHtml(kb.description)}</div>` : ''}
      <div class="kb-card-meta">
        <span class="chip">${kb.chunk_count ?? 0} 片段</span>
        <span>${escapeHtml(kb.updated_at || '')}</span>
      </div>`;
    card.addEventListener('click', (e) => {
      if (e.target.closest('[data-act]')) return;
      selectKb(kb.id);
    });
    card.querySelector('[data-act="edit"]').addEventListener('click', () => openEditModal(kb.id));
    card.querySelector('[data-act="del"]').addEventListener('click', () => openDeleteConfirm('kb', kb.id));
    kbListEl.appendChild(card);
  }
}

function selectKb(id) {
  state.activeKbId = id;
  // 切换知识库即开启新会话视图
  state.activeConversationId = null;
  state.messages = [];
  const kb = state.kbs.find((k) => k.id === id);
  $('active-kb-name').textContent = kb ? kb.name : '请选择知识库并开始提问';
  $('active-kb-meta').textContent = kb
    ? `${kb.chunk_count ?? 0} 个片段 · ${kb.description || '暂无简介'}`
    : '';
  renderKbList();
  renderConvList();
  renderMessages();
}

// ---------------- 历史对话 ----------------
async function loadConversations() {
  try {
    const data = await request('/api/conversations');
    state.conversations = data.conversations || [];
  } catch (_) {
    state.conversations = [];
  }
  renderConvList();
}

function renderConvList() {
  convListEl.innerHTML = '';
  if (!state.conversations.length) {
    convListEl.innerHTML = '<div class="loading-skeleton">暂无历史对话</div>';
    return;
  }
  for (const conv of state.conversations) {
    const item = document.createElement('div');
    item.className = 'conv-item' + (conv.id === state.activeConversationId ? ' active' : '');
    item.innerHTML = `
      <div class="conv-main">
        <div class="conv-title">${escapeHtml(conv.title || '新对话')}</div>
        <div class="conv-meta">${escapeHtml((conv.updated_at || '').slice(5, 16))}</div>
      </div>
      <div class="conv-actions">
        <button class="icon-btn" data-act="rename" title="重命名">✎</button>
        <button class="icon-btn danger" data-act="del" title="删除">🗑</button>
      </div>`;
    item.addEventListener('click', (e) => {
      if (e.target.closest('[data-act]')) return;
      selectConversation(conv.id);
    });
    item.querySelector('[data-act="rename"]').addEventListener('click', () => renameConversation(conv.id));
    item.querySelector('[data-act="del"]').addEventListener('click', () => openDeleteConfirm('conv', conv.id));
    convListEl.appendChild(item);
  }
}

async function selectConversation(id) {
  try {
    const data = await request('/api/conversations/' + id);
    const conv = data.conversation;
    state.activeConversationId = conv.id;
    state.activeKbId = conv.kb_id || null;
    state.messages = (conv.messages || []).map((m) => ({
      role: m.role, content: m.content, chunks: m.chunks || null,
    }));
    const kb = state.kbs.find((k) => k.id === state.activeKbId);
    $('active-kb-name').textContent = kb ? kb.name : '（原知识库已删除）';
    $('active-kb-meta').textContent = kb
      ? `${kb.chunk_count ?? 0} 个片段 · ${kb.description || '暂无简介'}`
      : '该会话绑定的知识库已不存在';
    renderKbList();
    renderConvList();
    renderMessages();
  } catch (e) {
    toast('加载会话失败: ' + e.message, 'error');
  }
}

function newConversation() {
  state.activeConversationId = null;
  state.messages = [];
  renderConvList();
  renderMessages();
  $('active-kb-name').textContent = state.activeKbId
    ? ($('active-kb-name').textContent)
    : '请选择知识库并开始提问';
  toast('已开启新对话，输入问题即可开始');
}

function renameConversation(id) {
  const conv = state.conversations.find((c) => c.id === id);
  openPrompt({
    title: '重命名对话',
    value: conv ? conv.title : '',
    placeholder: '输入新的对话名称',
    onOk: async (title) => {
      try {
        await request('/api/conversations/' + id, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ title }),
        });
        await loadConversations();
        toast('已重命名', 'success');
      } catch (e) {
        toast('重命名失败: ' + e.message, 'error');
        return false;
      }
    },
  });
}

// ---------------- 消息渲染 ----------------
function createMessageEl(role) {
  const wrap = document.createElement('div');
  wrap.className = 'msg ' + role;
  const avatar = document.createElement('div');
  avatar.className = 'avatar';
  avatar.textContent = role === 'user' ? '我' : 'AI';
  const bubble = document.createElement('div');
  bubble.className = 'msg-bubble';
  const content = document.createElement('div');
  content.className = 'msg-content';
  bubble.appendChild(content);
  wrap.appendChild(avatar);
  wrap.appendChild(bubble);
  return { wrap, content, bubble };
}

function renderMessages() {
  messagesEl.innerHTML = '';
  messagesEl.appendChild(emptyStateEl);
  if (state.messages.length === 0) {
    emptyStateEl.style.display = 'flex';
    return;
  }
  emptyStateEl.style.display = 'none';
  for (const msg of state.messages) {
    const { wrap, content } = createMessageEl(msg.role);
    content.innerHTML = markdown(msg.content);
    if (msg.chunks && msg.chunks.length) appendSources(content, msg.chunks);
    messagesEl.appendChild(wrap);
  }
  scrollToBottom();
}

function appendSources(contentEl, chunks) {
  const box = document.createElement('div');
  box.className = 'msg-sources';
  const toggle = document.createElement('button');
  toggle.className = 'sources-toggle';
  toggle.textContent = `引用 ${chunks.length} 个知识片段`;
  const body = document.createElement('div');
  body.className = 'sources-body';
  chunks.forEach((c) => {
    const item = document.createElement('div');
    item.className = 'source-item';
    const label = [c.evidence_id ? `[${c.evidence_id}]` : '', c.source_title || ''].filter(Boolean).join(' ');
    const score = c.evidence_id ? c.dense_score : c.score;
    const scoreLabel = typeof score === 'number' ? `向量相似度 ${score.toFixed(3)}` : '关键词召回';
    const headings = [...new Set((c.section_context || []).map(s => s.heading))].join('；');
    item.innerHTML = `<div class="src-score">${escapeHtml(label)}${label ? ' · ' : ''}${escapeHtml(scoreLabel)}</div>` +
      (headings ? `<div class="src-score">章节线索：${escapeHtml(headings)}</div>` : '') +
      `<div class="src-text">${escapeHtml(c.text)}</div>`;
    body.appendChild(item);
  });
  toggle.addEventListener('click', () => body.classList.toggle('open'));
  box.appendChild(toggle);
  box.appendChild(body);
  contentEl.appendChild(box);
}

function scrollToBottom() {
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

// ---------------- 发送消息 ----------------
async function sendMessage() {
  if (state.streaming) return;
  if (!state.activeKbId) { toast('请先选择或新建一个知识库', 'error'); return; }
  const question = $('input').value.trim();
  if (!question) return;

  $('input').value = '';
  autoResize();
  state.messages.push({ role: 'user', content: question, chunks: null });
  renderMessages();

  const { wrap, content } = createMessageEl('assistant');
  messagesEl.appendChild(wrap);
  emptyStateEl.style.display = 'none';
  let full = '';
  let metaChunks = [];
  const caret = document.createElement('span');
  caret.className = 'caret';
  content.appendChild(caret);

  state.streaming = true;
  $('btn-send').disabled = true;
  const history = state.messages
    .slice(0, -1)
    .filter((m) => m.chunks !== undefined)
    .map((m) => ({ role: m.role, content: m.content }))
    .slice(-10);

  try {
    const res = await fetch('/api/chat', {
      method: 'POST',
      headers: Object.assign({ 'Content-Type': 'application/json' }, authHeaders()),
      body: JSON.stringify({
        kb_id: state.activeKbId,
        question,
        history,
        top_k: state.topK,
        temperature: state.temperature,
        max_new_tokens: 512,
        provider: currentProvider().provider,
        provider_id: currentProvider().provider_id,
        conversation_id: state.activeConversationId,
      }),
    });
    if (res.status === 401) { showLogin(); throw new Error('未登录或登录已过期'); }
    if (!res.ok) {
      let d = res.statusText; try { d = (await res.json()).detail || d; } catch (_) {}
      throw new Error(d);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let newConv = false;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let idx;
      while ((idx = buffer.indexOf('\n\n')) >= 0) {
        const raw = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        const dataLine = raw.split('\n').filter((l) => l.startsWith('data:')).map((l) => l.slice(5).trim()).join('');
        if (!dataLine) continue;
        let evt; try { evt = JSON.parse(dataLine); } catch (_) { continue; }
        if (evt.type === 'meta') {
          metaChunks = evt.chunks || [];
          if (evt.conversation_id && evt.conversation_id !== state.activeConversationId) {
            state.activeConversationId = evt.conversation_id;
            newConv = !state.conversations.some((c) => c.id === evt.conversation_id);
          }
        } else if (evt.type === 'status') {
          content.textContent = evt.message || '正在处理…';
          content.appendChild(caret);
        } else if (evt.type === 'token') {
          full += evt.content;
          content.innerHTML = markdown(full);
          content.appendChild(caret);
          scrollToBottom();
        } else if (evt.type === 'error') {
          full = evt.message || full;
          content.innerHTML = markdown(full);
        }
      }
    }
    if (newConv) await loadConversations();
    else renderConvList();
  } catch (e) {
    full = '请求失败: ' + e.message;
    content.innerHTML = markdown(full);
    toast('请求失败: ' + e.message, 'error');
  } finally {
    caret.remove();
    content.innerHTML = markdown(full);
    if (metaChunks.length) appendSources(content, metaChunks);
    state.messages.push({ role: 'assistant', content: full, chunks: metaChunks });
    state.streaming = false;
    $('btn-send').disabled = false;
    scrollToBottom();
  }
}

// ---------------- 知识库弹窗 ----------------
function openCreateModal() {
  state.editingKbId = null;
  state.pendingFile = null;
  $('kb-modal-title').textContent = '新建知识库';
  $('kb-name').value = '';
  $('kb-desc').value = '';
  $('kb-text').value = '';
  $('kb-file').value = '';
  $('kb-file-info').hidden = true;
  $('kb-edit-hint').hidden = true;
  $('kb-modal').hidden = false;
  $('kb-name').focus();
}

async function openEditModal(id) {
  try {
    // 不请求正文全文，避免大数据量导致界面卡顿
    const data = await request('/api/kbs/' + id);
    const kb = data.kb;
    state.editingKbId = id;
    state.pendingFile = null;
    $('kb-modal-title').textContent = '编辑知识库';
    $('kb-name').value = kb.name || '';
    $('kb-desc').value = kb.description || '';
    $('kb-text').value = '';
    $('kb-text').placeholder = '留空表示不修改正文；如需替换，请选择文件或粘贴新正文。';
    $('kb-file').value = '';
    $('kb-file-info').hidden = true;
    $('kb-edit-hint').hidden = false;
    $('kb-modal').hidden = false;
  } catch (e) {
    toast('加载失败: ' + e.message, 'error');
  }
}

function closeKbModal() { $('kb-modal').hidden = true; }

function humanSize(bytes) {
  if (bytes < 1024) return bytes + ' B';
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
  return (bytes / 1024 / 1024).toFixed(1) + ' MB';
}

async function saveKb() {
  const name = $('kb-name').value.trim();
  const description = $('kb-desc').value.trim();
  const text = $('kb-text').value;
  if (!name) { toast('请填写名称', 'error'); return; }
  const btn = $('kb-save');
  btn.disabled = true;
  btn.textContent = '保存中...';
  try {
    if (state.pendingFile) {
      // 有文件：走 multipart 上传，内容不进入文本框
      const fd = new FormData();
      fd.append('file', state.pendingFile);
      fd.append('name', name);
      fd.append('description', description);
      if (state.editingKbId) fd.append('kb_id', state.editingKbId);
      const data = await request('/api/kbs/upload', { method: 'POST', body: fd });
      if (!state.editingKbId) state.activeKbId = data.kb.id;
      toast(`已上传「${data.filename}」（${humanSize(data.size)}），切分为 ${data.kb.chunk_count} 个片段`, 'success');
      if (data.warnings?.length) toast(data.warnings.join(' '), 'warning');
    } else if (state.editingKbId) {
      const body = { name, description };
      if (text) body.text = text;
      await request('/api/kbs/' + state.editingKbId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      toast('知识库已更新', 'success');
    } else {
      const data = await request('/api/kbs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, description, text }),
      });
      state.activeKbId = data.kb.id;
      toast('知识库已创建', 'success');
    }
    closeKbModal();
    state.pendingFile = null;
    await loadKbs();
  } catch (e) {
    toast('保存失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '保存';
  }
}

// ---------------- 融合知识库 ----------------
function openMergeModal() {
  if (state.kbs.length < 2) { toast('至少需要两个知识库才能融合', 'error'); return; }
  const listEl = $('merge-list');
  listEl.innerHTML = '';
  state.kbs.forEach((kb) => {
    const row = document.createElement('label');
    row.className = 'merge-item';
    row.innerHTML = `<input type="checkbox" value="${kb.id}">
      <span class="merge-name">${escapeHtml(kb.name)}</span>
      <span class="merge-chips">${kb.chunk_count ?? 0} 片段</span>`;
    listEl.appendChild(row);
  });
  $('merge-name').value = '';
  $('merge-delete').checked = false;
  $('merge-modal').hidden = false;
}

function closeMergeModal() { $('merge-modal').hidden = true; }

async function confirmMerge() {
  const checked = [...$('merge-list').querySelectorAll('input:checked')].map((i) => i.value);
  const name = $('merge-name').value.trim();
  if (checked.length < 2) { toast('请至少勾选两个知识库', 'error'); return; }
  if (!name) { toast('请填写新知识库名称', 'error'); return; }
  const btn = $('merge-ok');
  btn.disabled = true;
  btn.textContent = '融合中...';
  try {
    const data = await request('/api/kbs/merge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kb_ids: checked, name, description: '', delete_sources: $('merge-delete').checked,
      }),
    });
    toast(`已融合 ${data.merged_from.length} 个知识库为「${data.kb.name}」`, 'success');
    closeMergeModal();
    await loadKbs();
  } catch (e) {
    toast('融合失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '融合';
  }
}

// ---------------- 删除确认 ----------------
function openDeleteConfirm(type, id, label = '') {
  state.pendingDelete = { type, id };
  let title = '删除';
  let text = '确定要删除吗？此操作不可撤销。';
  if (type === 'kb') {
    const kb = state.kbs.find((k) => k.id === id);
    title = '删除知识库';
    text = `确定要删除「${kb ? kb.name : ''}」吗？其中的 ${kb ? kb.chunk_count : 0} 个片段将一并删除，此操作不可撤销。`;
  } else if (type === 'conv') {
    const conv = state.conversations.find((c) => c.id === id);
    title = '删除对话';
    text = `确定要删除对话「${conv ? conv.title : ''}」吗？其中的聊天记录将一并删除，此操作不可撤销。`;
  } else if (type === 'provider') {
    title = '删除 API 配置';
    text = `确定要删除 API 配置「${label}」吗？`;
  } else if (type === 'user') {
    title = '删除用户';
    text = `确定要删除用户「${label}」吗？其知识库、对话与配置将一并删除，此操作不可撤销。`;
  }
  $('confirm-title').textContent = title;
  $('confirm-text').textContent = text;
  $('confirm-modal').hidden = false;
}

function closeConfirm() { $('confirm-modal').hidden = true; }

async function confirmDelete() {
  const pending = state.pendingDelete;
  if (!pending) return;
  const btn = $('confirm-ok');
  btn.disabled = true;
  try {
    if (pending.type === 'kb') {
      await request('/api/kbs/' + pending.id, { method: 'DELETE' });
      if (state.activeKbId === pending.id) {
        state.activeKbId = null;
        state.messages = [];
        $('active-kb-name').textContent = '请选择知识库并开始提问';
        $('active-kb-meta').textContent = '';
        renderMessages();
      }
      await loadKbs();
    } else if (pending.type === 'conv') {
      await request('/api/conversations/' + pending.id, { method: 'DELETE' });
      if (state.activeConversationId === pending.id) {
        state.activeConversationId = null;
        state.messages = [];
        renderMessages();
      }
      await loadConversations();
    } else if (pending.type === 'provider') {
      await request('/api/llm/providers/' + pending.id, { method: 'DELETE' });
      await loadProviders();
    } else if (pending.type === 'user') {
      await request('/api/admin/users/' + pending.id, { method: 'DELETE' });
      await loadAdminData();
    }
    toast('已删除', 'success');
    closeConfirm();
  } catch (e) {
    toast('删除失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    state.pendingDelete = null;
  }
}

// ---------------- API 模型（用户私有） ----------------
function currentProvider() {
  const v = $('model-select').value;
  if (v === 'local') return { provider: 'local', provider_id: null };
  return { provider: 'api', provider_id: v };
}

async function loadProviders() {
  try {
    const data = await request('/api/llm/providers');
    state.providers = data.providers || [];
  } catch (_) {
    state.providers = [];
  }
  renderModelSelect();
  renderApiList();
}

function renderModelSelect() {
  const sel = $('model-select');
  const prev = sel.value;
  sel.innerHTML = '<option value="local">本地模型</option>';
  state.providers.forEach((p) => {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = `${p.name}（${p.model}）`;
    sel.appendChild(opt);
  });
  if ([...sel.options].some((o) => o.value === prev)) sel.value = prev;
  else sel.value = 'local';
}

function renderApiList() {
  const listEl = $('api-list');
  if (!listEl) return;
  if (!state.providers.length) {
    listEl.innerHTML = '<div class="loading-skeleton">暂无 API 配置，点击「添加配置」</div>';
    return;
  }
  listEl.innerHTML = '';
  state.providers.forEach((p) => {
    const row = document.createElement('div');
    row.className = 'api-row';
    row.innerHTML = `
      <div class="api-row-main">
        <div class="api-row-name">${escapeHtml(p.name)}</div>
        <div class="api-row-model">${escapeHtml(p.model)}</div>
        <div class="api-row-url">${escapeHtml(p.base_url)}</div>
        <div class="api-row-key">Key: ${escapeHtml(p.api_key_masked || '')}</div>
      </div>
      <div class="api-row-actions">
        <button class="icon-btn" data-act="edit" title="编辑">✎</button>
        <button class="icon-btn danger" data-act="del" title="删除">🗑</button>
      </div>`;
    row.querySelector('[data-act="edit"]').addEventListener('click', () => openApiForm(p.id));
    row.querySelector('[data-act="del"]').addEventListener('click', () => deleteProvider(p.id));
    listEl.appendChild(row);
  });
}

function openApiModal() {
  renderApiList();
  $('api-modal').hidden = false;
}
function closeApiModal() { $('api-modal').hidden = true; }

function openApiForm(id) {
  state.editingProviderId = id || null;
  $('api-form-title').textContent = id ? '编辑 API 配置' : '添加 API 配置';
  $('api-key-hint').style.display = id ? '' : 'none';
  if (id) {
    const p = state.providers.find((x) => x.id === id);
    $('api-name').value = p ? p.name : '';
    $('api-base-url').value = p ? p.base_url : '';
    $('api-model').value = p ? p.model : '';
    $('api-key').value = '';
    $('api-key').placeholder = p && p.api_key_masked ? `留空则不改（当前 ${p.api_key_masked}）` : 'sk-...';
  } else {
    $('api-name').value = '';
    $('api-base-url').value = '';
    $('api-model').value = '';
    $('api-key').value = '';
    $('api-key').placeholder = 'sk-...';
  }
  $('api-form-modal').hidden = false;
  $('api-name').focus();
}
function closeApiForm() { $('api-form-modal').hidden = true; }

async function saveApiForm() {
  const name = $('api-name').value.trim();
  const base_url = $('api-base-url').value.trim();
  const model = $('api-model').value.trim();
  const api_key = $('api-key').value.trim();
  if (!base_url) { toast('请填写 Base URL', 'error'); return; }
  if (!model) { toast('请填写模型名', 'error'); return; }
  const btn = $('api-form-save');
  btn.disabled = true;
  btn.textContent = '保存中...';
  try {
    if (state.editingProviderId) {
      await request('/api/llm/providers/' + state.editingProviderId, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, base_url, model, api_key }),
      });
      toast('API 配置已更新', 'success');
    } else {
      if (!api_key) { toast('请填写 API Key', 'error'); btn.disabled = false; btn.textContent = '保存'; return; }
      await request('/api/llm/providers', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, base_url, model, api_key }),
      });
      toast('API 配置已添加', 'success');
    }
    closeApiForm();
    await loadProviders();
  } catch (e) {
    toast('保存失败: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '保存';
  }
}

function deleteProvider(id) {
  const p = state.providers.find((x) => x.id === id);
  openDeleteConfirm('provider', id, p ? p.name : '');
}

// ---------------- 管理员：用户管理 ----------------
async function openAdminModal() {
  $('admin-modal').hidden = false;
  await loadAdminData();
}

function closeAdminModal() { $('admin-modal').hidden = true; }

async function loadAdminData() {
  try {
    const [usersData, statsData] = await Promise.all([
      request('/api/admin/users'),
      request('/api/admin/stats'),
    ]);
    const s = statsData.stats || {};
    $('admin-stats').innerHTML = `
      <span class="chip">用户 ${s.users ?? 0}</span>
      <span class="chip">管理员 ${s.admins ?? 0}</span>
      <span class="chip">知识库 ${s.knowledge_bases ?? 0}</span>
      <span class="chip">对话 ${s.conversations ?? 0}</span>
      <span class="chip">消息 ${s.messages ?? 0}</span>
      <span class="chip">API 配置 ${s.api_configs ?? 0}</span>`;
    const listEl = $('admin-user-list');
    listEl.innerHTML = '';
    (usersData.users || []).forEach((u) => {
      const row = document.createElement('div');
      row.className = 'admin-user-row';
      const isSelf = state.currentUser && u.id === state.currentUser.id;
      row.innerHTML = `
        <div class="admin-user-main">
          <span class="admin-user-name">${escapeHtml(u.username)}</span>
          <span class="chip">${u.role === 'admin' ? '管理员' : '普通用户'}</span>
          ${isSelf ? '<span class="chip">当前账号</span>' : ''}
        </div>
        <div class="admin-user-actions">
          <button class="btn btn-ghost btn-xs" data-act="reset">重置密码</button>
          <button class="btn btn-danger btn-xs" data-act="del" ${isSelf ? 'disabled' : ''}>删除</button>
        </div>`;
      row.querySelector('[data-act="reset"]').addEventListener('click', () => adminResetPassword(u));
      row.querySelector('[data-act="del"]').addEventListener('click', () => adminDeleteUser(u));
      listEl.appendChild(row);
    });
  } catch (e) {
    toast('加载用户失败: ' + e.message, 'error');
  }
}

async function adminAddUser() {
  const username = $('admin-new-username').value.trim();
  const password = $('admin-new-password').value;
  const role = $('admin-new-role').value;
  if (!username || !password) { toast('请填写用户名和密码', 'error'); return; }
  try {
    await request('/api/admin/users', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, role }),
    });
    toast('已创建用户 ' + username, 'success');
    $('admin-new-username').value = '';
    $('admin-new-password').value = '';
    await loadAdminData();
  } catch (e) {
    toast('创建失败: ' + e.message, 'error');
  }
}

function adminDeleteUser(u) {
  openDeleteConfirm('user', u.id, u.username);
}

function adminResetPassword(u) {
  openPrompt({
    title: `为用户「${u.username}」设置新密码`,
    placeholder: '新密码（至少 6 位）',
    hint: '重置后该用户的所有登录状态将失效。',
    onOk: async (password) => {
      try {
        await request(`/api/admin/users/${u.id}/reset-password`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password }),
        });
        toast('密码已重置', 'success');
      } catch (e) {
        toast('重置失败: ' + e.message, 'error');
        return false;
      }
    },
  });
}

// ---------------- 通用输入弹窗 ----------------
// 原生 prompt() 在嵌入式预览中会被禁用，统一改用自定义弹窗
function openPrompt({ title, value = '', placeholder = '', hint = '', okText = '确定', onOk }) {
  $('prompt-title').textContent = title || '输入';
  $('prompt-input').value = value || '';
  $('prompt-input').placeholder = placeholder || '';
  $('prompt-ok').textContent = okText;
  const hintEl = $('prompt-hint');
  if (hint) { hintEl.textContent = hint; hintEl.hidden = false; } else { hintEl.hidden = true; }
  state.pendingPrompt = onOk || null;
  $('prompt-modal').hidden = false;
  setTimeout(() => { $('prompt-input').focus(); $('prompt-input').select(); }, 0);
}

function closePrompt() {
  $('prompt-modal').hidden = true;
  state.pendingPrompt = null;
}

async function confirmPrompt() {
  const fn = state.pendingPrompt;
  const value = $('prompt-input').value.trim();
  if (!value) { toast('内容不能为空', 'error'); return; }
  if (fn) {
    const ok = await fn(value);
    if (ok === false) return;
  }
  closePrompt();
}

// ---------------- 其它 ----------------
function autoResize() {
  const t = $('input');
  t.style.height = 'auto';
  t.style.height = Math.min(t.scrollHeight, 160) + 'px';
}

function bindEvents() {
  // 认证
  $('auth-submit').addEventListener('click', submitAuth);
  $('auth-pass').addEventListener('keydown', (e) => { if (e.key === 'Enter') submitAuth(); });
  $('auth-confirm').addEventListener('keydown', (e) => { if (e.key === 'Enter') submitAuth(); });
  document.querySelectorAll('.auth-tab').forEach((btn) => {
    btn.addEventListener('click', () => switchAuthMode(btn.dataset.mode));
  });
  $('btn-logout').addEventListener('click', logout);

  // 知识库
  $('btn-new').addEventListener('click', openCreateModal);
  $('btn-merge').addEventListener('click', openMergeModal);
  $('kb-modal-close').addEventListener('click', closeKbModal);
  $('kb-cancel').addEventListener('click', closeKbModal);
  $('kb-save').addEventListener('click', saveKb);
  $('merge-close').addEventListener('click', closeMergeModal);
  $('merge-cancel').addEventListener('click', closeMergeModal);
  $('merge-ok').addEventListener('click', confirmMerge);
  $('kb-search').addEventListener('input', renderKbList);
  $('kb-file').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    state.pendingFile = file;
    const info = $('kb-file-info');
    info.hidden = false;
    info.textContent = `已选择：${file.name}（${humanSize(file.size)}）—— 保存时上传，内容不会显示在文本框中`;
    $('kb-text').value = '';
  });

  // 会话
  $('btn-new-conv').addEventListener('click', newConversation);

  // 删除确认
  $('confirm-close').addEventListener('click', closeConfirm);
  $('confirm-cancel').addEventListener('click', closeConfirm);
  $('confirm-ok').addEventListener('click', confirmDelete);

  // 输入弹窗
  $('prompt-close').addEventListener('click', closePrompt);
  $('prompt-cancel').addEventListener('click', closePrompt);
  $('prompt-ok').addEventListener('click', confirmPrompt);
  $('prompt-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); confirmPrompt(); }
  });

  // 聊天
  $('btn-send').addEventListener('click', sendMessage);
  $('btn-clear').addEventListener('click', newConversation);
  $('top-k').addEventListener('change', (e) => { state.topK = clampInt(e.target.value, 1, 10, 4); });
  $('temperature').addEventListener('change', (e) => { state.temperature = clampFloat(e.target.value, 0, 1, 0.2); });
  $('input').addEventListener('input', autoResize);
  $('input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });

  // API 设置
  $('btn-api-settings').addEventListener('click', openApiModal);
  $('api-modal-close').addEventListener('click', closeApiModal);
  $('api-close').addEventListener('click', closeApiModal);
  $('api-add').addEventListener('click', () => openApiForm(null));
  $('api-form-close').addEventListener('click', closeApiForm);
  $('api-form-cancel').addEventListener('click', closeApiForm);
  $('api-form-save').addEventListener('click', saveApiForm);

  // 管理员
  $('btn-admin').addEventListener('click', openAdminModal);
  $('admin-modal-close').addEventListener('click', closeAdminModal);
  $('admin-close').addEventListener('click', closeAdminModal);
  $('admin-add-user').addEventListener('click', adminAddUser);

  // 点击遮罩关闭
  const overlays = ['kb-modal', 'merge-modal', 'confirm-modal', 'prompt-modal', 'api-modal', 'api-form-modal', 'admin-modal'];
  const closers = { 'kb-modal': closeKbModal, 'merge-modal': closeMergeModal, 'confirm-modal': closeConfirm,
    'prompt-modal': closePrompt, 'api-modal': closeApiModal, 'api-form-modal': closeApiForm, 'admin-modal': closeAdminModal };
  overlays.forEach((id) => {
    $(id).addEventListener('click', (e) => { if (e.target === e.currentTarget) closers[id](); });
  });
}

// ---------------- 认证 ----------------
function switchAuthMode(mode) {
  state.authMode = mode;
  document.querySelectorAll('.auth-tab').forEach((b) => {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
  $('auth-confirm-wrap').hidden = mode !== 'register';
  $('auth-submit').textContent = mode === 'register' ? '注册' : '登录';
  $('auth-hint').textContent = mode === 'register'
    ? '注册后即可创建自己的知识库、保存个人 API 配置与聊天记录。'
    : '默认管理员：admin / admin123（可用环境变量 APP_ADMIN_PASSWORD 修改）';
  $('auth-err').textContent = '';
}

function showLogin() {
  state.token = null;
  state.currentUser = null;
  localStorage.removeItem('token');
  $('auth-overlay').style.display = 'flex';
  $('auth-err').textContent = '';
  $('auth-pass').value = '';
  $('auth-confirm').value = '';
}

function hideLogin() { $('auth-overlay').style.display = 'none'; }

async function submitAuth() {
  const username = $('auth-user').value.trim();
  const password = $('auth-pass').value;
  const confirm = $('auth-confirm').value;
  const errEl = $('auth-err');
  errEl.textContent = '';
  if (!username || !password) { errEl.textContent = '请输入用户名和密码'; return; }
  if (state.authMode === 'register') {
    if (password !== confirm) { errEl.textContent = '两次输入的密码不一致'; return; }
    if (password.length < 6) { errEl.textContent = '密码长度不能少于 6 位'; return; }
  }
  const btn = $('auth-submit');
  btn.disabled = true;
  try {
    const path = state.authMode === 'register' ? '/api/register' : '/api/login';
    const payload = state.authMode === 'register'
      ? { username, password, password_confirm: confirm }
      : { username, password };
    const res = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || '操作失败');
    state.token = data.token;
    state.currentUser = data.user;
    localStorage.setItem('token', data.token);
    hideLogin();
    applyRoleUI();
    $('auth-pass').value = '';
    $('auth-confirm').value = '';
    await afterLogin();
  } catch (e) {
    errEl.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
}

async function logout() {
  try {
    if (state.token) await request('/api/logout', { method: 'POST' });
  } catch (_) { /* ignore */ }
  showLogin();
  applyRoleUI();
}

function applyRoleUI() {
  const admin = isAdmin();
  $('btn-admin').style.display = admin ? '' : 'none';
  const uname = state.currentUser ? state.currentUser.username : '';
  $('btn-logout').textContent = '退出' + (uname ? ' · ' + uname : '');
}

async function afterLogin() {
  resetSessionState();
  await loadKbs();
  await loadProviders();
  await loadConversations();
}

function resetSessionState() {
  state.kbs = [];
  state.conversations = [];
  state.providers = [];
  state.activeKbId = null;
  state.activeConversationId = null;
  state.messages = [];
  renderKbList();
  renderConvList();
  renderMessages();
  $('active-kb-name').textContent = '请选择知识库并开始提问';
  $('active-kb-meta').textContent = '';
}

async function init() {
  if (state.token) {
    try {
      const data = await request('/api/me');
      state.currentUser = data.user;
      hideLogin();
      applyRoleUI();
      await afterLogin();
      return;
    } catch (_) { /* 401 已触发 showLogin */ }
  }
  showLogin();
  applyRoleUI();
}

bindEvents();
init();
