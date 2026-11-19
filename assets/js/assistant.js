// AI Engineering Assistant — Stage 11 frontend.
// Same auth pattern as the other labs: token in localStorage,
// API base from window.AIELAB_API_BASE (default local backend).
const API = (window.AIELAB_API_BASE || 'http://127.0.0.1:8001');
const token = () => localStorage.getItem('aielab.token');
const $ = (id) => document.getElementById(id);

async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  const t = token();
  if (t) headers['Authorization'] = 'Bearer ' + t;
  const res = await (window.aielabFetchWithWake || fetch)(API + path, { ...opts, headers },
    (attempt) => { const el = $('chat-status'); if (el) el.textContent = 'Waking the server… (retry ' + attempt + ')'; });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(body.error || ('HTTP ' + res.status));
  return body;
}

const S = { convId: null, convs: [], projects: [], proposals: {} };

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// Tiny renderer: **bold**, `code`, - lists, | tables |, paragraphs.
function renderMd(text) {
  const lines = String(text || '').split('\n');
  let html = '', inTable = false, inList = false;
  const inline = (s) => esc(s)
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
  for (const raw of lines) {
    const line = raw.trim();
    if (line.startsWith('|')) {
      const cells = line.split('|').filter((c, i, a) => i > 0 && i < a.length - 1)
        .map((c) => c.trim());
      if (/^:?-{3,}/.test(cells[0] || '')) continue;
      if (!inTable) { html += '<table><tbody>'; inTable = true; }
      html += '<tr>' + cells.map((c) => '<td>' + inline(c) + '</td>').join('') + '</tr>';
      continue;
    }
    if (inTable) { html += '</tbody></table>'; inTable = false; }
    if (line.startsWith('- ')) {
      if (!inList) { html += '<ul>'; inList = true; }
      html += '<li>' + inline(line.slice(2)) + '</li>';
      continue;
    }
    if (inList) { html += '</ul>'; inList = false; }
    if (line) html += '<p style="margin:4px 0">' + inline(line) + '</p>';
  }
  if (inTable) html += '</tbody></table>';
  if (inList) html += '</ul>';
  return html;
}

const PROV_LABEL = {
  'verified calculation': ['prov-verified', 'Verified calculation'],
  'actual simulation result': ['prov-simulation', 'Simulation result'],
  'database value': ['prov-database', 'Database value'],
  'estimate': ['prov-estimate', 'Estimate'],
  'general guidance': ['prov-guidance', 'General guidance'],
  'proposal': ['prov-proposal', 'Proposal — needs approval'],
};

function toolCard(tc) {
  const st = tc.status === 'completed'
    ? '<span class="st-ok">✓ completed</span>'
    : tc.status === 'proposed'
      ? '<span class="st-prop">◷ proposed — awaiting your approval</span>'
      : '<span class="st-fail">✗ failed</span>';
  let inner = `<div class="toolcard"><strong>Tool:</strong> ${esc(tc.tool || '')} — ${st}`;
  if (tc.provenance) inner += `<br><strong>Provenance:</strong> ${esc(tc.provenance)}`;
  if (tc.source) inner += `<br><strong>Source:</strong> ${esc(tc.source)}`;
  if (tc.error) inner += `<br><strong>Error:</strong> ${esc(tc.error)}`;
  if (tc.proposal_id) {
    inner += `<div class="proposal-actions">
      <button class="btn primary" data-approve="${esc(tc.proposal_id)}">Approve</button>
      <button class="btn" data-deny="${esc(tc.proposal_id)}">Deny</button>
    </div>`;
  }
  return inner + '</div>';
}

function renderMessage(m) {
  const div = document.createElement('div');
  div.className = 'msg ' + (m.role === 'user' ? 'user' : 'asst');
  if (m.role === 'assistant') {
    const prov = PROV_LABEL[m.provenance] || PROV_LABEL['general guidance'];
    div.innerHTML = `<span class="prov ${prov[0]}">${prov[1]}</span>` + renderMd(m.content)
      + (m.tool_calls || []).map(toolCard).join('');
  } else {
    div.textContent = m.content;
  }
  return div;
}

function renderLog(messages) {
  const log = $('chat-log');
  log.innerHTML = '';
  if (!messages.length) {
    log.innerHTML = '<p style="color:var(--hatch-widget-muted)">No messages yet. Ask an engineering question, or attach a project and ask about it.</p>';
    return;
  }
  for (const m of messages) log.appendChild(renderMessage(m));
  log.scrollTop = log.scrollHeight;
}

function renderConvs() {
  const list = $('conv-list');
  list.innerHTML = '';
  if (!S.convs.length) {
    list.innerHTML = '<p style="color:var(--hatch-widget-muted);font-size:13px">No conversations yet.</p>';
    return;
  }
  for (const c of S.convs) {
    const row = document.createElement('div');
    row.className = 'conv-item' + (c.id === S.convId ? ' active' : '');
    const title = document.createElement('span');
    title.className = 't';
    title.textContent = c.title;
    title.title = 'Click to open · double-click to rename';
    title.onclick = () => openConv(c.id);
    title.ondblclick = async () => {
      const name = prompt('Rename conversation', c.title);
      if (name && name.trim()) {
        await api('/api/v1/assistant/conversations/' + encodeURIComponent(c.id), {
          method: 'PATCH', body: JSON.stringify({ title: name.trim() }),
        });
        await loadConvs();
      }
    };
    const del = document.createElement('button');
    del.className = 'x';
    del.textContent = '×';
    del.title = 'Delete conversation (and its history)';
    del.onclick = async (e) => {
      e.stopPropagation();
      if (!confirm('Delete this conversation and its history?')) return;
      await api('/api/v1/assistant/conversations/' + encodeURIComponent(c.id), { method: 'DELETE' });
      if (S.convId === c.id) S.convId = null;
      await loadConvs();
      if (S.convId) await openConv(S.convId);
      else renderLog([]);
    };
    row.appendChild(title);
    row.appendChild(del);
    list.appendChild(row);
  }
}

async function loadConvs() {
  const data = await api('/api/v1/assistant/conversations');
  S.convs = data.conversations || [];
  renderConvs();
}

async function openConv(id) {
  S.convId = id;
  const data = await api('/api/v1/assistant/conversations/' + encodeURIComponent(id));
  const conv = data.conversation;
  renderLog(conv.messages || []);
  renderConvs();
  const sel = $('project-select');
  sel.value = conv.project_id || '';
  $('attach-hint').textContent = conv.project_id
    ? 'Attached — the assistant can read this project (owner-verified).'
    : 'Attach a project to ask about it or propose changes to it.';
}

async function loadProjects() {
  try {
    const data = await api('/api/v1/projects');
    S.projects = data.projects || [];
  } catch (e) { S.projects = []; }
  const sel = $('project-select');
  for (const p of S.projects) {
    const opt = document.createElement('option');
    opt.value = p.id;
    opt.textContent = p.name || p.id;
    sel.appendChild(opt);
  }
}

async function loadStatus() {
  try {
    const cfg = await api('/api/v1/assistant/config');
    $('provider-box').innerHTML =
      `<strong>${esc(cfg.label)}</strong><br>` +
      `Model: ${esc(cfg.model || '—')}<br>` +
      `External provider: ${cfg.provider === 'local' ? 'not configured (local engine)' : (cfg.configured ? 'configured' : 'key missing')}<br>` +
      `Rate limit: ${cfg.rate_limit_per_minute}/min, ${cfg.rate_limit_per_hour}/hour`;
  } catch (e) {
    $('provider-box').textContent = 'Sign in to see the assistant status.';
  }
  try {
    const u = await api('/api/v1/assistant/usage');
    $('usage-box').innerHTML =
      `Requests: ${u.totals.requests}<br>` +
      `Tokens: ${u.totals.prompt_tokens + u.totals.completion_tokens}<br>` +
      `Estimated cost: $${Number(u.totals.cost_usd).toFixed(4)} (local engine: $0)`;
  } catch (e) {
    $('usage-box').textContent = '—';
  }
  try {
    const t = await api('/api/v1/assistant/tools');
    const byLab = {};
    for (const tool of t.tools || []) {
      (byLab[tool.lab] = byLab[tool.lab] || []).push(tool.label);
    }
    $('tools-box').innerHTML = Object.entries(byLab)
      .map(([lab, names]) => `<strong>${esc(lab)}</strong>: ${esc(names.join(', '))}`)
      .join('<br>');
  } catch (e) {
    $('tools-box').textContent = '—';
  }
}

async function sendMessage() {
  const box = $('composer');
  const text = box.value.trim();
  if (!text) return;
  if (!S.convId) {
    const created = await api('/api/v1/assistant/conversations', {
      method: 'POST', body: JSON.stringify({ title: text.slice(0, 60) }),
    });
    S.convId = created.conversation.id;
    await loadConvs();
  }
  box.value = '';
  $('chat-status').textContent = 'Running the tool…';
  try {
    const data = await api(
      '/api/v1/assistant/conversations/' + encodeURIComponent(S.convId) + '/messages',
      { method: 'POST', body: JSON.stringify({ content: text }) });
    await openConv(S.convId);
    await loadStatus();
    $('chat-status').textContent = '';
  } catch (e) {
    $('chat-status').textContent = 'Error: ' + e.message;
  }
}

document.addEventListener('DOMContentLoaded', async () => {
  const chips = [
    'gear train 20 and 40 teeth, 1000 rpm, 10 Nm',
    'voltage divider 10 V, R1 1k, R2 1k',
    'column buckling 3 m, 100x100 mm square',
    'properties of steel S355',
    'what is torque?',
    'inspect my project',
  ];
  for (const c of chips) {
    const b = document.createElement('button');
    b.className = 'chip';
    b.textContent = c;
    b.onclick = () => { $('composer').value = c; sendMessage(); };
    $('chips').appendChild(b);
  }
  $('send').onclick = sendMessage;
  $('composer').addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  $('new-chat').onclick = async () => {
    const created = await api('/api/v1/assistant/conversations', {
      method: 'POST', body: JSON.stringify({}),
    });
    S.convId = created.conversation.id;
    await loadConvs();
    await openConv(S.convId);
  };
  $('project-select').onchange = async (e) => {
    if (!S.convId) return;
    await api('/api/v1/assistant/conversations/' + encodeURIComponent(S.convId), {
      method: 'PATCH',
      body: JSON.stringify({ project_id: e.target.value || null }),
    });
    await openConv(S.convId);
  };
  // Proposal approve/deny buttons (delegated).
  $('chat-log').addEventListener('click', async (e) => {
    const ap = e.target.closest('[data-approve]');
    const dn = e.target.closest('[data-deny]');
    if (!ap && !dn) return;
    const pid = (ap || dn).dataset.approve || (ap || dn).dataset.deny;
    const decision = ap ? 'approve' : 'deny';
    $('chat-status').textContent = 'Applying decision…';
    await api('/api/v1/assistant/conversations/' + encodeURIComponent(S.convId)
      + '/proposals/' + encodeURIComponent(pid),
      { method: 'POST', body: JSON.stringify({ decision }) });
    await openConv(S.convId);
    $('chat-status').textContent = '';
  });
  if (!token()) {
    $('chat-log').innerHTML = '<p>Sign in first — the assistant is per-user, and every conversation belongs to your account. <a href="auth.html">Go to sign in →</a></p>';
    // The panels below would otherwise sit on "Loading…" forever:
    // loadStatus() is never reached for a guest.
    $('provider-box').textContent = 'Sign in to see the assistant status.';
    $('usage-box').textContent = 'Sign in to see your usage.';
    $('tools-box').textContent = 'Sign in to see what the assistant can do.';
    return;
  }
  await loadProjects();
  await loadConvs();
  await loadStatus();
  if (S.convs.length) await openConv(S.convs[0].id);
});
