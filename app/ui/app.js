/**
 * AI Manager — Client Application Logic
 * Integrates the SaaS interface with the local agentic automation backend.
 */

let currentPlan = null;
let currentExecutionMode = "safe";

// ----------------------------------------------------------------------------
// Chat Session & History Persistence
// ----------------------------------------------------------------------------
const SESSIONS_KEY = "ai_manager_chat_sessions_v2";
const ACTIVE_SESSION_KEY = "ai_manager_active_session_id";
const SIDEBAR_STATE_KEY = "ai_manager_sidebar_collapsed";

function loadSessions() {
  try {
    const raw = localStorage.getItem(SESSIONS_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (e) {
    return [];
  }
}

function saveSessions(sessions) {
  try {
    localStorage.setItem(SESSIONS_KEY, JSON.stringify(sessions));
  } catch (e) {
    console.error("Failed to save sessions:", e);
  }
}

let chatSessions = loadSessions();
let currentSessionId = localStorage.getItem(ACTIVE_SESSION_KEY) || ("session_" + Date.now());

function getCurrentSession() {
  let session = chatSessions.find(s => s.id === currentSessionId);
  if (!session) {
    session = {
      id: currentSessionId,
      title: "New Conversation",
      created_at: Date.now(),
      messages: []
    };
    chatSessions.unshift(session);
    saveSessions(chatSessions);
  }
  return session;
}

// ----------------------------------------------------------------------------
// Chat Command History (ArrowUp & ArrowDown in Chat Input)
// ----------------------------------------------------------------------------
const COMMAND_HISTORY_KEY = "ai_manager_command_history_v1";

function loadCommandHistory() {
  try {
    const raw = localStorage.getItem(COMMAND_HISTORY_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) return parsed;
    }
  } catch (e) {}

  const pastCmds = [];
  try {
    const sessions = loadSessions();
    sessions.forEach(s => {
      if (Array.isArray(s.messages)) {
        s.messages.forEach(m => {
          if (m && m.sender === "user" && typeof m.text === "string") {
            const trimmed = m.text.trim();
            if (trimmed && !pastCmds.includes(trimmed)) {
              pastCmds.push(trimmed);
            }
          }
        });
      }
    });
  } catch (e) {}
  return pastCmds;
}

function saveCommandHistory(history) {
  try {
    const trimmed = history.slice(-100);
    localStorage.setItem(COMMAND_HISTORY_KEY, JSON.stringify(trimmed));
  } catch (e) {}
}

let commandHistory = loadCommandHistory();
let historyIndex = -1;
let draftInputText = "";

function addMessageToCurrentSession(msg) {
  const session = getCurrentSession();
  if (session.messages.length === 0 && msg.sender === "user") {
    let t = msg.text ? (msg.text.slice(0, 30) + (msg.text.length > 30 ? "..." : "")) : "";
    if ((!t || t.toLowerCase().includes("what is this")) && msg.attachments && msg.attachments[0]) {
      t = msg.attachments[0].name.slice(0, 30);
    }
    session.title = t || "Conversation";
  }
  session.messages.push(msg);
  session.updated_at = Date.now();
  saveSessions(chatSessions);
  renderSidebarThreads();
}

let targetThreadMenuSessionId = null;
let pendingDeleteSessionId = null;
let lastDeletedSession = null;
let undoToastTimeout = null;

function renderSidebarThreads() {
  const container = document.getElementById("sidebar-threads-container");
  if (!container) return;

  const validSessions = chatSessions
    .filter(s => s.messages && s.messages.length > 0)
    .sort((a, b) => {
      if (Boolean(a.pinned) !== Boolean(b.pinned)) {
        return a.pinned ? -1 : 1;
      }
      return (b.updated_at || b.created_at || 0) - (a.updated_at || a.created_at || 0);
    });

  if (validSessions.length === 0) {
    container.innerHTML = `<div class="sidebar-thread-empty">No saved chats</div>`;
    return;
  }

  container.innerHTML = "";
  validSessions.forEach(s => {
    const item = document.createElement("div");
    item.className = `sidebar-thread-item ${s.id === currentSessionId ? "active" : ""} ${s.pinned ? "pinned" : ""}`;
    item.dataset.id = s.id;

    const pinBadgeHtml = s.pinned ? `
      <span class="thread-item-pin-badge" title="Pinned conversation">
        <svg width="11" height="11" viewBox="0 0 24 24" fill="currentColor">
          <line x1="12" y1="17" x2="12" y2="22" stroke="currentColor" stroke-width="2"></line>
          <path d="M5 17h14v-1.76a2 2 0 0 0-1.11-1.79l-1.78-.89A2 2 0 0 1 15 10.77V5a1 1 0 0 1 1-1h1V2H7v2h1a1 1 0 0 1 1 1v5.77a2 2 0 0 1-1.11 1.79l-1.78.89A2 2 0 0 0 5 15.24V17z"></path>
        </svg>
      </span>
    ` : "";

    item.innerHTML = `
      <div class="thread-item-content">
        ${pinBadgeHtml}
        <svg class="nav-icon" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
        <span class="thread-item-title" title="${escapeHtml(s.title || "Conversation")}">${escapeHtml(s.title || "Conversation")}</span>
      </div>
      <button class="thread-item-more" data-more-id="${s.id}" title="Conversation options">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="1.5"></circle>
          <circle cx="19" cy="12" r="1.5"></circle>
          <circle cx="5" cy="12" r="1.5"></circle>
        </svg>
      </button>
    `;

    const moreBtn = item.querySelector(".thread-item-more");
    moreBtn?.addEventListener("click", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openThreadContextMenu(s.id, moreBtn);
    });

    const titleSpan = item.querySelector(".thread-item-title");
    titleSpan?.addEventListener("dblclick", (e) => {
      e.preventDefault();
      e.stopPropagation();
      startRenameThread(s.id);
    });

    item.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      openThreadContextMenu(s.id, null, e);
    });

    item.addEventListener("click", (e) => {
      if (e.target.closest(".thread-rename-input") || e.target.closest(".thread-item-more")) {
        return;
      }
      loadChatSession(s.id);
    });

    container.appendChild(item);
  });
}

function openThreadContextMenu(sessionId, anchorBtn, mouseEvent) {
  const menu = document.getElementById("thread-context-menu");
  if (!menu) return;

  if (targetThreadMenuSessionId === sessionId && !menu.classList.contains("hidden")) {
    closeThreadContextMenu();
    return;
  }

  targetThreadMenuSessionId = sessionId;
  const session = chatSessions.find(s => s.id === sessionId);

  const pinLabel = document.getElementById("menu-pin-label");
  if (pinLabel && session) {
    pinLabel.textContent = session.pinned ? "Unpin conversation" : "Pin to top";
  }

  menu.classList.remove("hidden");
  menu.style.display = "block";

  if (anchorBtn) {
    const rect = anchorBtn.getBoundingClientRect();
    menu.style.top = `${Math.min(rect.bottom + 4, window.innerHeight - 180)}px`;
    menu.style.left = `${Math.max(10, Math.min(rect.left, window.innerWidth - 180))}px`;
    document.querySelectorAll(".thread-item-more.open").forEach(b => b.classList.remove("open"));
    anchorBtn.classList.add("open");
  } else if (mouseEvent) {
    menu.style.top = `${Math.min(mouseEvent.clientY, window.innerHeight - 180)}px`;
    menu.style.left = `${Math.min(mouseEvent.clientX, window.innerWidth - 180)}px`;
  }
}

function closeThreadContextMenu() {
  const menu = document.getElementById("thread-context-menu");
  if (menu) {
    menu.classList.add("hidden");
    menu.style.display = "none";
  }
  document.querySelectorAll(".thread-item-more.open").forEach(b => b.classList.remove("open"));
  targetThreadMenuSessionId = null;
}

function togglePinThread(sessionId) {
  closeThreadContextMenu();
  const session = chatSessions.find(s => s.id === sessionId);
  if (!session) return;
  session.pinned = !session.pinned;
  saveSessions(chatSessions);
  renderSidebarThreads();
}

function startRenameThread(sessionId) {
  closeThreadContextMenu();
  const item = document.querySelector(`.sidebar-thread-item[data-id="${sessionId}"]`);
  const titleSpan = item?.querySelector(".thread-item-title");
  const session = chatSessions.find(s => s.id === sessionId);
  if (!item || !titleSpan || !session) return;

  const currentTitle = session.title || "Conversation";
  const input = document.createElement("input");
  input.type = "text";
  input.className = "thread-rename-input";
  input.value = currentTitle;

  titleSpan.replaceWith(input);
  input.focus();
  input.select();

  let finished = false;
  const finishRename = () => {
    if (finished) return;
    finished = true;
    const val = input.value.trim();
    session.title = val || currentTitle;
    saveSessions(chatSessions);
    renderSidebarThreads();
  };

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      finishRename();
    } else if (e.key === "Escape") {
      e.preventDefault();
      finished = true;
      renderSidebarThreads();
    }
  });

  input.addEventListener("blur", finishRename);
}

function exportThread(sessionId) {
  closeThreadContextMenu();
  const session = chatSessions.find(s => s.id === sessionId);
  if (!session) return;

  let text = `# ${session.title || "Conversation"}\nDate: ${new Date(session.created_at).toLocaleString()}\n\n`;
  (session.messages || []).forEach(m => {
    const role = m.sender === "user" ? "User" : "Assistant";
    const body = m.text || (m.data ? m.data.message : "");
    text += `### ${role}:\n${body}\n\n`;
  });

  navigator.clipboard.writeText(text).then(() => {
    // Subtle visual indicator
    const notifyBtn = document.getElementById("btn-notifications");
    if (notifyBtn) {
      const orig = notifyBtn.title;
      notifyBtn.title = "Transcript copied to clipboard!";
      setTimeout(() => { notifyBtn.title = orig; }, 2000);
    }
  }).catch(() => {
    const blob = new Blob([text], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${(session.title || "chat").replace(/[^a-zA-Z0-9_-]/g, "_")}.md`;
    a.click();
    URL.revokeObjectURL(url);
  });
}

function promptDeleteThread(sessionId) {
  closeThreadContextMenu();
  const session = chatSessions.find(s => s.id === sessionId);
  if (!session) return;

  pendingDeleteSessionId = sessionId;
  const modal = document.getElementById("delete-thread-modal");
  const desc = document.getElementById("delete-thread-prompt-text");
  if (desc) {
    desc.textContent = `Are you sure you want to delete "${session.title || "this conversation"}"? This action cannot be undone.`;
  }
  modal?.classList.remove("hidden");
}

function closeDeleteModal() {
  document.getElementById("delete-thread-modal")?.classList.add("hidden");
  pendingDeleteSessionId = null;
}

function showUndoToast(session) {
  lastDeletedSession = session;
  const toast = document.getElementById("toast-undo-container");
  const text = document.getElementById("toast-undo-text");
  if (!toast) return;

  if (text) {
    text.textContent = `Deleted "${session.title || "Conversation"}"`;
  }
  toast.classList.remove("hidden");

  if (undoToastTimeout) clearTimeout(undoToastTimeout);
  undoToastTimeout = setTimeout(() => {
    toast.classList.add("hidden");
    lastDeletedSession = null;
  }, 6000);
}

function handleUndoDelete() {
  if (!lastDeletedSession) return;
  const restoredSession = lastDeletedSession;
  chatSessions.push(restoredSession);
  saveSessions(chatSessions);
  lastDeletedSession = null;
  const toast = document.getElementById("toast-undo-container");
  toast?.classList.add("hidden");
  if (undoToastTimeout) clearTimeout(undoToastTimeout);
  renderSidebarThreads();
  loadChatSession(restoredSession.id);
}

function deleteSession(sessionId) {
  const targetSession = chatSessions.find(s => s.id === sessionId);
  chatSessions = chatSessions.filter(s => s.id !== sessionId);
  saveSessions(chatSessions);
  if (targetSession) {
    showUndoToast(targetSession);
  }
  if (currentSessionId === sessionId) {
    startNewTaskSession();
  } else {
    renderSidebarThreads();
  }
}

function startNewTaskSession() {
  currentSessionId = "session_" + Date.now();
  localStorage.setItem(ACTIVE_SESSION_KEY, currentSessionId);

  const heroStage = document.getElementById("hero-stage");
  const chatStream = document.getElementById("chat-stream-container");
  const promptInput = document.getElementById("ai-main-input");
  const attachmentTray = document.getElementById("attachment-tray");

  if (chatStream) {
    chatStream.innerHTML = "";
    chatStream.classList.add("hidden");
  }
  heroStage?.classList.remove("hidden");
  if (attachmentTray) {
    attachmentTray.innerHTML = "";
    attachmentTray.classList.add("hidden");
  }
  if (promptInput) {
    promptInput.value = "";
    promptInput.style.height = "auto";
    promptInput.focus();
  }
  historyIndex = -1;
  draftInputText = "";

  document.getElementById("chat-viewport")?.scrollTo({ top: 0 });
  renderSidebarThreads();
}

function loadChatSession(sessionId) {
  currentSessionId = sessionId;
  localStorage.setItem(ACTIVE_SESSION_KEY, sessionId);
  historyIndex = -1;
  draftInputText = "";

  const session = chatSessions.find(s => s.id === sessionId);
  const heroStage = document.getElementById("hero-stage");
  const chatStream = document.getElementById("chat-stream-container");

  if (!session || !session.messages || session.messages.length === 0) {
    startNewTaskSession();
    return;
  }

  heroStage?.classList.add("hidden");
  if (chatStream) {
    chatStream.innerHTML = "";
    chatStream.classList.remove("hidden");

    session.messages.forEach(m => {
      if (m.sender === "user") {
        appendUserMessage(m.text, m.attachments || [], false);
      } else {
        appendAssistantMessage(m.data || { type: "conversation", message: m.text }, false);
      }
    });
  }

  renderSidebarThreads();
  scrollToBottom(true);
  requestAnimationFrame(() => {
    const vp = document.getElementById("chat-viewport");
    if (vp) vp.scrollTop = vp.scrollHeight;
  });
}

// ----------------------------------------------------------------------------
// Markdown Formatter (Zero external dependency)
// ----------------------------------------------------------------------------
function stripEmojis(text) {
  if (!text) return "";
  return text.replace(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}\u{FE00}-\u{FE0F}\u{1F900}-\u{1F9FF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}]/gu, "").trim();
}

function escapeHtml(text) {
  if (!text) return "";
  const clean = stripEmojis(String(text));
  return clean
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function formatBasicMarkdown(str) {
  if (!str) return "";
  let h = escapeHtml(str);
  h = h.replace(/^### (.*$)/gim, '<h3 class="chat-md-h3">$1</h3>');
  h = h.replace(/^## (.*$)/gim, '<h2 class="chat-md-h2">$1</h2>');
  h = h.replace(/^# (.*$)/gim, '<h1 class="chat-md-h1">$1</h1>');
  h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  h = h.replace(/(^|[^*])\*([^*]+)\*/g, '$1<em>$2</em>');
  h = h.replace(/`([^`]+)`/g, '<code>$1</code>');
  h = h.replace(/\n\n+/g, '<br><br>');
  h = h.replace(/\n/g, '<br>');
  return h;
}

function formatEmailSummaryDeck(text) {
  if (!text) return null;
  const hasSummaryPattern = /(?:^|\n)(?:#|\*\*#)?1\.\s*(?:\[[A-Za-z\s]+\])?/i.test(text) &&
                            /(?:From|Key Points|Required Action)/i.test(text);
  if (!hasSummaryPattern) return null;

  const firstItemIdx = text.search(/(?:^|\n)(?=(?:#|\*\*#)1\.\s*)/i);
  if (firstItemIdx === -1) return null;

  const introText = text.slice(0, firstItemIdx).trim();
  const itemsText = text.slice(firstItemIdx);

  const parts = itemsText.split(/(?:^|\n)(?=(?:#|\*\*#)\d+\.\s*)/g);
  const items = [];

  for (const part of parts) {
    const trimmed = part.trim();
    if (!trimmed.match(/^(?:#|\*\*#)\d+\./)) continue;
    const lines = trimmed.split("\n").map(l => l.trim()).filter(Boolean);
    const headerLine = lines[0] || "";
    const headerMatch = headerLine.match(/^(?:#|\*\*#)(\d+)\.\s*(?:\[([^\]]+)\])?\s*(.*)$/);
    if (!headerMatch) continue;

    const num = headerMatch[1];
    const priority = (headerMatch[2] || "NORMAL").toUpperCase().trim();
    let subject = headerMatch[3].replace(/^\*\*|\*\*$/g, "").trim();

    let from = "Unknown";
    let keyPoints = "";
    let action = "None (Informational update)";

    for (let i = 1; i < lines.length; i++) {
      const line = lines[i];
      if (line.match(/^(?:•|\*|-)?\s*From:/i)) {
        from = line.replace(/^(?:•|\*|-)?\s*From:\s*/i, "").replace(/^`|`$/g, "").trim();
      } else if (line.match(/^(?:•|\*|-)?\s*Key Points:/i)) {
        keyPoints = line.replace(/^(?:•|\*|-)?\s*Key Points:\s*/i, "").trim();
      } else if (line.match(/^(?:•|\*|-)?\s*Required Action:/i)) {
        action = line.replace(/^(?:•|\*|-)?\s*Required Action:\s*/i, "").trim();
      } else if (keyPoints && !line.match(/^(?:•|\*|-)?\s*(?:Required Action|From):/i)) {
        keyPoints += " " + line;
      }
    }

    if (!keyPoints) {
      keyPoints = "Automated notification or social feed activity from sender.";
    }

    items.push({ num, priority, subject, from, keyPoints, action });
  }

  if (items.length === 0) return null;

  const totalCount = items.length;
  const urgentCount = items.filter(it => ["URGENT", "SECURITY", "HIGH"].includes(it.priority)).length;
  const actionCount = items.filter(it => !it.action.toLowerCase().includes("none")).length;

  let introHtml = "";
  if (introText) {
    introHtml = `<div class="chat-md-intro" style="margin-bottom: 12px; font-weight: 500; color: var(--text-main); font-size: 13.5px;">${formatBasicMarkdown(introText)}</div>`;
  }

  const cardsHtml = items.map(item => {
    const pLower = item.priority.toLowerCase();
    const prioCardClass = "prio-card-" + (pLower.includes("urgent") ? "urgent" : pLower.includes("sec") ? "security" : pLower.includes("high") ? "high" : pLower.includes("low") ? "low" : "normal");
    const prioBadgeClass = "prio-" + (pLower.includes("urgent") ? "urgent" : pLower.includes("sec") ? "security" : pLower.includes("high") ? "high" : pLower.includes("low") ? "low" : "normal");
    const isActionNeeded = !item.action.toLowerCase().includes("none");

    return `
      <div class="email-summary-card ${prioCardClass}" data-priority="${pLower}" data-action="${isActionNeeded ? 'true' : 'false'}">
        <div class="esc-header-row">
          <div class="esc-header-left">
            <span class="esc-num-badge">#${String(item.num).padStart(2, "0")}</span>
            <span class="esc-prio-badge ${prioBadgeClass}">
              <span class="prio-indicator-dot"></span>
              ${escapeHtml(item.priority)}
            </span>
          </div>
          <div class="esc-sender-badge" title="From: ${escapeHtml(item.from)}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
            <span>${escapeHtml(item.from)}</span>
          </div>
        </div>

        <h4 class="esc-title">${escapeHtml(item.subject)}</h4>

        <div class="esc-key-points">
          <div class="esc-points-header">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="8" y1="6" x2="21" y2="6"/><line x1="8" y1="12" x2="21" y2="12"/><line x1="8" y1="18" x2="21" y2="18"/><line x1="3" y1="6" x2="3.01" y2="6"/><line x1="3" y1="12" x2="3.01" y2="12"/><line x1="3" y1="18" x2="3.01" y2="18"/></svg>
            Key Takeaways
          </div>
          <p class="esc-points-body">${escapeHtml(item.keyPoints)}</p>
        </div>

        <div class="esc-footer-row">
          <div class="esc-action-callout ${isActionNeeded ? 'action-required' : 'action-none'}">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              ${isActionNeeded 
                ? '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>' 
                : '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>'}
            </svg>
            <span>${escapeHtml(item.action)}</span>
          </div>
          <button type="button" class="esc-view-inbox-btn" data-search="${escapeHtml(item.subject)}">
            View in Inbox &rarr;
          </button>
        </div>
      </div>
    `;
  }).join("");

  return `
    ${introHtml}
    <div class="email-summary-deck">
      <div class="deck-top-stat-bar">
        <div class="deck-stat-group">
          <div class="deck-stat-chip total">
            <span>${totalCount}</span> Emails Summarized
          </div>
          <div class="deck-stat-chip urgent">
            <span>${urgentCount}</span> Urgent / High
          </div>
          <div class="deck-stat-chip action">
            <span>${actionCount}</span> Need Action
          </div>
        </div>
        <div class="deck-filter-pills">
          <button type="button" class="deck-filter-btn active" data-filter="all">All (${totalCount})</button>
          <button type="button" class="deck-filter-btn" data-filter="action">Action Needed (${actionCount})</button>
          <button type="button" class="deck-filter-btn" data-filter="urgent">Urgent (${urgentCount})</button>
        </div>
      </div>
      <div class="deck-cards-list">
        ${cardsHtml}
      </div>
    </div>
  `;
}

function formatMarkdown(text) {
  if (!text) return "";

  // Check if text is an executive email summary list
  const emailDeckHtml = formatEmailSummaryDeck(text);
  if (emailDeckHtml) {
    return emailDeckHtml;
  }

  // 1. Preserve and extract Fenced Code Blocks
  const codeBlocks = [];
  let html = escapeHtml(text);
  html = html.replace(/```([a-zA-Z0-9_-]*)\n?([\s\S]*?)```/g, (match, lang, code) => {
    const languageLabel = lang || "code";
    const block = `
      <div class="code-block-container">
        <div class="code-block-header">
          <span>${languageLabel}</span>
          <button type="button" class="btn-copy-code">Copy</button>
        </div>
        <pre><code>${code.trim()}</code></pre>
      </div>
    `;
    const token = `__CODEBLOCK_${codeBlocks.length}__`;
    codeBlocks.push(block);
    return token;
  });

  // 2. Preserve and extract Markdown Tables
  const tableBlocks = [];
  const tableRegex = /((?:^[ \t]*\|.+?\|[ \t]*\n)(?:^[ \t]*\|[ \t]*(?:[-:| ]+)\|[ \t]*\n)(?:^[ \t]*\|.+?\|[ \t]*(?:\n|$))+)/gm;
  html = html.replace(tableRegex, (match) => {
    const lines = match.trim().split("\n").map(l => l.trim()).filter(Boolean);
    if (lines.length < 2) return match;

    const parseRow = (line) => {
      return line
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map(cell => cell.trim());
    };

    const formatCell = (c) => {
      return c
        .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
        .replace(/`([^`]+)`/g, "<code>$1</code>");
    };

    const headerCells = parseRow(lines[0]);
    const bodyLines = lines.slice(2);

    let tableHtml = '<div class="chat-table-wrapper"><table class="chat-table"><thead><tr>';
    headerCells.forEach(h => {
      tableHtml += `<th>${formatCell(h)}</th>`;
    });
    tableHtml += '</tr></thead><tbody>';

    bodyLines.forEach(line => {
      const cells = parseRow(line);
      tableHtml += '<tr>';
      cells.forEach(cell => {
        tableHtml += `<td>${formatCell(cell)}</td>`;
      });
      tableHtml += '</tr>';
    });
    tableHtml += '</tbody></table></div>';

    const token = `__TABLE_${tableBlocks.length}__`;
    tableBlocks.push(tableHtml);
    return token;
  });

  // 3. Headings
  html = html.replace(/^### (.*$)/gim, '<h3 class="chat-md-h3">$1</h3>');
  html = html.replace(/^## (.*$)/gim, '<h2 class="chat-md-h2">$1</h2>');
  html = html.replace(/^# (.*$)/gim, '<h1 class="chat-md-h1">$1</h1>');

  // 4. Inline Code: `code`
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // 5. Bold & Italics: **text**, *text*
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");

  // 6. Bullet Lists: - item or * item
  html = html.replace(/^\s*[-*]\s+(.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>(?:(?!<ul)[^<]|<(?!\/ul>))*<\/li>)/gs, "<ul>$1</ul>");

  // 7. Line breaks
  html = html.replace(/\n\n+/g, "<br><br>");
  html = html.replace(/\n/g, "<br>");

  // 8. Restore Tables & Code Blocks
  tableBlocks.forEach((tbl, idx) => {
    html = html.replace(`__TABLE_${idx}__`, tbl);
  });
  codeBlocks.forEach((cb, idx) => {
    html = html.replace(`__CODEBLOCK_${idx}__`, cb);
  });

  return html;
}

// ----------------------------------------------------------------------------
// Top-Row LLM Engine Toggle Control
// ----------------------------------------------------------------------------
const LLM_TOGGLE_STORAGE_KEY = "ai_manager_llm_toggle_active";

function isLlmEngineEnabled() {
  const stored = localStorage.getItem(LLM_TOGGLE_STORAGE_KEY);
  return stored === "1";
}

let lastLlmStatusData = null;

function updateChatModelBadge(data, isEnabled) {
  if (data) lastLlmStatusData = data;
  const badge = document.getElementById("chat-model-badge");
  const dot = document.getElementById("chat-model-badge-dot");
  const name = document.getElementById("chat-model-badge-name");
  if (!badge || !name) return;

  const enabled = isEnabled !== undefined ? isEnabled : isLlmEngineEnabled();
  if (!enabled) {
    badge.className = "chat-model-badge offline";
    if (dot) dot.className = "chat-model-badge-dot offline";
    name.textContent = "LLM Off";
    badge.title = "LLM inference is toggled OFF (Manual mode). Click to configure or enable.";
    return;
  }

  const status = data || lastLlmStatusData;
  if (!status) {
    name.textContent = "Checking...";
    return;
  }

  const provider = (status.provider || "ollama").toLowerCase();
  if (provider === "groq") {
    const rawModel = status.groq_model || "llama-3.3-70b-versatile";
    const shortModel = rawModel.split("/").pop();
    const isOnline = Boolean(status.groq_configured && status.llm_available);
    badge.className = `chat-model-badge ${isOnline ? "online groq" : "warning"}`;
    if (dot) dot.className = `chat-model-badge-dot ${isOnline ? "online" : "warning"}`;
    name.textContent = `⚡ Groq: ${shortModel}`;
    badge.title = isOnline
      ? `Active Model: Groq Cloud (${rawModel}). Click to configure.`
      : `Groq is not configured. Click to set API key.`;
  } else {
    const rawModel = status.ollama_model || "qwen2.5:3b";
    const isOnline = Boolean(status.ollama_online);
    badge.className = `chat-model-badge ${isOnline ? "online ollama" : "offline"}`;
    if (dot) dot.className = `chat-model-badge-dot ${isOnline ? "online" : "offline"}`;
    name.textContent = `● Local: ${rawModel}`;
    badge.title = isOnline
      ? `Active Model: Local Ollama (${rawModel}). Click to configure.`
      : `Local Ollama is offline (Port 11434). Click to start.`;
  }
}

function updateLlmToggleUI(enabled) {
  const checkbox = document.getElementById("llm-toggle-checkbox");
  const dot = document.getElementById("llm-toggle-dot");
  const text = document.getElementById("llm-toggle-text");
  const wrap = document.getElementById("header-llm-toggle-wrap");

  if (checkbox) checkbox.checked = enabled;
  if (text) text.textContent = enabled ? "LLM On" : "LLM Off";
  if (dot) {
    dot.className = "llm-toggle-status-dot " + (enabled ? "online" : "offline");
  }
  if (wrap) {
    wrap.classList.toggle("active", enabled);
    wrap.title = enabled
      ? "Local LLM inference is ON. Click to toggle OFF (pure offline mode)."
      : "Local LLM inference is OFF (instant offline mode). Click to toggle ON.";
  }
  updateChatModelBadge(lastLlmStatusData, enabled);
}

function initLlmToggle() {
  const checkbox = document.getElementById("llm-toggle-checkbox");
  const wrap = document.getElementById("header-llm-toggle-wrap");
  const btnGear = document.getElementById("btn-open-llm-modal");
  const chatModelBadge = document.getElementById("chat-model-badge");
  const current = isLlmEngineEnabled();
  updateLlmToggleUI(current);

  const handleToggle = (newVal) => {
    localStorage.setItem(LLM_TOGGLE_STORAGE_KEY, newVal ? "1" : "0");
    updateLlmToggleUI(newVal);
  };

  checkbox?.addEventListener("change", (e) => {
    e.stopPropagation();
    handleToggle(checkbox.checked);
  });

  btnGear?.addEventListener("click", (e) => {
    e.stopPropagation();
    openLlmConfigModal();
  });

  chatModelBadge?.addEventListener("click", (e) => {
    e.stopPropagation();
    openLlmConfigModal();
  });

  wrap?.addEventListener("click", (e) => {
    if (e.target.closest("#btn-open-llm-modal")) return;
    if (e.target !== checkbox && !e.target.closest(".llm-switch")) {
      // If LLM is currently off and user clicks the bar, check if LLM is ready or open config
      fetch("/api/llm/status").then(r => r.json()).then(st => {
        if (!st.llm_available && !checkbox.checked) {
          openLlmConfigModal();
        } else {
          const next = !checkbox.checked;
          checkbox.checked = next;
          handleToggle(next);
        }
      }).catch(() => {
        const next = !checkbox.checked;
        checkbox.checked = next;
        handleToggle(next);
      });
    }
  });

  initLlmConfigModal(handleToggle);
  fetchLlmStatus();
}

let _detectGpuFn = null;

function openLlmConfigModal() {
  const modal = document.getElementById("llm-config-modal");
  if (modal) modal.classList.remove("hidden");
  fetchLlmStatus();
  if (typeof _detectGpuFn === "function") {
    _detectGpuFn();
  }
}

function closeLlmConfigModal() {
  const modal = document.getElementById("llm-config-modal");
  if (modal) modal.classList.add("hidden");
}

async function fetchLlmStatus() {
  const elActiveProv = document.getElementById("llm-cfg-active-prov");
  const elOllamaStatus = document.getElementById("llm-cfg-ollama-status");
  const elGroqStatus = document.getElementById("llm-cfg-groq-status");
  const inputModel = document.getElementById("cfg-ollama-model");
  const inputGroqModel = document.getElementById("cfg-groq-model");

  try {
    const res = await fetch("/api/llm/status");
    const data = await res.json();
    lastLlmStatusData = data;
    updateChatModelBadge(data);

    if (elActiveProv) elActiveProv.textContent = data.provider || "ollama";
    if (elOllamaStatus) {
      if (data.ollama_online) {
        elOllamaStatus.className = "risk-badge risk-low";
        elOllamaStatus.textContent = `ONLINE (${data.ollama_model || "qwen2.5:3b"})`;
      } else {
        elOllamaStatus.className = "risk-badge risk-high";
        elOllamaStatus.textContent = "OFFLINE (Port 11434)";
      }
    }
    if (elGroqStatus) {
      if (data.groq_configured) {
        elGroqStatus.className = "risk-badge risk-low";
        elGroqStatus.textContent = `CONFIGURED (${data.groq_key_preview || "Active"})`;
      } else {
        elGroqStatus.className = "risk-badge risk-med";
        elGroqStatus.textContent = "NOT CONFIGURED";
      }
    }
    if (inputModel && data.ollama_model) {
      inputModel.value = data.ollama_model;
    }
    if (inputGroqModel && data.groq_model) {
      inputGroqModel.value = data.groq_model;
    }
  } catch (_) {}
}

function initLlmConfigModal(onActivateLlm) {
  const modal = document.getElementById("llm-config-modal");
  const btnClose = document.getElementById("btn-close-llm-modal");
  const btnCloseX = document.getElementById("btn-close-llm-modal-x");
  const tabBtnGroq = document.getElementById("llm-tab-btn-groq");
  const tabBtnOllama = document.getElementById("llm-tab-btn-ollama");
  const secGroq = document.getElementById("llm-section-groq");
  const secOllama = document.getElementById("llm-section-ollama");
  const inputGroqKey = document.getElementById("cfg-groq-key");
  const inputGroqModel = document.getElementById("cfg-groq-model");
  const inputOllamaModel = document.getElementById("cfg-ollama-model");
  const btnSaveGroq = document.getElementById("btn-save-groq-cfg");
  const btnSaveOllama = document.getElementById("btn-save-ollama-cfg");
  const btnStartOllama = document.getElementById("btn-start-local-ollama");
  const feedbackEl = document.getElementById("llm-cfg-feedback");

  // --- Compute mode helpers (using <select> instead of radios) ---
  function getSelectedComputeMode() {
    const sel = document.getElementById("ollama-compute-select");
    return sel ? sel.value : "cpu";
  }

  function updateGpuStatus(gpuData) {
    const badge = document.getElementById("ollama-gpu-badge");
    const sub = document.getElementById("ollama-gpu-detect-sub");
    const sel = document.getElementById("ollama-compute-select");
    if (!badge) return;

    if (gpuData.gpu_available) {
      badge.className = "risk-badge risk-low";
      badge.textContent = gpuData.gpu_name + " (" + gpuData.gpu_type.toUpperCase() + ")";
      if (sub) sub.textContent = "GPU inference available";
      if (sel) sel.value = "gpu";
    } else {
      badge.className = "risk-badge risk-high";
      badge.textContent = gpuData.gpu_name || "No capable GPU";
      if (sub) sub.textContent = "CPU mode recommended";
      if (sel) sel.value = "cpu";
    }
    if (gpuData.forced_cpu_mode) {
      if (sub) sub.textContent += " · CPU mode saved";
      if (sel) sel.value = "cpu";
    }
  }

  let _lastGpuData = null;
  let _gpuDetecting = false;

  async function detectGpu(force = false) {
    if (_lastGpuData && !force) {
      updateGpuStatus(_lastGpuData);
      return;
    }
    if (_gpuDetecting) return;
    _gpuDetecting = true;
    try {
      const res = await fetch("/api/llm/gpu_status");
      if (!res.ok) {
        throw new Error("HTTP " + res.status);
      }
      const data = await res.json();
      _lastGpuData = data;
      updateGpuStatus(data);
    } catch (_) {
      const badge = document.getElementById("ollama-gpu-badge");
      const sub = document.getElementById("ollama-gpu-detect-sub");
      if (badge) {
        badge.className = "risk-badge risk-med";
        badge.textContent = "Detection unavailable";
      }
      if (sub) sub.textContent = "Defaulting to CPU mode";
      const sel = document.getElementById("ollama-compute-select");
      if (sel) sel.value = "cpu";
    } finally {
      _gpuDetecting = false;
    }
  }
  _detectGpuFn = detectGpu;


  const setTab = (tab) => {
    if (tab === "groq") {
      tabBtnGroq?.classList.add("pill-btn-dark");
      tabBtnGroq?.classList.remove("pill-btn-outline");
      tabBtnOllama?.classList.add("pill-btn-outline");
      tabBtnOllama?.classList.remove("pill-btn-dark");
      if (secGroq) secGroq.style.display = "block";
      if (secOllama) secOllama.style.display = "none";
    } else {
      tabBtnOllama?.classList.add("pill-btn-dark");
      tabBtnOllama?.classList.remove("pill-btn-outline");
      tabBtnGroq?.classList.add("pill-btn-outline");
      tabBtnGroq?.classList.remove("pill-btn-dark");
      if (secGroq) secGroq.style.display = "none";
      if (secOllama) secOllama.style.display = "block";
      // Auto-detect GPU when switching to Ollama tab
      detectGpu();
    }
  };


  tabBtnGroq?.addEventListener("click", () => setTab("groq"));
  tabBtnOllama?.addEventListener("click", () => setTab("ollama"));

  btnClose?.addEventListener("click", closeLlmConfigModal);
  btnCloseX?.addEventListener("click", closeLlmConfigModal);
  modal?.addEventListener("click", (e) => {
    if (e.target === modal) closeLlmConfigModal();
  });

  const inputGroqCustom = document.getElementById("cfg-groq-model-custom");
  const btnFetchGroqModels = document.getElementById("btn-fetch-groq-models");
  const lblModelsCount = document.getElementById("cfg-groq-models-count");

  inputGroqModel?.addEventListener("change", () => {
    if (inputGroqModel.value === "__custom__") {
      if (inputGroqCustom) {
        inputGroqCustom.style.display = "block";
        inputGroqCustom.focus();
      }
    } else {
      if (inputGroqCustom) inputGroqCustom.style.display = "none";
    }
  });

  btnFetchGroqModels?.addEventListener("click", async () => {
    const key = inputGroqKey?.value.trim();
    if (!key) {
      if (feedbackEl) {
        feedbackEl.style.display = "block";
        feedbackEl.style.background = "#fef2f2";
        feedbackEl.style.color = "#991b1b";
        feedbackEl.textContent = "Please enter your Groq API key first to query your available models.";
      }
      return;
    }

    if (feedbackEl) {
      feedbackEl.style.display = "block";
      feedbackEl.style.background = "#eff6ff";
      feedbackEl.style.color = "#1e40af";
      feedbackEl.textContent = "Fetching available models from Groq account...";
    }

    try {
      btnFetchGroqModels.disabled = true;
      const res = await fetch("/api/llm/groq/models", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ groq_api_key: key }),
      });
      const data = await res.json();
      if (data.success && Array.isArray(data.models) && data.models.length > 0) {
        inputGroqModel.innerHTML = "";
        data.models.forEach((mid) => {
          const opt = document.createElement("option");
          opt.value = mid;
          opt.textContent = mid;
          inputGroqModel.appendChild(opt);
        });
        const customOpt = document.createElement("option");
        customOpt.value = "__custom__";
        customOpt.textContent = "Custom Model (Enter below)...";
        inputGroqModel.appendChild(customOpt);

        if (lblModelsCount) lblModelsCount.textContent = `${data.models.length} models found`;
        if (feedbackEl) {
          feedbackEl.style.background = "#f0fdf4";
          feedbackEl.style.color = "#166534";
          feedbackEl.textContent = `Loaded ${data.models.length} models from your Groq account.`;
        }
      } else {
        if (feedbackEl) {
          feedbackEl.style.background = "#fef2f2";
          feedbackEl.style.color = "#991b1b";
          feedbackEl.textContent = data.error || "Could not fetch models.";
        }
      }
    } catch (e) {
      if (feedbackEl) {
        feedbackEl.style.background = "#fef2f2";
        feedbackEl.style.color = "#991b1b";
        feedbackEl.textContent = "Error: " + e.message;
      }
    } finally {
      btnFetchGroqModels.disabled = false;
    }
  });

  btnSaveGroq?.addEventListener("click", async () => {
    const key = inputGroqKey?.value.trim();
    let model = inputGroqModel?.value || "llama-3.3-70b-versatile";
    if (model === "__custom__") {
      model = inputGroqCustom?.value.trim() || "llama-3.3-70b-versatile";
    }

    if (!key) {
      if (feedbackEl) {
        feedbackEl.style.display = "block";
        feedbackEl.style.background = "#fef2f2";
        feedbackEl.style.color = "#991b1b";
        feedbackEl.textContent = "Please enter your Groq API key (starts with gsk_).";
      }
      return;
    }

    if (feedbackEl) {
      feedbackEl.style.display = "block";
      feedbackEl.style.background = "#eff6ff";
      feedbackEl.style.color = "#1e40af";
      feedbackEl.textContent = `Validating Groq API connection with ${model}...`;
    }

    try {
      btnSaveGroq.disabled = true;
      const res = await fetch("/api/llm/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: "groq", groq_api_key: key, groq_model: model })
      });
      let data = {};
      try { data = await res.json(); } catch (_) {}

      if (res.ok && data.success) {
        const activeM = data.model || model;
        if (feedbackEl) {
          feedbackEl.style.background = "#f0fdf4";
          feedbackEl.style.color = "#166534";
          feedbackEl.textContent = `Groq connected successfully (${activeM})! Activating LLM.`;
        }
        if (onActivateLlm) onActivateLlm(true);
        fetchLlmStatus();
        setTimeout(closeLlmConfigModal, 1400);
      } else {
        if (feedbackEl) {
          feedbackEl.style.background = "#fef2f2";
          feedbackEl.style.color = "#991b1b";
          feedbackEl.textContent = data.error || data.detail || `Connection error (HTTP ${res.status})`;
        }
      }
    } catch (e) {
      if (feedbackEl) {
        feedbackEl.style.background = "#fef2f2";
        feedbackEl.style.color = "#991b1b";
        feedbackEl.textContent = "Error: " + e.message;
      }
    } finally {
      btnSaveGroq.disabled = false;
    }
  });

  btnSaveOllama?.addEventListener("click", async () => {
    const model = inputOllamaModel?.value.trim() || "qwen2.5:3b";
    try {
      btnSaveOllama.disabled = true;
      const res = await fetch("/api/llm/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: "ollama",
          ollama_model: model,
          cpu_mode: getSelectedComputeMode() === "cpu"
        })
      });
      let data = {};
      try { data = await res.json(); } catch (_) {}

      if (res.ok && data.success) {
        if (feedbackEl) {
          feedbackEl.style.display = "block";
          feedbackEl.style.background = "#f0fdf4";
          feedbackEl.style.color = "#166534";
          feedbackEl.textContent = `Provider set to Local Ollama (${model}).`;
        }
        if (onActivateLlm) onActivateLlm(true);
        fetchLlmStatus();
        setTimeout(closeLlmConfigModal, 1400);
      } else {
        if (feedbackEl) {
          feedbackEl.style.display = "block";
          feedbackEl.style.background = "#fef2f2";
          feedbackEl.style.color = "#991b1b";
          feedbackEl.textContent = data.error || data.detail || `Connection error (HTTP ${res.status})`;
        }
      }
    } catch (e) {
      if (feedbackEl) {
        feedbackEl.style.display = "block";
        feedbackEl.style.background = "#fef2f2";
        feedbackEl.style.color = "#991b1b";
        feedbackEl.textContent = "Error: " + e.message;
      }
    } finally {
      btnSaveOllama.disabled = false;
    }
  });

  btnStartOllama?.addEventListener("click", async () => {
    const mode = getSelectedComputeMode();
    const isCpu = mode === "cpu";
    if (feedbackEl) {
      feedbackEl.style.display = "block";
      feedbackEl.style.background = "#eff6ff";
      feedbackEl.style.color = "#1e40af";
      feedbackEl.textContent = isCpu
        ? "Launching Ollama in CPU-only mode (no GPU required)..."
        : "Launching Ollama with GPU acceleration...";
    }
    try {
      btnStartOllama.disabled = true;
      const res = await fetch("/api/llm/start_ollama", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cpu_mode: isCpu }),
      });
      const data = await res.json();
      if (feedbackEl) {
        const ok = data.success;
        feedbackEl.style.background = ok ? "#f0fdf4" : "#fef2f2";
        feedbackEl.style.color = ok ? "#166534" : "#991b1b";
        feedbackEl.textContent = data.message || data.error;
      }
      fetchLlmStatus();
    } catch (e) {
      if (feedbackEl) {
        feedbackEl.style.background = "#fef2f2";
        feedbackEl.style.color = "#991b1b";
        feedbackEl.textContent = "Error: " + e.message;
      }
    } finally {
      btnStartOllama.disabled = false;
    }
  });
} // end initLlmConfigModal



// ----------------------------------------------------------------------------
// App Initialization
// ----------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", () => {
  initNavigation();
  initCollapsibleSections();
  initLlmToggle();
  initAskAiPrompt();
  initProductivityTools();
  initWorkspaces();
  initAudit();
  initDashboard();
  initSpotlightSearch();
  initAttachments();
  initNotifications();

  // Restore sidebar state
  if (localStorage.getItem(SIDEBAR_STATE_KEY) === "true") {
    document.querySelector(".layout-container")?.classList.add("sidebar-collapsed");
  }

  // Restore active session or initial state
  renderSidebarThreads();
  const active = chatSessions.find(s => s.id === currentSessionId);
  if (active && active.messages && active.messages.length > 0) {
    loadChatSession(currentSessionId);
  }

  fetchStatus();
  setInterval(fetchStatus, 8000);
});

// ----------------------------------------------------------------------------
// Navigation & Breadcrumbs
// ----------------------------------------------------------------------------
function initNavigation() {
  const navBtns = document.querySelectorAll(".nav-item");
  const viewPanes = document.querySelectorAll(".view-pane");
  const breadcrumbRoot = document.querySelector(".breadcrumb-root");
  const breadcrumbCurrent = document.getElementById("breadcrumb-current-text");

  const tabMeta = {
    "tab-ask-ai": { root: "Overview", label: "Ask AI" },
    "tab-dashboard": { root: "Overview", label: "Dashboard" },
    "tab-inbox": { root: "Overview", label: "Inbox" },
    "tab-leads": { root: "Overview", label: "Manage Tasks" },
    "tab-calendar": { root: "Overview", label: "Multi-calendar" },
    "tab-analytics": { root: "Tools", label: "Audit & Logs" },
    "tab-documents": { root: "Tools", label: "Documents" },
    "tab-browser": { root: "Tools", label: "Web Browser" },
    "tab-workspaces": { root: "Manager", label: "Workspaces" },
    "tab-performance": { root: "Manager", label: "Performance" },
    "tab-settings": { root: "Manager", label: "Settings" },
  };

  function switchTab(tabId) {
    if (!tabId) return;
    try {
      localStorage.setItem("active_dashboard_tab", tabId);
    } catch (e) {}

    navBtns.forEach(b => b.classList.remove("active"));
    viewPanes.forEach(p => p.classList.remove("active"));

    const targetBtn = document.querySelector(`.nav-item[data-tab="${tabId}"]`);
    const targetPane = document.getElementById(tabId);

    if (targetBtn) targetBtn.classList.add("active");
    if (targetPane) targetPane.classList.add("active");

    if (tabMeta[tabId]) {
      if (breadcrumbRoot) breadcrumbRoot.textContent = tabMeta[tabId].root;
      if (breadcrumbCurrent) breadcrumbCurrent.textContent = tabMeta[tabId].label;
    }

    if (tabId === "tab-workspaces") fetchWorkspaces();
    if (tabId === "tab-analytics") fetchAuditLogs();
    if (tabId === "tab-leads") fetchTasksList();
    if (tabId === "tab-calendar") fetchCalendarEvents();
    if (tabId === "tab-inbox") {
      document.getElementById("header-chat-tools")?.classList.add("hidden");
      document.getElementById("header-inbox-search-wrap")?.classList.remove("hidden");
      fetchEmailInbox();
    } else {
      document.getElementById("header-chat-tools")?.classList.remove("hidden");
      document.getElementById("header-inbox-search-wrap")?.classList.add("hidden");
    }

    if (tabId === "tab-ask-ai") {
      requestAnimationFrame(() => {
        const vp = document.getElementById("chat-viewport");
        if (vp) vp.scrollTop = vp.scrollHeight;
      });
    }
  }

  navBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const tabId = btn.getAttribute("data-tab");
      switchTab(tabId);
    });
  });

  // Restore persisted tab on reload
  try {
    const hash = window.location.hash ? "tab-" + window.location.hash.replace("#", "") : null;
    const saved = hash || localStorage.getItem("active_dashboard_tab");
    if (saved && document.getElementById(saved)) {
      switchTab(saved);
    }
  } catch (e) {}

  // Breadcrumb Click Navigation
  breadcrumbRoot?.addEventListener("click", () => {
    switchTab("tab-dashboard");
  });

  // Sidebar toggle & close buttons
  const toggleSidebar = () => {
    const layout = document.querySelector(".layout-container");
    layout?.classList.toggle("sidebar-collapsed");
    const isCollapsed = layout?.classList.contains("sidebar-collapsed");
    localStorage.setItem(SIDEBAR_STATE_KEY, isCollapsed ? "true" : "false");
  };
  document.getElementById("btn-toggle-sidebar")?.addEventListener("click", toggleSidebar);
  document.getElementById("btn-sidebar-close")?.addEventListener("click", toggleSidebar);

  // Top header search thread button (Spotlight)
  document.getElementById("btn-search-thread")?.addEventListener("click", () => {
    openSpotlightModal();
  });

  // Top header quick back button
  document.getElementById("btn-nav-back")?.addEventListener("click", () => {
    switchTab("tab-ask-ai");
  });

  // Sidebar quick chat button
  document.getElementById("btn-sidebar-quick-chat")?.addEventListener("click", () => {
    switchTab("tab-ask-ai");
    document.getElementById("ai-main-input")?.focus();
  });

  // Workspaces button in Ask AI view
  document.getElementById("btn-create-folder")?.addEventListener("click", () => {
    switchTab("tab-workspaces");
  });

  // Global keyboard shortcuts (Ctrl+B, Ctrl+S, Esc)
  window.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
      e.preventDefault();
      toggleSidebar();
    } else if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
      e.preventDefault();
      document.getElementById("global-search-input")?.focus();
    } else if (e.key === "Escape") {
      closeSpotlightModal();
      closeApprovalModal();
      closeDeleteModal();
      closeThreadContextMenu();
      closeNotificationPopover();
      document.getElementById("link-email-modal")?.classList.add("hidden");
    }
  });

  // Thread Context Menu Action Handlers
  document.addEventListener("click", (e) => {
    if (!e.target.closest("#thread-context-menu") && !e.target.closest(".thread-item-more")) {
      closeThreadContextMenu();
    }
  });

  document.getElementById("menu-pin-thread")?.addEventListener("click", () => {
    if (targetThreadMenuSessionId) togglePinThread(targetThreadMenuSessionId);
  });

  document.getElementById("menu-rename-thread")?.addEventListener("click", () => {
    if (targetThreadMenuSessionId) startRenameThread(targetThreadMenuSessionId);
  });

  document.getElementById("menu-export-thread")?.addEventListener("click", () => {
    if (targetThreadMenuSessionId) exportThread(targetThreadMenuSessionId);
  });

  document.getElementById("menu-delete-thread")?.addEventListener("click", () => {
    if (targetThreadMenuSessionId) promptDeleteThread(targetThreadMenuSessionId);
  });

  // Delete Confirmation Modal Actions
  document.getElementById("btn-cancel-delete-thread")?.addEventListener("click", closeDeleteModal);
  document.getElementById("btn-confirm-delete-thread")?.addEventListener("click", () => {
    if (pendingDeleteSessionId) {
      deleteSession(pendingDeleteSessionId);
      closeDeleteModal();
    }
  });

  // Undo Delete Toast Action
  document.getElementById("btn-undo-delete")?.addEventListener("click", handleUndoDelete);
}

// ----------------------------------------------------------------------------
// Collapsible Sidebar Sections
// ----------------------------------------------------------------------------
function initCollapsibleSections() {
  const sectionHeaders = document.querySelectorAll(".nav-section-header");
  sectionHeaders.forEach(header => {
    header.addEventListener("click", () => {
      const parentSection = header.closest(".nav-section");
      if (parentSection) {
        parentSection.classList.toggle("collapsed");
      }
    });
  });
}

// ----------------------------------------------------------------------------
// Notifications Hub (Unread Mail & Calendar Reminders)
// ----------------------------------------------------------------------------
let notificationsData = { emails: [], events: [] };
let activeNotifFilter = "all";

function closeNotificationPopover() {
  const popover = document.getElementById("notifications-popover");
  const notifBtn = document.getElementById("btn-notifications");
  popover?.classList.add("hidden");
  notifBtn?.setAttribute("aria-expanded", "false");
}

function initNotifications() {
  const notifBtn = document.getElementById("btn-notifications");
  const popover = document.getElementById("notifications-popover");

  notifBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    if (!popover) return;
    const isHidden = popover.classList.toggle("hidden");
    notifBtn.setAttribute("aria-expanded", !isHidden);
    if (!isHidden) {
      fetchNotifications();
    }
  });

  // Close when clicking outside
  document.addEventListener("click", (e) => {
    if (!popover?.contains(e.target) && !notifBtn?.contains(e.target)) {
      closeNotificationPopover();
    }
  });

  // Filter tabs
  const tabBtns = document.querySelectorAll(".notif-tab");
  tabBtns.forEach(btn => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      tabBtns.forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      activeNotifFilter = btn.getAttribute("data-filter") || "all";
      renderNotificationsList();
    });
  });

  // Mark all as read
  document.getElementById("notif-mark-all-read")?.addEventListener("click", async (e) => {
    e.stopPropagation();
    try {
      await fetch("/api/email/mark_all_read", { method: "POST" });
      await fetchNotifications();
      if (document.getElementById("tab-inbox")?.classList.contains("active")) {
        fetchEmailInbox();
      }
    } catch (err) {
      console.error("Failed to mark emails as read:", err);
    }
  });

  // Go to Inbox
  document.getElementById("notif-open-inbox")?.addEventListener("click", (e) => {
    e.stopPropagation();
    closeNotificationPopover();
    document.querySelector('.nav-item[data-tab="tab-inbox"]')?.click();
  });

  // Initial fetch and periodic polling
  fetchNotifications();
  setInterval(fetchNotifications, 20000);
}

async function fetchNotifications() {
  try {
    const [emailRes, calRes] = await Promise.all([
      fetch("/api/email/inbox?category=unread").then(r => r.json()).catch(() => ({ messages: [] })),
      fetch("/api/calendar/events").then(r => r.json()).catch(() => ({ events: [] }))
    ]);

    const emails = emailRes.messages || [];
    const events = calRes.events || [];
    notificationsData = { emails, events };

    const total = emails.length + events.length;
    const badge = document.getElementById("header-notif-badge");
    const countAllSpan = document.getElementById("notif-count-all");
    const countMailSpan = document.getElementById("notif-count-mail");
    const countCalSpan = document.getElementById("notif-count-cal");
    const pillCount = document.getElementById("notif-pill-count");

    if (badge) {
      if (total > 0) {
        badge.textContent = total > 9 ? "9+" : total;
        badge.classList.remove("hidden");
      } else {
        badge.classList.add("hidden");
      }
    }

    if (countAllSpan) countAllSpan.textContent = total;
    if (countMailSpan) countMailSpan.textContent = emails.length;
    if (countCalSpan) countCalSpan.textContent = events.length;
    if (pillCount) pillCount.textContent = `${total} new`;

    renderNotificationsList();
  } catch (err) {
    console.error("Failed to fetch notifications:", err);
  }
}

function renderNotificationsList() {
  const container = document.getElementById("notif-list-container");
  if (!container) return;

  const { emails, events } = notificationsData;
  let items = [];

  if (activeNotifFilter === "all" || activeNotifFilter === "mail") {
    emails.forEach(m => {
      items.push({
        type: "mail",
        id: m.id,
        sender: m.sender || "Unknown",
        title: m.subject || "(No Subject)",
        snippet: m.body_preview || (m.body ? m.body.slice(0, 100) : "No preview available"),
        time: m.received_at ? formatNotifTime(m.received_at) : "Recently",
        priority: m.priority || "normal",
        category: m.category || "unread"
      });
    });
  }

  if (activeNotifFilter === "all" || activeNotifFilter === "calendar") {
    events.forEach(ev => {
      items.push({
        type: "calendar",
        id: ev.id,
        sender: "Calendar Reminder",
        title: ev.title || "Upcoming Event",
        snippet: ev.description || `${ev.start_time || ""} - ${ev.end_time || ""}`,
        time: ev.start_time || "Scheduled",
        priority: "calendar",
        category: "event"
      });
    });
  }

  if (items.length === 0) {
    container.innerHTML = `
      <div class="notif-empty-state">
        <svg class="notif-empty-icon" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
          <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"></path>
          <path d="M13.73 21a2 2 0 0 1-3.46 0"></path>
        </svg>
        <div>All caught up! No notifications.</div>
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  items.forEach(item => {
    const el = document.createElement("div");
    el.className = "notif-item";

    const isUrgent = item.priority === "high" || item.category === "urgent";
    const iconHtml = item.type === "mail"
      ? `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
           <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path>
           <polyline points="22,6 12,13 2,6"></polyline>
         </svg>`
      : `<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
           <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
           <line x1="16" y1="2" x2="16" y2="6"></line>
           <line x1="8" y1="2" x2="8" y2="6"></line>
           <line x1="3" y1="10" x2="21" y2="10"></line>
         </svg>`;

    const tagClass = item.type === "calendar" ? "calendar" : (isUrgent ? "urgent" : "unread");
    const tagText = item.type === "calendar" ? "Reminder" : (isUrgent ? "Urgent" : "Unread");

    el.innerHTML = `
      <div class="notif-item-icon ${item.type} ${isUrgent ? 'urgent' : ''}">
        ${iconHtml}
      </div>
      <div class="notif-item-content">
        <div class="notif-item-header">
          <span class="notif-item-sender">${escapeHtml(item.sender)}</span>
          <span class="notif-item-time">${escapeHtml(item.time)}</span>
        </div>
        <div class="notif-item-subject">${escapeHtml(item.title)}</div>
        <div class="notif-item-snippet">${escapeHtml(item.snippet)}</div>
        <span class="notif-tag ${tagClass}">${tagText}</span>
      </div>
    `;

    el.addEventListener("click", () => {
      closeNotificationPopover();
      if (item.type === "mail") {
        document.querySelector('.nav-item[data-tab="tab-inbox"]')?.click();
        setTimeout(() => {
          selectEmailMessage(item.id);
          fetchNotifications();
        }, 120);
      } else {
        document.querySelector('.nav-item[data-tab="tab-calendar"]')?.click();
      }
    });

    container.appendChild(el);
  });
}

function formatNotifTime(dateStr) {
  try {
    const d = new Date(dateStr);
    if (isNaN(d.getTime())) return dateStr;
    const now = new Date();
    const diffMs = now - d;
    const diffMins = Math.floor(diffMs / 60000);
    if (diffMins < 1) return "Just now";
    if (diffMins < 60) return `${diffMins}m ago`;
    const diffHours = Math.floor(diffMins / 60);
    if (diffHours < 24) return `${diffHours}h ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch (e) {
    return dateStr;
  }
}


// ----------------------------------------------------------------------------
// Ask AI & In-Chat Conversation Stream
// ----------------------------------------------------------------------------
let pendingApprovalCallback = null;

function initAskAiPrompt() {
  const promptInput = document.getElementById("ai-main-input");
  const sendBtn = document.getElementById("btn-submit-prompt");
  const heroStage = document.getElementById("hero-stage");
  const chatStream = document.getElementById("chat-stream-container");
  const newChatBtn = document.getElementById("btn-new-chat");

  // Mode dropdown
  const dropdownTrigger = document.getElementById("dropdown-style-trigger");
  const styleMenu = document.getElementById("style-menu");
  const modeItems = document.querySelectorAll("#style-menu .dropdown-item");

  dropdownTrigger?.addEventListener("click", (e) => {
    e.stopPropagation();
    styleMenu?.classList.toggle("hidden");
  });

  document.addEventListener("click", () => {
    styleMenu?.classList.add("hidden");
  });

  modeItems.forEach(item => {
    item.addEventListener("click", () => {
      modeItems.forEach(i => i.classList.remove("active"));
      item.classList.add("active");
      currentExecutionMode = item.getAttribute("data-mode");
      const label = item.textContent.trim().split(" ")[0] || "Mode";
      const span = dropdownTrigger?.querySelector("span");
      if (span) span.textContent = label;
      styleMenu?.classList.add("hidden");
    });
  });

  // Reset / New Task (Preserves current chat and starts new thread)
  newChatBtn?.addEventListener("click", () => {
    startNewTaskSession();
  });

  // Auto-expanding textarea
  promptInput?.addEventListener("input", () => {
    promptInput.style.height = "auto";
    const newH = Math.min(promptInput.scrollHeight, 110);
    promptInput.style.height = newH + "px";

    // If user edited text while browsing history, break out of history recall
    if (historyIndex !== -1 && promptInput.value !== commandHistory[historyIndex]) {
      historyIndex = -1;
      draftInputText = promptInput.value;
    }
  });

  // Submit Prompt
  async function submitPrompt() {
    let text = promptInput?.value.trim();
    if (!text && pendingAttachments.length === 0) return;

    if (!text && pendingAttachments.length > 0) {
      text = "What is this file? Please analyze and explain its contents.";
    }

    // Save to command history
    if (text) {
      if (commandHistory.length === 0 || commandHistory[commandHistory.length - 1] !== text) {
        commandHistory.push(text);
        saveCommandHistory(commandHistory);
      }
    }
    historyIndex = -1;
    draftInputText = "";

    // Capture attachments snapshot
    const currentAtts = [...pendingAttachments];
    pendingAttachments = [];
    renderAttachmentTray();

    // Transition out of hero view into chat stream
    heroStage?.classList.add("hidden");
    chatStream?.classList.remove("hidden");

    // Read attached files as base64
    let encodedAttachments = [];
    if (currentAtts.length > 0) {
      const readPromises = currentAtts.map(f => new Promise((resolve) => {
        const reader = new FileReader();
        reader.onload = () => {
          resolve({
            name: f.name,
            size: f.size,
            type: f.type,
            data: reader.result
          });
        };
        reader.onerror = () => resolve({ name: f.name, size: f.size, type: f.type, data: null });
        reader.readAsDataURL(f);
      }));
      encodedAttachments = await Promise.all(readPromises);
    }

    // 1. Append User Message to Chat Stream and persist
    appendUserMessage(text, currentAtts.map(f => ({ name: f.name, size: f.size })), true);
    promptInput.value = "";
    promptInput.style.height = "auto";
    scrollToBottom();

    if (sendBtn) sendBtn.disabled = true;

    // 2. Append Typing Indicator
    const typingRowId = appendTypingIndicator();
    scrollToBottom();

    try {
      const currentSession = getCurrentSession();
      const recentHistory = (currentSession.messages || [])
        .slice(-8)
        .map(m => ({
          role: m.sender === "user" ? "user" : "assistant",
          content: m.text || (typeof m.data?.message === "string" ? m.data.message : "")
        }))
        .filter(h => h.content);

      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          mode: currentExecutionMode,
          attachments: encodedAttachments,
          history: recentHistory,
          llm_enabled: isLlmEngineEnabled()
        })
      });
      const data = await res.json();

      removeTypingIndicator(typingRowId);

      if (!data.success) {
        appendAssistantMessage({
          type: "conversation",
          message: "Error processing request: " + (data.error || "Unknown error")
        }, true);
        return;
      }

      // 3. Append Assistant Response directly within Chat Stream and persist!
      appendAssistantMessage(data, true);
      scrollToBottom();

      // If autonomous mode and low risk, auto-trigger execution
      if (currentExecutionMode === "autonomous" && data.type === "plan" && !data.requires_approval) {
        const lastCard = chatStream?.querySelector(".inline-plan-card:last-of-type");
        if (lastCard) {
          executeInlinePlan(data, lastCard, true);
        }
      }
    } catch (err) {
      removeTypingIndicator(typingRowId);
      appendAssistantMessage({
        type: "conversation",
        message: "Network error contacting local agent: " + err.message
      }, true);
      scrollToBottom();
    } finally {
      if (sendBtn) sendBtn.disabled = false;
    }
  }

  sendBtn?.addEventListener("click", submitPrompt);

  promptInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitPrompt();
      return;
    }

    if (e.key === "ArrowUp") {
      const text = promptInput.value;
      const selStart = promptInput.selectionStart ?? 0;
      const isSingleLine = !text.includes("\n");
      const isAtFirstLine = selStart === 0 || text.lastIndexOf("\n", selStart - 1) === -1;

      if ((isSingleLine || isAtFirstLine) && commandHistory.length > 0) {
        if (historyIndex === -1) {
          draftInputText = text;
          historyIndex = commandHistory.length - 1;
        } else if (historyIndex > 0) {
          historyIndex--;
        } else {
          return;
        }

        e.preventDefault();
        promptInput.value = commandHistory[historyIndex];
        promptInput.style.height = "auto";
        const newH = Math.min(promptInput.scrollHeight, 110);
        promptInput.style.height = newH + "px";
        const len = promptInput.value.length;
        promptInput.setSelectionRange(len, len);
      }
      return;
    }

    if (e.key === "ArrowDown") {
      if (historyIndex === -1) return;

      const text = promptInput.value;
      const selEnd = promptInput.selectionEnd ?? text.length;
      const isSingleLine = !text.includes("\n");
      const isAtLastLine = selEnd === text.length || text.indexOf("\n", selEnd) === -1;

      if (isSingleLine || isAtLastLine) {
        e.preventDefault();
        if (historyIndex < commandHistory.length - 1) {
          historyIndex++;
          promptInput.value = commandHistory[historyIndex];
        } else {
          historyIndex = -1;
          promptInput.value = draftInputText;
        }

        promptInput.style.height = "auto";
        const newH = Math.min(promptInput.scrollHeight, 110);
        promptInput.style.height = newH + "px";
        const len = promptInput.value.length;
        promptInput.setSelectionRange(len, len);
      }
      return;
    }
  });

  // Modal actions
  document.getElementById("btn-modal-confirm")?.addEventListener("click", () => {
    closeApprovalModal();
    if (pendingApprovalCallback) pendingApprovalCallback(true);
  });

  document.getElementById("btn-modal-deny")?.addEventListener("click", () => {
    closeApprovalModal();
    if (pendingApprovalCallback) pendingApprovalCallback(false);
  });
}

function appendUserMessage(text, attachments = [], persist = true) {
  const chatStream = document.getElementById("chat-stream-container");
  if (!chatStream) return;

  const row = document.createElement("div");
  row.className = "chat-row user-row";

  const bubble = document.createElement("div");
  bubble.className = "user-bubble";

  if (attachments && attachments.length > 0) {
    const attsContainer = document.createElement("div");
    attsContainer.className = "user-bubble-attachments";
    attachments.forEach(att => {
      const pill = document.createElement("span");
      pill.className = "user-bubble-attachment-pill";
      pill.innerHTML = `
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
          <polyline points="14 2 14 8 20 8"></polyline>
        </svg>
        <span>${escapeHtml(att.name || "File")}</span>
      `;
      attsContainer.appendChild(pill);
    });
    bubble.appendChild(attsContainer);
  }

  const textNode = document.createElement("div");
  textNode.className = "user-bubble-text";
  textNode.textContent = text;
  bubble.appendChild(textNode);

  row.appendChild(bubble);
  chatStream.appendChild(row);

  if (persist) {
    addMessageToCurrentSession({
      sender: "user",
      text: text,
      attachments: attachments,
      timestamp: Date.now()
    });
  }
}

function appendTypingIndicator() {
  const chatStream = document.getElementById("chat-stream-container");
  if (!chatStream) return null;

  const id = "typing-" + Date.now();
  const row = document.createElement("div");
  row.className = "chat-row assistant-row";
  row.id = id;

  row.innerHTML = `
    <div class="assistant-avatar-badge">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
        <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="#2563eb"/>
      </svg>
    </div>
    <div class="assistant-content-box">
      <div class="typing-dots">
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
        <span class="typing-dot"></span>
      </div>
    </div>
  `;
  chatStream.appendChild(row);
  return id;
}

function removeTypingIndicator(id) {
  if (id) {
    document.getElementById(id)?.remove();
  }
}

function appendAssistantMessage(data, persist = true) {
  const chatStream = document.getElementById("chat-stream-container");
  if (!chatStream) return;

  const row = document.createElement("div");
  row.className = "chat-row assistant-row";

  const avatar = `
    <div class="assistant-avatar-badge">
      <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
        <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z" fill="#2563eb"/>
      </svg>
    </div>
  `;

  const contentBox = document.createElement("div");
  contentBox.className = "assistant-content-box";

  // Message Text with Markdown formatting and Copy button
  const textEl = document.createElement("div");
  textEl.className = "assistant-message-text";
  textEl.innerHTML = formatMarkdown(data.message || "");
  contentBox.appendChild(textEl);

  // Wire 1-click code block copy buttons
  contentBox.querySelectorAll(".btn-copy-code").forEach(btn => {
    btn.addEventListener("click", () => {
      const code = btn.closest(".code-block-container")?.querySelector("code")?.innerText;
      if (code) {
        navigator.clipboard.writeText(code);
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Copy"; }, 1500);
      }
    });
  });

  // Wire email summary deck interactive filters
  contentBox.querySelectorAll(".deck-filter-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const deck = btn.closest(".email-summary-deck");
      if (!deck) return;
      deck.querySelectorAll(".deck-filter-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const filter = btn.dataset.filter;
      deck.querySelectorAll(".email-summary-card").forEach(card => {
        if (filter === "all") {
          card.classList.remove("hidden");
        } else if (filter === "action") {
          if (card.dataset.action === "true") card.classList.remove("hidden");
          else card.classList.add("hidden");
        } else if (filter === "urgent") {
          const p = card.dataset.priority || "";
          if (p.includes("urgent") || p.includes("high") || p.includes("sec")) card.classList.remove("hidden");
          else card.classList.add("hidden");
        }
      });
    });
  });

  // Wire View in Inbox button to smoothly switch tabs and search email
  contentBox.querySelectorAll(".esc-view-inbox-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      const query = btn.dataset.search || "";
      switchTab("tab-inbox");
      const searchInput = document.getElementById("email-search-input");
      if (searchInput && query) {
        searchInput.value = query.slice(0, 30);
        searchInput.dispatchEvent(new Event("input"));
      }
    });
  });

  // If this is a synthesized automation plan, render the plan card inline inside this message!
  if (data.type === "plan" && data.steps && data.steps.length > 0) {
    const planCard = document.createElement("div");
    planCard.className = "inline-plan-card";

    const risk = (data.cumulative_risk || "LOW").toUpperCase();
    const riskClass = risk === "HIGH" ? "risk-high" : risk === "MEDIUM" ? "risk-med" : "risk-low";

    planCard.innerHTML = `
      <div class="inline-plan-header">
        <span class="inline-plan-title">Workflow Plan (${data.steps.length} steps)</span>
        <span class="risk-badge ${riskClass}">${risk} RISK</span>
      </div>
      <p class="inline-plan-desc">Target Workspace: <strong>${escapeHtml(data.workspace || "Default")}</strong></p>
      <div class="inline-steps-list">
        ${data.steps.map((s, idx) => {
          const stepRisk = (s.risk || "LOW").toUpperCase();
          const sRiskClass = stepRisk === "HIGH" ? "risk-high" : stepRisk === "MEDIUM" ? "risk-med" : "risk-low";
          return `
            <div class="inline-step-item">
              <div class="inline-step-left">
                <span class="inline-step-num">${idx + 1}</span>
                <span class="inline-step-action">${escapeHtml(s.action)}</span>
                <span class="inline-step-args">${escapeHtml(JSON.stringify(s.arguments))}</span>
              </div>
              <span class="risk-badge ${sRiskClass}">${stepRisk}</span>
            </div>
          `;
        }).join("")}
      </div>
      <div class="inline-plan-actions">
        <button class="pill-btn pill-btn-dark btn-inline-execute">Execute Plan</button>
        <button class="pill-btn pill-btn-outline btn-inline-discard">Discard</button>
      </div>
      <div class="inline-execution-stream hidden"></div>
    `;

    // Hook buttons
    const execBtn = planCard.querySelector(".btn-inline-execute");
    const discardBtn = planCard.querySelector(".btn-inline-discard");

    discardBtn?.addEventListener("click", () => {
      planCard.remove();
    });

    execBtn?.addEventListener("click", () => {
      if (data.requires_approval) {
        pendingApprovalCallback = (approved) => {
          executeInlinePlan(data, planCard, approved);
        };
        showApprovalModal(data);
      } else {
        executeInlinePlan(data, planCard, true);
      }
    });

    contentBox.appendChild(planCard);
  }

  // If email messages are returned, render them as single horizontal full-width rows matching Inbox!
  if (data.emails && data.emails.length > 0) {
    const listEl = document.createElement("div");
    listEl.className = "chat-email-list";
    data.emails.forEach((em, idx) => {
      const emailRow = document.createElement("div");
      emailRow.className = `chat-email-row ${em.is_read ? 'read' : 'unread'}`;
      emailRow.setAttribute("data-id", em.id || `msg-${idx}`);

      const prioClass = `chat-prio-${(em.priority || 'normal').toLowerCase()}`;
      emailRow.innerHTML = `
        <span class="chat-email-num">#${idx + 1}</span>
        <span class="chat-email-prio ${prioClass}">${escapeHtml((em.priority || 'normal').toUpperCase())}</span>
        <span class="chat-email-sender" title="${escapeHtml(em.sender_email || em.sender)}">${escapeHtml(em.sender)}</span>
        <div class="chat-email-content">
          <span class="chat-email-subject">${escapeHtml(em.subject || '(No Subject)')}</span>
          <span class="chat-email-sep">—</span>
          <span class="chat-email-snippet">${escapeHtml(em.snippet || '')}</span>
        </div>
        <span class="chat-email-date">${escapeHtml(em.date || '')}</span>
      `;

      emailRow.addEventListener("click", () => {
        const inboxNavBtn = document.getElementById("nav-btn-inbox");
        if (inboxNavBtn) {
          inboxNavBtn.click();
          setTimeout(() => {
            if (em.id && typeof openEmailDetailView === "function") {
              openEmailDetailView(em.id);
            }
          }, 150);
        }
      });
      listEl.appendChild(emailRow);
    });
    contentBox.appendChild(listEl);
  }

  // Render Quick Reply / Action buttons below the mail list or response!
  if (data.quick_actions && data.quick_actions.length > 0) {
    const qaContainer = document.createElement("div");
    qaContainer.className = "chat-quick-actions";
    data.quick_actions.forEach(qa => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = qa.id === "summarize_priority" ? "chat-quick-btn chat-quick-primary" : "chat-quick-btn chat-quick-outline";
      btn.innerHTML = `
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          ${qa.id === 'open_inbox' 
            ? '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"></polyline><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>'
            : '<line x1="8" y1="6" x2="21" y2="6"></line><line x1="8" y1="12" x2="21" y2="12"></line><line x1="8" y1="18" x2="21" y2="18"></line><line x1="3" y1="6" x2="3.01" y2="6"></line><line x1="3" y1="12" x2="3.01" y2="12"></line><line x1="3" y1="18" x2="3.01" y2="18"></line>'
          }
        </svg>
        <span>${escapeHtml(qa.label)}</span>
      `;
      btn.addEventListener("click", () => {
        if (qa.action === "switch_to_inbox") {
          document.getElementById("nav-btn-inbox")?.click();
        } else if (qa.action === "switch_to_calendar") {
          document.getElementById("nav-btn-calendar")?.click();
        } else if (qa.action === "sync_emails") {
          document.getElementById("btn-sync-emails")?.click();
        } else if (qa.prompt) {
          const input = document.getElementById("ai-main-input");
          if (input) {
            input.value = qa.prompt;
            document.getElementById("btn-submit-prompt")?.click();
          }
        }
      });
      qaContainer.appendChild(btn);
    });
    contentBox.appendChild(qaContainer);
  }

  row.innerHTML = avatar;
  row.appendChild(contentBox);
  chatStream.appendChild(row);

  if (persist) {
    addMessageToCurrentSession({
      sender: "assistant",
      type: data.type || "conversation",
      data: data,
      text: data.message || "",
      timestamp: Date.now()
    });
  }
}

async function executeInlinePlan(plan, cardEl, approved = true) {
  const streamEl = cardEl.querySelector(".inline-execution-stream");
  const actionsEl = cardEl.querySelector(".inline-plan-actions");

  if (actionsEl) actionsEl.classList.add("hidden");
  if (streamEl) {
    streamEl.classList.remove("hidden");
    streamEl.innerHTML = `<div class="inline-stream-line">Initiating deterministic execution...</div>`;
  }

  try {
    const res = await fetch("/api/tasks/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task_id: plan.task_id,
        steps: plan.steps,
        goal: plan.goal,
        approved: approved
      })
    });
    const result = await res.json();

    if (streamEl) {
      streamEl.innerHTML = "";
      (result.steps || []).forEach((s, idx) => {
        const line = document.createElement("div");
        line.className = "inline-stream-line";
        const isOk = s.status === "COMPLETED" || s.status === "SUCCESS";
        const isFail = s.status === "FAILED";
        const icon = isOk ? "[OK]" : isFail ? "[FAIL]" : "[RUNNING]";
        let statusDetail = "Success";
        if (!isOk) {
          statusDetail = s.error_info || s.error_message || "Action stopped or unapproved";
        } else if (s.output && typeof s.output.count === "number") {
          statusDetail = `Found ${s.output.count} matching item(s)`;
        } else if (s.summary) {
          statusDetail = s.summary;
        }
        line.innerHTML = `${icon} Step ${idx + 1} (${escapeHtml(s.action)}): <strong>${escapeHtml(s.status)}</strong> - ${escapeHtml(statusDetail)}`;
        streamEl.appendChild(line);

        // Render file or item results if present
        if (s.output && Array.isArray(s.output.files)) {
          const fileBox = document.createElement("div");
          fileBox.className = "inline-stream-results";
          fileBox.style.cssText = "margin: 6px 0 10px 16px; padding: 8px 12px; background: rgba(15, 23, 42, 0.04); border: 1px solid rgba(0,0,0,0.06); border-radius: 6px; font-size: 12px; max-height: 220px; overflow-y: auto;";
          if (s.output.files.length === 0) {
            fileBox.innerHTML = `<span style="color: #64748b; font-style: italic;">No matching files found.</span>`;
          } else {
            const limit = 25;
            const slice = s.output.files.slice(0, limit);
            let fileHtml = slice.map((f, fIdx) => {
              const fname = f.split(/[\/\\]/).pop();
              return `<div style="padding: 2px 0; display: flex; justify-content: space-between; gap: 8px;"><span style="font-weight: 500;">${fIdx + 1}. ${escapeHtml(fname)}</span><span style="color: #64748b; font-family: monospace; font-size: 11px;">${escapeHtml(f)}</span></div>`;
            }).join("");
            if (s.output.files.length > limit) {
              fileHtml += `<div style="color: #64748b; margin-top: 4px; font-style: italic;">... and ${s.output.files.length - limit} more files</div>`;
            }
            fileBox.innerHTML = fileHtml;
          }
          streamEl.appendChild(fileBox);
        } else if (s.output && Array.isArray(s.output.processes)) {
          const procBox = document.createElement("div");
          procBox.className = "inline-stream-results";
          procBox.style.cssText = "margin: 6px 0 10px 16px; padding: 8px 12px; background: rgba(15, 23, 42, 0.04); border: 1px solid rgba(0,0,0,0.06); border-radius: 6px; font-size: 12px; max-height: 200px; overflow-y: auto;";
          const slice = s.output.processes.slice(0, 15);
          procBox.innerHTML = slice.map((p, pIdx) => `<div style="padding: 2px 0;">${pIdx + 1}. <strong>${escapeHtml(p.name || p.pid || "process")}</strong> (PID: ${escapeHtml(String(p.pid || ''))})</div>`).join("");
          streamEl.appendChild(procBox);
        }
      });
      const finalSummary = document.createElement("div");
      finalSummary.className = "inline-stream-line";
      finalSummary.style.fontWeight = "600";
      finalSummary.style.color = result.success ? "#059669" : "#dc2626";
      finalSummary.textContent = result.success ? "Execution successfully completed." : "Execution finished with warnings or failure.";
      streamEl.appendChild(finalSummary);
    }

    scrollToBottom();
    fetchStatus();
    fetchAuditLogs();
  } catch (err) {
    if (streamEl) {
      streamEl.innerHTML = `<div class="inline-stream-line" style="color:#ef4444;">Execution error: ${escapeHtml(err.message)}</div>`;
    }
  }
}

// ----------------------------------------------------------------------------
// Spotlight Search Modal
// ----------------------------------------------------------------------------
function initSpotlightSearch() {
  const modal = document.getElementById("search-threads-modal");
  const input = document.getElementById("spotlight-thread-input");

  modal?.addEventListener("click", (e) => {
    if (e.target === modal) closeSpotlightModal();
  });

  input?.addEventListener("input", () => {
    renderSpotlightResults(input.value.trim().toLowerCase());
  });
}

function openSpotlightModal() {
  const modal = document.getElementById("search-threads-modal");
  const input = document.getElementById("spotlight-thread-input");
  if (!modal) return;

  modal.classList.remove("hidden");
  if (input) {
    input.value = "";
    input.focus();
  }
  renderSpotlightResults("");
}

function closeSpotlightModal() {
  document.getElementById("search-threads-modal")?.classList.add("hidden");
}

function renderSpotlightResults(query) {
  const list = document.getElementById("spotlight-threads-results");
  if (!list) return;

  const validSessions = chatSessions.filter(s => s.messages && s.messages.length > 0);
  const filtered = validSessions.filter(s => {
    if (!query) return true;
    const titleMatch = (s.title || "").toLowerCase().includes(query);
    const msgMatch = (s.messages || []).some(m => (m.text || "").toLowerCase().includes(query));
    return titleMatch || msgMatch;
  });

  if (filtered.length === 0) {
    list.innerHTML = `<div style="padding: 16px; text-align: center; color: #94a3b8; font-size: 13px;">No matching conversations found.</div>`;
    return;
  }

  list.innerHTML = "";
  filtered.forEach(s => {
    const item = document.createElement("div");
    item.className = "spotlight-item";
    const dateStr = new Date(s.updated_at || s.created_at).toLocaleDateString();
    item.innerHTML = `
      <div class="spotlight-item-left">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"></path>
        </svg>
        <span class="spotlight-item-title">${escapeHtml(s.title || "Conversation")}</span>
      </div>
      <span class="spotlight-item-time">${dateStr}</span>
    `;
    item.addEventListener("click", () => {
      closeSpotlightModal();
      loadChatSession(s.id);
    });
    list.appendChild(item);
  });
}

// ----------------------------------------------------------------------------
// File Attachments Tray
// ----------------------------------------------------------------------------
let pendingAttachments = [];

function renderAttachmentTray() {
  const tray = document.getElementById("attachment-tray");
  if (!tray) return;

  if (pendingAttachments.length === 0) {
    tray.classList.add("hidden");
    tray.innerHTML = "";
    return;
  }

  tray.classList.remove("hidden");
  tray.innerHTML = "";

  pendingAttachments.forEach((f, idx) => {
    const pill = document.createElement("span");
    pill.className = "attachment-pill";
    pill.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
        <polyline points="14 2 14 8 20 8"></polyline>
      </svg>
      <span>${escapeHtml(f.name)}</span>
      <button type="button" class="attachment-pill-remove" title="Remove attachment">&times;</button>
    `;
    pill.querySelector(".attachment-pill-remove")?.addEventListener("click", (e) => {
      e.stopPropagation();
      pendingAttachments.splice(idx, 1);
      renderAttachmentTray();
    });
    tray.appendChild(pill);
  });
}

function initAttachments() {
  const attachBtn = document.getElementById("btn-tool-attach");
  const fileInput = document.getElementById("file-picker-input");

  attachBtn?.addEventListener("click", () => {
    fileInput?.click();
  });

  fileInput?.addEventListener("change", (e) => {
    const files = Array.from(e.target.files || []);
    if (!files.length) return;

    files.forEach(f => {
      if (!pendingAttachments.some(p => p.name === f.name && p.size === f.size)) {
        pendingAttachments.push(f);
      }
    });

    renderAttachmentTray();
    fileInput.value = "";
  });
}

function scrollToBottom(instant = false) {
  const viewport = document.getElementById("chat-viewport");
  if (viewport) {
    if (instant) {
      viewport.scrollTop = viewport.scrollHeight;
    } else {
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
    }
  }
}

function showApprovalModal(plan) {
  const modal = document.getElementById("approval-modal");
  const details = document.getElementById("modal-approval-details");
  if (!modal || !details) return;

  const highSteps = (plan.steps || []).filter(s => (s.risk || "").toUpperCase() === "HIGH");

  details.innerHTML = `
    <p><strong>Goal:</strong> ${plan.goal}</p>
    <p><strong>High-Risk Action(s):</strong></p>
    <ul style="margin: 6px 0 0 18px;">
      ${highSteps.map(s => `<li><code>${s.action}</code>: ${JSON.stringify(s.arguments)}</li>`).join("")}
    </ul>
    <p style="margin-top: 8px; color: #64748b; font-size: 11.5px;">
      Action will be executed strictly within authorized workspaces and permanently recorded in the cryptographic audit trail.
    </p>
  `;
  modal.classList.remove("hidden");
}

function closeApprovalModal() {
  document.getElementById("approval-modal")?.classList.add("hidden");
}

// ----------------------------------------------------------------------------
// Telemetry & Status
// ----------------------------------------------------------------------------
async function fetchStatus() {
  try {
    const res = await fetch("/api/status");
    const data = await res.json();

    const elProvider = document.getElementById("dash-llm-provider");
    const elModel = document.getElementById("dash-llm-model");
    const elWorkspaces = document.getElementById("dash-workspaces-count");
    const elCpu = document.getElementById("dash-cpu-usage");
    const elRam = document.getElementById("dash-ram-usage");
    const elPlatform = document.getElementById("dash-platform");

    if (elProvider) elProvider.textContent = data.llm_provider.toUpperCase();
    if (elModel) elModel.textContent = `${data.llm_model} (Local-First)`;
    if (elWorkspaces) elWorkspaces.textContent = data.workspaces_count;
    if (elCpu) elCpu.textContent = `${data.cpu_usage}%`;
    if (elRam) elRam.textContent = `${data.ram_usage}%`;
    if (elPlatform) elPlatform.textContent = `${data.platform} Telemetry`;
  } catch (e) {
    console.warn("Status fetch failed:", e);
  }
}

// ============================================================================
// Live Class Attendance with Dynamic Rotating QR Code
// ============================================================================
let activeAttendanceSession = null;
let attendanceTimerInterval = null;
let attendancePollInterval = null;
let attendanceRoster = [];
let lastEndedSessionId = null;

function showAttendanceToast(msg, type = "info") {
  let toast = document.getElementById("attendance-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "attendance-toast";
    toast.style.cssText = `
      position: fixed;
      bottom: 24px;
      right: 24px;
      background: #0f172a;
      color: #ffffff;
      padding: 11px 18px;
      border-radius: 10px;
      font-size: 13px;
      font-weight: 500;
      box-shadow: 0 10px 25px rgba(0,0,0,0.25);
      z-index: 99999;
      display: flex;
      align-items: center;
      gap: 8px;
      transition: all 0.25s cubic-bezier(0.16, 1, 0.3, 1);
      opacity: 0;
      transform: translateY(14px);
      pointer-events: none;
    `;
    document.body.appendChild(toast);
  }
  const icon = type === "success" ? "✓ " : "ℹ ";
  toast.innerHTML = `<span style="color: ${type === 'success' ? '#4ade80' : '#60a5fa'}; font-weight: 700; font-size: 14px;">${icon}</span><span>${escapeHtml(msg)}</span>`;
  toast.style.opacity = "1";
  toast.style.transform = "translateY(0)";
  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(14px)";
  }, 3500);
}

function downloadAttendanceCsv(sessionId) {
  if (!sessionId) return;
  const link = document.createElement("a");
  link.href = `/api/attendance/export?session_id=${encodeURIComponent(sessionId)}`;
  link.download = `attendance_${sessionId}.csv`;
  document.body.appendChild(link);
  link.click();
  setTimeout(() => {
    try { document.body.removeChild(link); } catch (e) {}
  }, 100);
}

async function fetchActiveAttendanceSession() {
  try {
    const res = await fetch("/api/attendance/session/active");
    const data = await res.json();
    if (data.success && data.active) {
      activeAttendanceSession = data;
      renderAttendanceActiveState(data);
      startAttendancePolling();
    } else {
      activeAttendanceSession = null;
      renderAttendanceInactiveState();
      stopAttendancePolling();
    }
  } catch (err) {
    console.warn("Failed to fetch active attendance session:", err);
  }
}

function startAttendancePolling() {
  if (attendancePollInterval) return;
  // Poll every 1.5 seconds so scans appear immediately in real-time without reloading
  attendancePollInterval = setInterval(async () => {
    if (!activeAttendanceSession || !activeAttendanceSession.active) {
      stopAttendancePolling();
      return;
    }
    await checkActiveAttendanceUpdates();
  }, 1500);
}

function stopAttendancePolling() {
  if (attendancePollInterval) {
    clearInterval(attendancePollInterval);
    attendancePollInterval = null;
  }
}

async function checkActiveAttendanceUpdates() {
  try {
    const res = await fetch("/api/attendance/session/active");
    const data = await res.json();
    if (!data.success || !data.active) {
      if (activeAttendanceSession) {
        activeAttendanceSession = null;
        renderAttendanceInactiveState();
        stopAttendancePolling();
      }
      return;
    }

    // 1. Detect if token rotated
    if (data.current_token !== activeAttendanceSession.current_token) {
      activeAttendanceSession.current_token = data.current_token;
      activeAttendanceSession.expires_at = data.expires_at;
      activeAttendanceSession.qr_svg = data.qr_svg;
      activeAttendanceSession.checkin_url = data.checkin_url;

      const qrContainer = document.getElementById("att-qr-container");
      if (qrContainer && data.qr_svg) qrContainer.innerHTML = data.qr_svg;

      const projQrContainer = document.getElementById("proj-qr-container");
      if (projQrContainer && data.qr_svg) projQrContainer.innerHTML = data.qr_svg;

      const linkInput = document.getElementById("att-link-input");
      if (linkInput) linkInput.value = data.checkin_url || "";

      startAttendanceCountdown(data.expires_at, data.rotation_interval || 15);
    }

    // 2. Real-time live roster update (detect newly checked in students)
    const newRoster = data.roster || [];
    const prevIds = new Set((attendanceRoster || []).map(r => r.student_id));
    const newlyAdded = newRoster.filter(r => !prevIds.has(r.student_id));

    if (newlyAdded.length > 0 || newRoster.length !== attendanceRoster.length) {
      const newIdsSet = new Set(newlyAdded.map(r => r.student_id));
      attendanceRoster = newRoster;
      renderAttendanceRoster(attendanceRoster, newIdsSet);

      const counterEl = document.getElementById("att-present-counter");
      if (counterEl) counterEl.textContent = `${attendanceRoster.length} Present`;

      const projPresentCount = document.getElementById("proj-present-count");
      if (projPresentCount) projPresentCount.textContent = `${attendanceRoster.length} Present`;

      if (newlyAdded.length > 0) {
        const latest = newlyAdded[0];
        showAttendanceToast(`${latest.student_name} (${latest.student_id}) checked in!`, "success");
      }
    }
  } catch (err) {
    console.debug("Live attendance check error:", err);
  }
}

function renderAttendanceActiveState(data) {
  const badge = document.getElementById("att-status-badge");
  const badgeText = document.getElementById("att-status-text");
  if (badge) badge.className = "attendance-status-badge active";
  if (badgeText) badgeText.textContent = "Session Active";

  const courseNameEl = document.getElementById("att-display-course");
  const courseSubEl = document.getElementById("att-display-section");
  if (courseNameEl) courseNameEl.textContent = data.course_name || "Live Classroom";
  if (courseSubEl) courseSubEl.innerHTML = `${escapeHtml(data.section || "Section A")} &bull; ${data.rotation_interval || 15}s Dynamic Rotation`;

  const lanIpEl = document.getElementById("att-lan-ip-display");
  if (lanIpEl && data.lan_ip) {
    const port = window.location.port ? `:${window.location.port}` : (window.location.protocol === "https:" ? ":8443" : ":8000");
    lanIpEl.textContent = `${data.lan_ip}${port}`;
  }

  const btnStart = document.getElementById("btn-start-attendance");
  const btnStartLabel = document.getElementById("btn-start-attendance-label");
  const btnExport = document.getElementById("btn-export-attendance");
  const btnExportLabel = document.getElementById("btn-export-attendance-label");
  const btnSimulate = document.getElementById("btn-simulate-scan");
  const btnRotate = document.getElementById("btn-manual-rotate-qr");

  if (btnStartLabel) btnStartLabel.textContent = "End Session";
  if (btnStart) {
    btnStart.className = "pill-btn pill-btn-ghost danger";
    btnStart.style.color = "#dc2626";
  }
  if (btnExport) btnExport.disabled = false;
  if (btnExportLabel) btnExportLabel.textContent = "Export CSV";
  if (btnSimulate) btnSimulate.disabled = false;
  if (btnRotate) btnRotate.disabled = false;

  const btnProjector = document.getElementById("btn-projector-mode");
  if (btnProjector) btnProjector.disabled = false;

  const qrContainer = document.getElementById("att-qr-container");
  if (qrContainer && data.qr_svg) {
    qrContainer.innerHTML = data.qr_svg;
  }

  const projQrContainer = document.getElementById("proj-qr-container");
  if (projQrContainer && data.qr_svg) {
    projQrContainer.innerHTML = data.qr_svg;
  }

  const projCourseTitle = document.getElementById("proj-course-title");
  if (projCourseTitle) projCourseTitle.textContent = data.course_name || "Live Classroom";
  const projCourseSub = document.getElementById("proj-course-sub");
  if (projCourseSub) projCourseSub.innerHTML = `${escapeHtml(data.section || "Section A")} &bull; Dynamic Rotating OTP`;
  const projPresentCount = document.getElementById("proj-present-count");
  if (projPresentCount) projPresentCount.textContent = `${(data.roster || []).length} Present`;

  const tunnelUrl = data.tunnel_url;
  const isTunnelActive = !!(data.is_tunnel_active && tunnelUrl);
  const tunnelChip = document.getElementById("att-tunnel-chip");
  const accessText = document.getElementById("att-mobile-access-text");

  if (tunnelChip) {
    tunnelChip.style.display = isTunnelActive ? "inline-flex" : "none";
  }
  if (accessText) {
    if (isTunnelActive) {
      accessText.innerHTML = `Mobile Access: Public Cloudflare Tunnel Active &bull; <strong style="color: #047857;">${escapeHtml(tunnelUrl.replace(/^https?:\/\//, ''))}</strong>`;
    } else {
      accessText.innerHTML = `Mobile Access: Connect your phone to Wi-Fi to scan or visit <strong id="att-lan-ip-display">${data.lan_ip || '127.0.0.1'}:8000</strong>`;
    }
  }

  const lanHost = tunnelUrl || data.network_url || (data.lan_ip ? `${window.location.protocol}//${data.lan_ip}${window.location.port ? ':' + window.location.port : ''}` : window.location.origin);
  const scannerUrl = `${lanHost}/attendance/student`;
  const scannerInput = document.getElementById("att-scanner-url-input");
  if (scannerInput) scannerInput.value = scannerUrl;
  const projUrlText = document.getElementById("proj-url-text");
  if (projUrlText) projUrlText.textContent = scannerUrl;

  const linkInput = document.getElementById("att-link-input");
  if (linkInput) linkInput.value = data.checkin_url || "";

  attendanceRoster = data.roster || [];
  renderAttendanceRoster(attendanceRoster);

  startAttendanceCountdown(data.expires_at, data.rotation_interval || 15);
}

function renderAttendanceInactiveState() {
  const badge = document.getElementById("att-status-badge");
  const badgeText = document.getElementById("att-status-text");
  if (badge) badge.className = "attendance-status-badge inactive";
  if (badgeText) badgeText.textContent = "No Active Session";

  const tunnelChip = document.getElementById("att-tunnel-chip");
  if (tunnelChip) tunnelChip.style.display = "none";

  const btnStart = document.getElementById("btn-start-attendance");
  const btnStartLabel = document.getElementById("btn-start-attendance-label");
  const btnExport = document.getElementById("btn-export-attendance");
  const btnExportLabel = document.getElementById("btn-export-attendance-label");
  const btnSimulate = document.getElementById("btn-simulate-scan");
  const btnRotate = document.getElementById("btn-manual-rotate-qr");

  if (btnStartLabel) btnStartLabel.textContent = "Start Session";
  if (btnStart) {
    btnStart.className = "pill-btn pill-btn-dark";
    btnStart.style.color = "#ffffff";
  }

  // Keep Export active if there is a recently ended session
  if (lastEndedSessionId) {
    if (btnExport) btnExport.disabled = false;
    if (btnExportLabel) btnExportLabel.textContent = "Export Last CSV";
  } else {
    if (btnExport) btnExport.disabled = true;
    if (btnExportLabel) btnExportLabel.textContent = "Export CSV";
  }

  if (btnSimulate) btnSimulate.disabled = true;
  if (btnRotate) btnRotate.disabled = true;

  const btnProjector = document.getElementById("btn-projector-mode");
  if (btnProjector) btnProjector.disabled = true;

  const projQrContainer = document.getElementById("proj-qr-container");
  if (projQrContainer) projQrContainer.innerHTML = "";

  const qrContainer = document.getElementById("att-qr-container");
  if (qrContainer) {
    qrContainer.innerHTML = `
      <div class="att-qr-placeholder">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5">
          <rect x="3" y="3" width="7" height="7"></rect>
          <rect x="14" y="3" width="7" height="7"></rect>
          <rect x="14" y="14" width="7" height="7"></rect>
          <rect x="3" y="14" width="7" height="7"></rect>
        </svg>
        <span>Click "Start Session" to project the live QR code</span>
      </div>
    `;
  }

  const linkInput = document.getElementById("att-link-input");
  if (linkInput) linkInput.value = "";

  const countdownEl = document.getElementById("att-countdown-display");
  if (countdownEl) countdownEl.textContent = "--s";

  const progressFill = document.getElementById("att-progress-fill");
  if (progressFill) progressFill.style.width = "100%";

  const projCountdownEl = document.getElementById("proj-timer-val");
  if (projCountdownEl) projCountdownEl.textContent = "--s";
  const projProgressFill = document.getElementById("proj-progress-fill");
  if (projProgressFill) projProgressFill.style.width = "100%";

  if (attendanceTimerInterval) {
    clearInterval(attendanceTimerInterval);
    attendanceTimerInterval = null;
  }
}

function startAttendanceCountdown(expiresAt, totalInterval) {
  if (attendanceTimerInterval) {
    clearInterval(attendanceTimerInterval);
    attendanceTimerInterval = null;
  }

  const countdownEl = document.getElementById("att-countdown-display");
  const progressFill = document.getElementById("att-progress-fill");
  const projCountdownEl = document.getElementById("proj-timer-val");
  const projProgressFill = document.getElementById("proj-progress-fill");

  const tick = async () => {
    const now = Date.now() / 1000;
    const remaining = Math.max(0, Math.round(expiresAt - now));
    const pct = Math.max(0, Math.min(100, (remaining / totalInterval) * 100));

    if (countdownEl) countdownEl.textContent = `${remaining}s`;
    if (progressFill) progressFill.style.width = `${pct}%`;
    if (projCountdownEl) projCountdownEl.textContent = `${remaining}s`;
    if (projProgressFill) projProgressFill.style.width = `${pct}%`;

    if (remaining <= 0) {
      clearInterval(attendanceTimerInterval);
      attendanceTimerInterval = null;
      await fetchActiveAttendanceSession();
    }
  };

  tick();
  attendanceTimerInterval = setInterval(tick, 1000);
}

function formatRosterTime(rawTime) {
  if (!rawTime) return "Just now";
  const s = String(rawTime).trim();
  if (s.includes("IST")) {
    const parts = s.split(" ");
    return parts.length >= 2 ? parts[1] : s;
  }
  try {
    const d = new Date(s.includes("T") || s.includes("Z") ? s : s.replace(" ", "T") + "Z");
    if (!isNaN(d.getTime())) {
      return d.toLocaleTimeString("en-GB", {
        timeZone: "Asia/Kolkata",
        hour12: false,
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit"
      });
    }
  } catch (e) {}
  return s.split(" ")[1] || s;
}

function renderAttendanceRoster(roster, newIds = new Set()) {
  const tbody = document.getElementById("att-roster-tbody");
  const counterEl = document.getElementById("att-present-counter");
  if (counterEl) counterEl.textContent = `${roster.length} Present`;

  if (!tbody) return;
  if (!roster || roster.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="att-empty-row">No students checked in yet. Ask students to scan the live QR code.</td></tr>`;
    return;
  }

  const searchInput = document.getElementById("att-roster-search-input");
  const filterQuery = (searchInput ? searchInput.value : "").toLowerCase().trim();

  const displayList = filterQuery
    ? roster.filter(r => (r.student_name || "").toLowerCase().includes(filterQuery) || (r.student_id || "").toLowerCase().includes(filterQuery))
    : roster;

  if (displayList.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5" class="att-empty-row">No matching students found for "${escapeHtml(filterQuery)}".</td></tr>`;
    return;
  }

  tbody.innerHTML = "";
  displayList.forEach((r, idx) => {
    const tr = document.createElement("tr");
    if (newIds && newIds.has(r.student_id)) {
      tr.className = "att-row-new";
    }
    const timeFormatted = formatRosterTime(r.checked_in_at);
    tr.innerHTML = `
      <td style="font-weight: 600; color: #64748b;">${idx + 1}</td>
      <td style="font-family: var(--font-mono); font-weight: 700; color: #0f172a;">${escapeHtml(r.student_id)}</td>
      <td style="font-weight: 600;">${escapeHtml(r.student_name)}</td>
      <td style="font-size: 12px; color: #64748b;">${escapeHtml(timeFormatted)}</td>
      <td><span class="att-status-pill">Verified Present</span></td>
    `;
    tbody.appendChild(tr);
  });
}

function initAttendanceModule() {
  const modal = document.getElementById("modal-start-attendance");
  const btnStart = document.getElementById("btn-start-attendance");
  const btnCloseModal = document.getElementById("btn-close-modal-attendance");
  const btnCancelModal = document.getElementById("btn-cancel-modal-attendance");
  const btnConfirmStart = document.getElementById("btn-confirm-start-attendance");

  const checkAutoExport = document.getElementById("check-auto-export-attendance");
  const modalCheckAutoExport = document.getElementById("modal-att-auto-export");

  // Load and sync auto-export preference
  const savedAutoExport = localStorage.getItem("att_auto_export_csv") !== "false";
  if (checkAutoExport) checkAutoExport.checked = savedAutoExport;
  if (modalCheckAutoExport) modalCheckAutoExport.checked = savedAutoExport;

  checkAutoExport?.addEventListener("change", (e) => {
    localStorage.setItem("att_auto_export_csv", e.target.checked ? "true" : "false");
    if (modalCheckAutoExport) modalCheckAutoExport.checked = e.target.checked;
  });

  modalCheckAutoExport?.addEventListener("change", (e) => {
    localStorage.setItem("att_auto_export_csv", e.target.checked ? "true" : "false");
    if (checkAutoExport) checkAutoExport.checked = e.target.checked;
  });

  const openModal = () => modal?.classList.remove("hidden");
  const closeModal = () => modal?.classList.add("hidden");

  btnCloseModal?.addEventListener("click", closeModal);
  btnCancelModal?.addEventListener("click", closeModal);

  btnStart?.addEventListener("click", async () => {
    if (activeAttendanceSession && activeAttendanceSession.active) {
      const sessId = activeAttendanceSession.session_id;
      const count = (attendanceRoster || []).length;
      if (confirm(`End current attendance session? (${count} student${count === 1 ? '' : 's'} recorded). The live QR code will be deactivated.`)) {
        try {
          const res = await fetch("/api/attendance/session/end", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessId })
          });
          const endData = await res.json();
          lastEndedSessionId = sessId;
          stopAttendancePolling();

          // Auto-export CSV check
          const isAutoExport = checkAutoExport ? checkAutoExport.checked : (localStorage.getItem("att_auto_export_csv") !== "false");
          if (isAutoExport) {
            downloadAttendanceCsv(sessId);
            showAttendanceToast(`Session ended. Roster CSV (${count} students) downloaded.`, "success");
          } else {
            showAttendanceToast(`Session ended (${count} students recorded). Click 'Export Last CSV' anytime to download.`, "info");
          }

          await fetchActiveAttendanceSession();
        } catch (err) {
          console.error("Error ending session:", err);
        }
      }
    } else {
      openModal();
    }
  });

  // Preset chips click & manual input sync
  const intervalInput = document.getElementById("modal-att-interval");
  const presetChips = document.querySelectorAll(".att-interval-preset-chip");

  presetChips.forEach(chip => {
    chip.addEventListener("click", () => {
      const val = chip.getAttribute("data-sec");
      if (intervalInput && val) {
        intervalInput.value = val;
        presetChips.forEach(c => {
          c.classList.remove("active");
          c.style.background = "#f1f5f9";
          c.style.color = "#475569";
          c.style.borderColor = "#e2e8f0";
        });
        chip.classList.add("active");
        chip.style.background = "#2563eb";
        chip.style.color = "#ffffff";
        chip.style.borderColor = "#2563eb";
      }
    });
  });

  intervalInput?.addEventListener("input", (e) => {
    const val = parseInt(e.target.value, 10);
    presetChips.forEach(c => {
      if (parseInt(c.getAttribute("data-sec"), 10) === val) {
        c.classList.add("active");
        c.style.background = "#2563eb";
        c.style.color = "#ffffff";
        c.style.borderColor = "#2563eb";
      } else {
        c.classList.remove("active");
        c.style.background = "#f1f5f9";
        c.style.color = "#475569";
        c.style.borderColor = "#e2e8f0";
      }
    });
  });

  btnConfirmStart?.addEventListener("click", async () => {
    const course = document.getElementById("modal-att-course")?.value.trim() || "Course Attendance";
    const section = document.getElementById("modal-att-section")?.value.trim() || "Section A";
    const intervalRaw = document.getElementById("modal-att-interval")?.value;
    let interval = parseInt(intervalRaw, 10);
    if (isNaN(interval) || interval < 1) {
      interval = 1;
    }
    const useTunnel = document.getElementById("modal-att-use-tunnel") ? document.getElementById("modal-att-use-tunnel").checked : true;

    btnConfirmStart.disabled = true;
    const origText = btnConfirmStart.textContent;
    btnConfirmStart.textContent = useTunnel ? "Starting Cloudflare Tunnel..." : "Starting...";

    try {
      const res = await fetch("/api/attendance/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_name: course,
          section: section,
          rotation_interval_seconds: interval,
          use_tunnel: useTunnel
        })
      });
      const data = await res.json();
      if (data.success) {
        closeModal();
        await fetchActiveAttendanceSession();
        if (data.tunnel_url) {
          showAttendanceToast(`Live attendance active with Cloudflare Tunnel`, "success");
        } else {
          showAttendanceToast(`Live attendance started for ${course}`, "success");
        }
      } else {
        alert(data.error || "Could not start session.");
      }
    } catch (err) {
      alert("Failed to start attendance session: " + err.message);
    } finally {
      btnConfirmStart.disabled = false;
      btnConfirmStart.textContent = origText;
    }
  });

  document.getElementById("btn-manual-rotate-qr")?.addEventListener("click", async () => {
    if (!activeAttendanceSession) return;
    try {
      await fetch("/api/attendance/session/rotate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: activeAttendanceSession.session_id })
      });
      await fetchActiveAttendanceSession();
      showAttendanceToast("QR code rotated with new token", "info");
    } catch (err) {
      console.error("Rotate error:", err);
    }
  });

  document.getElementById("btn-simulate-scan")?.addEventListener("click", async () => {
    if (!activeAttendanceSession) return;
    try {
      const res = await fetch("/api/attendance/simulate_scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: activeAttendanceSession.session_id })
      });
      const data = await res.json();
      if (data.success) {
        await checkActiveAttendanceUpdates();
      } else {
        alert(data.error || "Simulation error.");
      }
    } catch (err) {
      console.error("Simulation error:", err);
    }
  });

  document.getElementById("btn-copy-checkin-link")?.addEventListener("click", () => {
    const linkInput = document.getElementById("att-link-input");
    if (!linkInput || !linkInput.value) return;
    navigator.clipboard.writeText(linkInput.value);
    const btn = document.getElementById("btn-copy-checkin-link");
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = orig; }, 1500);
    }
  });

  document.getElementById("btn-copy-scanner-link")?.addEventListener("click", () => {
    const scannerInput = document.getElementById("att-scanner-url-input");
    if (!scannerInput || !scannerInput.value) return;
    navigator.clipboard.writeText(scannerInput.value);
    const btn = document.getElementById("btn-copy-scanner-link");
    if (btn) {
      const orig = btn.textContent;
      btn.textContent = "Copied!";
      setTimeout(() => { btn.textContent = orig; }, 1500);
    }
  });

  const modalProjector = document.getElementById("modal-attendance-projector");
  document.getElementById("btn-projector-mode")?.addEventListener("click", () => {
    if (!activeAttendanceSession) return;
    modalProjector?.classList.remove("hidden");
  });

  document.getElementById("btn-close-projector")?.addEventListener("click", () => {
    modalProjector?.classList.add("hidden");
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modalProjector && !modalProjector.classList.contains("hidden")) {
      modalProjector.classList.add("hidden");
    }
  });

  document.getElementById("btn-export-attendance")?.addEventListener("click", () => {
    const targetId = (activeAttendanceSession && activeAttendanceSession.session_id) || lastEndedSessionId;
    if (!targetId) {
      alert("No active or recent attendance session to export.");
      return;
    }
    downloadAttendanceCsv(targetId);
  });

  document.getElementById("att-roster-search-input")?.addEventListener("input", () => {
    renderAttendanceRoster(attendanceRoster);
  });

  fetchActiveAttendanceSession();
}

function initDashboard() {
  document.getElementById("btn-refresh-dashboard")?.addEventListener("click", () => {
    fetchStatus();
    fetchActiveAttendanceSession();
  });
  initAttendanceModule();
}

// ----------------------------------------------------------------------------
// Productivity Tools (Documents, Web Browser, Email, Calendar)
// ----------------------------------------------------------------------------
function initProductivityTools() {
  // Document safe read & summarize
  const docPath = document.getElementById("doc-file-path");
  const docViewer = document.getElementById("doc-viewer-container");
  const docText = document.getElementById("doc-viewer-text");
  const docTitle = document.getElementById("doc-viewer-filename");

  document.getElementById("btn-doc-read")?.addEventListener("click", async () => {
    const path = docPath?.value.trim();
    if (!path) return alert("Please specify a document path.");

    try {
      const res = await fetch("/api/docs/read", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, max_chars: 4000 })
      });
      const data = await res.json();

      docViewer?.classList.remove("hidden");
      if (docTitle) docTitle.textContent = `Safe Read: ${path}`;
      if (docText) docText.textContent = data.content || data.error || "No content returned.";
    } catch (e) {
      alert("Error reading document: " + e.message);
    }
  });

  document.getElementById("btn-doc-summarize")?.addEventListener("click", async () => {
    const path = docPath?.value.trim();
    if (!path) return alert("Please specify a document path.");

    try {
      const res = await fetch("/api/docs/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path, max_chars: 4000 })
      });
      const data = await res.json();

      docViewer?.classList.remove("hidden");
      if (docTitle) docTitle.textContent = `Summary: ${path}`;
      if (docText) docText.textContent = data.summary || data.error || "No summary returned.";
    } catch (e) {
      alert("Error summarizing document: " + e.message);
    }
  });

  // Browser Fetch
  const browserUrl = document.getElementById("browser-url-input");
  const browserViewer = document.getElementById("browser-viewer-container");
  const browserText = document.getElementById("browser-viewer-text");

  document.getElementById("btn-fetch-browser")?.addEventListener("click", async () => {
    const url = browserUrl?.value.trim();
    if (!url) return alert("Please enter a valid URL.");

    try {
      const res = await fetch("/api/browser/fetch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, max_chars: 4000 })
      });
      const data = await res.json();

      browserViewer?.classList.remove("hidden");
      if (browserText) browserText.textContent = data.text || data.error || "No content.";
    } catch (e) {
      alert("Error fetching page: " + e.message);
    }
  });

  // Initialize Email Copilot
  initEmailCopilot();

  // Initialize GitHub Dashboard
  initGithubDashboard();

  // Initialize Calendar Scheduler Controls
  initCalendarSchedulerControls();
}

// ----------------------------------------------------------------------------
// Email Copilot & Smart Inbox Engine (Ergonomic Upgrade)
// ----------------------------------------------------------------------------
let activeEmailCategory = "all";
let activeEmailPriority = "all";
let activeEmailId = null;
let activeEmailMsg = null;
let activeReplyTone = "professional";
let emailSearchDebounce = null;
let activeConnectedEmail = "";
let activeAccountType = "demo";
let isThreadedView = false;
let currentEmailViewMode = "clean";

function normalizeThreadSubject(subj) {
  if (!subj) return "(no subject)";
  return subj.replace(/^(\s*(re|fwd|fw):\s*)+/i, "").trim().toLowerCase();
}

function detectCalendarRelevance(email, summaryText) {
  if (!email) return false;
  const combined = `${email.subject || ""} ${email.body || ""} ${summaryText || ""}`.toLowerCase();
  
  // Explicit meeting/calendar terminology
  const explicitWords = [
    "meeting", "meet", "call", "zoom", "google meet", "teams",
    "schedule", "reschedule", "appointment", "calendar", "invite",
    "invitation", "sync", "webinar", "interview", "catch up",
    "deadline", "due date", "due by", "rsvp", "conference",
    "scheduled for", "see you on", "join the call", "google calendar"
  ];

  const hasKeyword = explicitWords.some(word => {
    const rx = new RegExp(`\\b${word}\\b`, "i");
    return rx.test(combined);
  });

  const hasSpecificTimeDate = /\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+at\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b/i.test(combined) ||
                              /\b(tomorrow|today)\s+at\s+\d{1,2}(:\d{2})?\s*(am|pm)?\b/i.test(combined) ||
                              /\bat\s+\d{1,2}(:\d{2})\s*(am|pm)\b/i.test(combined);

  return hasKeyword || hasSpecificTimeDate;
}

function detectActionItemsRelevance(summaryText) {
  if (!summaryText) return false;
  if (/action items:?\s*(none|n\/a|no actionable|no immediate|none\b)/i.test(summaryText)) {
    return false;
  }
  const match = summaryText.match(/action items:?\s*([^\n\r]+)/i);
  if (match) {
    const content = match[1].trim();
    if (/^(none|n\/a|not specified|none\.)/i.test(content)) return false;
    return content.length > 5;
  }
  return false;
}

function updateBriefingActionButtons(emailMsg, summaryText) {
  const calBtn = document.getElementById("btn-summary-add-calendar");
  const taskBtn = document.getElementById("btn-summary-create-task");
  
  const hasCalendar = detectCalendarRelevance(emailMsg, summaryText);
  const hasTasks = detectActionItemsRelevance(summaryText);

  if (calBtn) {
    calBtn.style.display = hasCalendar ? "inline-flex" : "none";
  }
  if (taskBtn) {
    taskBtn.style.display = hasTasks ? "inline-flex" : "none";
  }
}

const AVATAR_PALETTE = [
  { bg: "#2563eb", text: "#ffffff" }, // Blue
  { bg: "#7c3aed", text: "#ffffff" }, // Violet
  { bg: "#059669", text: "#ffffff" }, // Emerald
  { bg: "#d97706", text: "#ffffff" }, // Amber
  { bg: "#dc2626", text: "#ffffff" }, // Rose
  { bg: "#0891b2", text: "#ffffff" }, // Cyan
  { bg: "#4f46e5", text: "#ffffff" }, // Indigo
  { bg: "#475569", text: "#ffffff" }, // Slate
];

function getSenderAvatar(senderStr) {
  if (!senderStr) return { char: "U", bg: "#64748b", text: "#ffffff", cleanName: "Unknown Sender", rawEmail: "" };
  let cleanName = senderStr;
  let rawEmail = "";
  const match = senderStr.match(/^(.*?)\s*<([^>]+)>/);
  if (match) {
    cleanName = match[1].replace(/["']/g, "").trim() || match[2].split("@")[0];
    cleanName = cleanName.replace(/\b(CSE|ISE|ECE|EEE|MECH|CIVIL|AIML)-\d+\b/gi, "").trim();
    rawEmail = match[2].trim();
  } else if (senderStr.includes("@")) {
    cleanName = senderStr.split("@")[0].replace(/[._-]/g, " ").replace(/\b\w/g, c => c.toUpperCase());
    rawEmail = senderStr;
  }
  const char = cleanName.charAt(0).toUpperCase() || "M";
  let hash = 0;
  for (let i = 0; i < cleanName.length; i++) {
    hash = cleanName.charCodeAt(i) + ((hash << 5) - hash);
  }
  const color = AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length];
  return { char, bg: color.bg, text: color.text, cleanName, rawEmail };
}

function formatEmailTime(isoStr) {
  if (!isoStr) return "Recent";
  const date = new Date(isoStr);
  if (isNaN(date.getTime())) return "Recent";
  const now = new Date();
  const diffSec = Math.floor((now - date) / 1000);
  if (diffSec < 60) return "Just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400 && date.getDate() === now.getDate()) {
    return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  }
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.getDate() === yesterday.getDate() && date.getMonth() === yesterday.getMonth() && date.getFullYear() === yesterday.getFullYear()) {
    return "Yesterday";
  }
  if (diffSec < 86400 * 6) {
    return date.toLocaleDateString([], { weekday: 'short' });
  }
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function decodeHtmlEntities(str) {
  if (!str) return "";
  const txt = document.createElement("textarea");
  txt.innerHTML = str;
  return txt.value;
}

function cleanSnippet(text) {
  if (!text) return "";
  let cleaned = decodeHtmlEntities(text);
  cleaned = cleaned
    .replace(/\*{2,}\s*disclaimer\s*\*{2,}[\s\S]*/i, "")
    .replace(/\n\s*--\s*[\s\S]*/i, "")
    .replace(/\b(The information contained in this (?:electronic )?communication[\s\S]*)/i, "")
    .replace(/\[image:[^\]]*\]/gi, "")
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\u00a0|&nbsp;/gi, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned;
}

function formatEmailBody(rawBody) {
  if (!rawBody) return "(Empty message content)";

  // Strip Outlook/MSO comments and conditional tags
  let cleaned = rawBody
    .replace(/<!--[\s\S]*?-->/g, "")
    .replace(/<!\[if[\s\S]*?<!\[endif\]>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "");

  // Detect and split institutional / legal disclaimers
  const disclaimerSeparators = [
    /\n\s*--\s*\n\s*\*{2,}\s*DISCLAIMER\s*\*{2,}/i,
    /\n\s*\*{3,}\s*DISCLAIMER\s*\*{3,}/i,
    /\n\s*--\s*\n/i,
    /\n\s*_{3,}\s*\n/i,
    /(The information contained in this (?:electronic )?communication is intended solely.*)/is,
    /(This (?:e-?mail|message|communication) (?:and any attachments )?is confidential.*)/is,
    /(CONFIDENTIALITY NOTICE:?.*)/is
  ];

  let mainBody = cleaned;
  let disclaimerBody = "";

  for (const pattern of disclaimerSeparators) {
    const match = cleaned.search(pattern);
    if (match !== -1) {
      mainBody = cleaned.slice(0, match).trim();
      disclaimerBody = cleaned.slice(match).trim();
      break;
    }
  }

  if (!mainBody && disclaimerBody) {
    mainBody = disclaimerBody;
    disclaimerBody = "";
  }

  const formatText = (text) => {
    let escaped = escapeHtml(text);
    // Replace [image: ...] with clean badge
    escaped = escaped.replace(/\[image:\s*([^\]]+)\]/gi, (match, label) => {
      return `<span class="email-image-chip"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><circle cx="8.5" cy="8.5" r="1.5"></circle><polyline points="21 15 16 10 5 21"></polyline></svg> ${escapeHtml(label)}</span>`;
    });
    // Replace raw URLs with stylish, non-overflowing truncated links
    const urlRegex = /(https?:\/\/[^\s<>"']+)/gi;
    escaped = escaped.replace(urlRegex, (url) => {
      try {
        const parsed = new URL(url);
        const displayHost = parsed.hostname.replace(/^www\./, '');
        const displayPath = parsed.pathname.length > 15 ? parsed.pathname.slice(0, 15) + '…' : parsed.pathname;
        const label = displayHost + (displayPath === '/' ? '' : displayPath);
        return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="email-link" title="${url}">${label} ↗</a>`;
      } catch (e) {
        return `<a href="${url}" target="_blank" rel="noopener noreferrer" class="email-link">${url.slice(0, 30)}… ↗</a>`;
      }
    });
    return escaped;
  };

  let html = `<div class="email-main-message">${formatText(mainBody)}</div>`;

  if (disclaimerBody) {
    html += `
      <details class="email-disclaimer-fold">
        <summary>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
            <polyline points="14 2 14 8 20 8"></polyline>
            <line x1="16" y1="13" x2="8" y2="13"></line>
            <line x1="16" y1="17" x2="8" y2="17"></line>
            <polyline points="10 9 9 9 8 9"></polyline>
          </svg>
          <span>Institutional Legal Disclaimer</span>
          <span class="fold-badge">Click to view</span>
        </summary>
        <div class="disclaimer-text">${formatText(disclaimerBody)}</div>
      </details>
    `;
  }

  return html;
}

function showSystemToast(message, duration = 4000) {
  let toast = document.getElementById("system-notification-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "system-notification-toast";
    toast.className = "quick-send-toast";
    document.body.appendChild(toast);
  }
  toast.innerHTML = `<span>${escapeHtml(message)}</span>`;
  toast.classList.remove("hidden");
  toast.style.display = "flex";
  if (toast._timer) clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    toast.style.display = "none";
  }, duration);
}

function formatBentoSummary(rawSummary) {
  if (!rawSummary) return "Actionable communication requiring executive review.";
  
  // Extract Urgency if present
  let urgency = "Medium";
  if (/urgency level:\s*high/i.test(rawSummary)) urgency = "High";
  else if (/urgency level:\s*low/i.test(rawSummary)) urgency = "Low";

  const urgencyClass = urgency === "High" ? "urgency-high" : (urgency === "Low" ? "urgency-low" : "urgency-med");
  
  // Format clean paragraphs with crisp typographic badges (no emojis)
  let formatted = escapeHtml(rawSummary)
    .replace(/(Executive Summary:?)/gi, '<span class="bento-badge-tag bento-blue">EXECUTIVE SUMMARY</span><br>')
    .replace(/(Key Takeaways:?)/gi, '<div class="bento-section"><span class="bento-badge-tag bento-slate">KEY TAKEAWAYS</span>')
    .replace(/(Action Items:?)/gi, '</div><div class="bento-section"><span class="bento-badge-tag bento-amber">ACTION ITEMS</span>')
    .replace(/(Urgency Level:?\s*(High|Medium|Low)?)/gi, `</div><div class="bento-section"><span class="bento-badge-urgency ${urgencyClass}">Urgency: ${urgency}</span></div>`);

  return formatted;
}

function initEmailCopilot() {
  fetchEmailAccount();

  // Handle Google OAuth callback notification and redirection
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get("google_auth") === "success") {
    const userEmail = urlParams.get("email") || "Google Account";
    window.history.replaceState({}, document.title, window.location.pathname + "#inbox");
    document.getElementById("nav-btn-inbox")?.click();
    setTimeout(() => {
      alert(`Successfully signed in with Google (${userEmail})!\nYour Gmail mailbox is connected and synchronized.`);
    }, 200);
  } else if (urlParams.get("google_error")) {
    const err = urlParams.get("google_error");
    window.history.replaceState({}, document.title, window.location.pathname + "#inbox");
    setTimeout(() => {
      alert("Google Sign-In Notice: " + err);
    }, 200);
  }

  // Back to Inbox Button in Detail View
  document.getElementById("btn-back-to-inbox")?.addEventListener("click", () => {
    closeEmailDetailView();
  });

  // Category Tabs (Primary, Unread, Urgent, Action Needed)
  document.querySelectorAll(".inbox-cat-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".inbox-cat-tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      activeEmailCategory = tab.dataset.category || "all";
      fetchEmailInbox();
    });
  });

  // Select All Checkbox
  document.getElementById("email-select-all-check")?.addEventListener("change", (e) => {
    const isChecked = e.target.checked;
    document.querySelectorAll(".row-checkbox").forEach(cb => { cb.checked = isChecked; });
  });

  // Reload / Sync Mail Button (above emails row)
  document.getElementById("btn-table-sync")?.addEventListener("click", () => {
    syncEmailInbox();
  });

  // Top bar Google Account Popover & Login/Logout actions
  const topGoogleBtn = document.getElementById("btn-top-google-account");
  const topGooglePopover = document.getElementById("google-account-popover");
  const btnTopLogout = document.getElementById("btn-top-google-logout");

  topGoogleBtn?.addEventListener("click", (e) => {
    e.stopPropagation();
    topGooglePopover?.classList.toggle("hidden");
  });

  document.addEventListener("click", (e) => {
    if (!e.target.closest("#top-user-pill-wrap")) {
      topGooglePopover?.classList.add("hidden");
    }
  });

  btnTopLogout?.addEventListener("click", async () => {
    const confirmed = confirm("Disconnect your Google account and return to offline sandbox mode?");
    if (!confirmed) return;
    try {
      const res = await fetch("/api/email/account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "demo.executive@local.ai", account_type: "demo" })
      });
      const data = await res.json();
      if (data.success) {
        topGooglePopover?.classList.add("hidden");
        await fetchEmailAccount();
        await fetchEmailInbox();
      }
    } catch (e) {
      alert("Error logging out: " + e.message);
    }
  });

  // Compose button opens detail view in composer mode
  document.getElementById("btn-new-email-draft")?.addEventListener("click", () => {
    openEmailComposerDraft();
  });

  // Global Escape key returns from single-email detail to inbox list
  window.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      const detailView = document.getElementById("inbox-detail-view");
      if (detailView && !detailView.classList.contains("hidden")) {
        closeEmailDetailView();
      }
    }
  });

  // Search input in top header
  const emailSearchInput = document.getElementById("email-search-input");
  emailSearchInput?.addEventListener("input", (e) => {
    const val = e.target.value.trim();
    if (emailSearchDebounce) clearTimeout(emailSearchDebounce);
    emailSearchDebounce = setTimeout(() => {
      fetchEmailInbox(val);
    }, 280);
  });

  // Toggle Summary Card Accordion
  document.getElementById("btn-toggle-summary-card")?.addEventListener("click", () => {
    document.getElementById("ai-summary-card")?.classList.toggle("collapsed");
  });

  // Copy Email Body Button
  document.getElementById("btn-copy-email-body")?.addEventListener("click", () => {
    const text = document.getElementById("detail-body-text")?.innerText || "";
    navigator.clipboard?.writeText(text);
    const copyBtn = document.getElementById("btn-copy-email-body");
    if (copyBtn) {
      copyBtn.textContent = "Copied!";
      setTimeout(() => { copyBtn.textContent = "Copy Text"; }, 2000);
    }
  });

  // Message Body Reply Button
  document.getElementById("btn-body-reply")?.addEventListener("click", () => {
    document.getElementById("ai-reply-card")?.scrollIntoView({ behavior: "smooth" });
    document.getElementById("reply-body")?.focus();
  });

  // Toggle Read / Unread Status
  document.getElementById("btn-toggle-read-status")?.addEventListener("click", () => {
    if (!activeEmailId) return;
    const activeRow = document.querySelector(`.email-row[data-id="${activeEmailId}"]`);
    const label = document.getElementById("read-status-label");
    if (activeRow) {
      const isUnread = activeRow.classList.toggle("unread");
      activeRow.classList.toggle("read", !isUnread);
      if (label) label.textContent = isUnread ? "Mark Read" : "Mark Unread";
    } else if (label) {
      label.textContent = label.textContent === "Mark Read" ? "Mark Unread" : "Mark Read";
    }
  });

  // One-click quick intent chips
  document.querySelectorAll(".intent-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const intent = chip.getAttribute("data-intent");
      const guidanceInput = document.getElementById("reply-guidance-input");
      if (guidanceInput) guidanceInput.value = intent;
      if (activeEmailId) {
        generateSmartReply(activeEmailId);
      }
    });
  });

  // Re-run AI semantic classification across inbox
  document.getElementById("btn-classify-inbox")?.addEventListener("click", async () => {
    const btn = document.getElementById("btn-classify-inbox");
    const origHtml = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = `<span>Classifying Inbox...</span>`;
    try {
      const res = await fetch("/api/email/classify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: true })
      });
      const data = await res.json();
      if (data.success) {
        showSystemToast(`Classification complete: ${data.processed_count || 0} emails categorized.`);
        await fetchEmailIntelligenceStats();
        await fetchEmailInbox();
      } else {
        alert("Classification warning: " + (data.error || "Failed"));
      }
    } catch (e) {
      alert("Classification error: " + e.message);
    } finally {
      btn.disabled = false;
      btn.innerHTML = origHtml;
    }
  });

  // Bulk cleanup modal triggers
  document.getElementById("btn-open-bulk-cleanup")?.addEventListener("click", openBulkCleanupModal);
  document.getElementById("btn-close-cleanup-modal")?.addEventListener("click", () => {
    document.getElementById("modal-bulk-cleanup")?.classList.add("hidden");
  });
  document.getElementById("btn-cancel-cleanup")?.addEventListener("click", () => {
    document.getElementById("modal-bulk-cleanup")?.classList.add("hidden");
  });
  document.getElementById("btn-confirm-cleanup")?.addEventListener("click", executeBulkCleanup);

  // Cloud Privacy Settings Button
  const btnPrivacy = document.getElementById("btn-email-privacy-toggle");
  if (btnPrivacy) {
    const updatePrivacyBtn = (allowed) => {
      btnPrivacy.textContent = allowed ? "Cloud AI: Enabled (Groq)" : "Cloud AI: Local Only";
      btnPrivacy.style.color = allowed ? "#15803d" : "#475569";
    };
    fetch("/api/email/privacy_settings")
      .then(r => r.json())
      .then(d => { if (d.success) updatePrivacyBtn(d.allow_cloud_processing); })
      .catch(() => {});

    btnPrivacy.addEventListener("click", async () => {
      try {
        const curRes = await fetch("/api/email/privacy_settings");
        const curData = await curRes.json();
        const currentlyAllowed = curData.allow_cloud_processing || false;
        const nextState = !currentlyAllowed;
        if (nextState) {
          const agree = confirm("PRIVACY CONSENT REQUIRED:\n\nEnabling Cloud AI permits transmitting email snippets and conversation threads to Groq Cloud LLM for advanced classification and drafting.\n\nDo you grant consent to enable Cloud processing?");
          if (!agree) return;
        }
        const postRes = await fetch("/api/email/privacy_settings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ allow_cloud_processing: nextState })
        });
        const postData = await postRes.json();
        if (postData.success) {
          updatePrivacyBtn(postData.allow_cloud_processing);
          showSystemToast(nextState ? "Cloud AI processing enabled with consent." : "Cloud AI disabled. Local processing only.");
        }
      } catch (err) {
        alert("Failed to update privacy settings: " + err.message);
      }
    });
  }

  // Manual Category Correction listener
  document.getElementById("detail-category-select")?.addEventListener("change", async (e) => {
    if (!activeEmailId) return;
    const newCat = e.target.value;
    try {
      const res = await fetch("/api/email/category/update", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message_id: activeEmailId, category: newCat })
      });
      const data = await res.json();
      if (data.success) {
        showSystemToast(`Category manually updated to: ${newCat.replace('_', ' ')}`);
        await fetchEmailIntelligenceStats();
      }
    } catch (err) {
      alert("Failed to update category: " + err.message);
    }
  });

  // Trust Sender button
  document.getElementById("btn-sender-trust")?.addEventListener("click", async () => {
    if (!activeEmailMsg) return;
    const avatar = getSenderAvatar(activeEmailMsg.sender);
    const email = avatar.rawEmail || activeEmailMsg.sender;
    try {
      const res = await fetch("/api/email/sender/reputation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sender_email: email, reputation: "trusted", display_name: avatar.cleanName })
      });
      const data = await res.json();
      if (data.success) {
        showSystemToast(`Sender ${email} marked as TRUSTED.`);
        const repLabel = document.getElementById("detail-sender-rep-label");
        if (repLabel) {
          repLabel.textContent = "Sender: Trusted";
          repLabel.className = "sender-rep-label trusted";
        }
        await fetchEmailIntelligenceStats();
      }
    } catch (err) {
      alert("Error updating sender: " + err.message);
    }
  });

  // Block Sender button
  document.getElementById("btn-sender-block")?.addEventListener("click", async () => {
    if (!activeEmailMsg) return;
    const avatar = getSenderAvatar(activeEmailMsg.sender);
    const email = avatar.rawEmail || activeEmailMsg.sender;
    const confirmed = confirm(`Are you sure you want to block sender ${email}? All future emails from this sender will be marked as spam.`);
    if (!confirmed) return;
    try {
      const res = await fetch("/api/email/sender/reputation", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sender_email: email, reputation: "blocked", display_name: avatar.cleanName })
      });
      const data = await res.json();
      if (data.success) {
        showSystemToast(`Sender ${email} BLOCKED and classified as spam.`);
        const repLabel = document.getElementById("detail-sender-rep-label");
        if (repLabel) {
          repLabel.textContent = "Sender: Blocked";
          repLabel.className = "sender-rep-label blocked";
        }
        await fetchEmailIntelligenceStats();
      }
    } catch (err) {
      alert("Error blocking sender: " + err.message);
    }
  });

  // Toggle Context Card Accordion
  document.getElementById("btn-toggle-context-card")?.addEventListener("click", () => {
    const card = document.getElementById("email-context-card");
    const btn = document.getElementById("btn-toggle-context-card");
    if (card) {
      const isCollapsed = card.classList.toggle("collapsed");
      if (btn) btn.textContent = isCollapsed ? "Expand" : "Collapse";
    }
  });

  // 5 Specialized Context-Aware Reply Buttons
  document.querySelectorAll(".btn-context-reply").forEach(btn => {
    btn.addEventListener("click", () => {
      if (!activeEmailId) return alert("Select an email first.");
      const replyType = btn.getAttribute("data-reply-type") || "ai_smart";
      generateContextAwareReply(activeEmailId, replyType);
    });
  });

  // View mode toggle (Clean Text vs Original Formatted HTML)
  document.getElementById("btn-view-mode-clean")?.addEventListener("click", () => {
    currentEmailViewMode = "clean";
    document.getElementById("btn-view-mode-clean")?.classList.add("active");
    document.getElementById("btn-view-mode-html")?.classList.remove("active");
    document.getElementById("detail-body-text")?.classList.remove("hidden");
    document.getElementById("detail-body-html")?.classList.add("hidden");
  });

  document.getElementById("btn-view-mode-html")?.addEventListener("click", () => {
    currentEmailViewMode = "html";
    document.getElementById("btn-view-mode-html")?.classList.add("active");
    document.getElementById("btn-view-mode-clean")?.classList.remove("active");
    document.getElementById("detail-body-html")?.classList.remove("hidden");
    document.getElementById("detail-body-text")?.classList.add("hidden");
  });

  // Schedule follow-up on Calendar from briefing
  document.getElementById("btn-summary-add-calendar")?.addEventListener("click", async () => {
    if (!activeEmailId) return alert("Select an email message first.");
    const subject = document.getElementById("detail-subject-title")?.textContent || "Email Follow-up";
    const sender = document.getElementById("detail-sender-name")?.textContent || "Sender";
    const cleanSubj = subject.replace(/^(\s*(re|fwd|fw):\s*)+/i, "").trim();

    const tomorrow = new Date();
    tomorrow.setDate(tomorrow.getDate() + 1);
    const dateStr = tomorrow.toISOString().split("T")[0];
    const startTime = `${dateStr}T10:00:00`;
    const endTime = `${dateStr}T11:00:00`;

    try {
      const res = await fetch("/api/calendar/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: `Follow-up: ${cleanSubj}`,
          start_time: startTime,
          end_time: endTime,
          description: `Follow-up regarding communication from ${sender}`
        })
      });
      const data = await res.json();
      if (data.success) {
        showSystemToast(`Added to Calendar: "Follow-up: ${cleanSubj}" tomorrow at 10:00 AM`);
        fetchNotifications();
      } else {
        alert(`Failed to add event: ${data.error || "Unknown error"}`);
      }
    } catch (err) {
      alert(`Calendar error: ${err.message}`);
    }
  });

  // Create Task from briefing action items
  document.getElementById("btn-summary-create-task")?.addEventListener("click", async () => {
    if (!activeEmailId) return alert("Select an email message first.");
    const subject = document.getElementById("detail-subject-title")?.textContent || "Email Follow-up";
    const goal = `Review and execute action items from email: ${subject}`;

    try {
      const res = await fetch("/api/tasks/plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ goal })
      });
      const data = await res.json();
      if (data.success) {
        showSystemToast(`Plan synthesized with ${data.steps?.length || 0} step(s). Switching to Manage Tasks.`);
        document.querySelector('.nav-item[data-tab="tab-leads"]')?.click();
      } else {
        alert(`Failed to plan task: ${data.error || "Unknown error"}`);
      }
    } catch (err) {
      alert(`Task error: ${err.message}`);
    }
  });

  // Threaded View Toggle
  document.getElementById("btn-toggle-threaded")?.addEventListener("click", () => {
    isThreadedView = !isThreadedView;
    document.getElementById("btn-toggle-threaded")?.classList.toggle("active", isThreadedView);
    fetchEmailInbox();
  });

  // Instant Send with 5-Second Undo Toast
  document.getElementById("btn-quick-send-now")?.addEventListener("click", () => {
    const to = document.getElementById("reply-to")?.value?.trim();
    const subject = document.getElementById("reply-subject")?.value?.trim();
    const body = document.getElementById("reply-body")?.value?.trim();
    if (!to || !body) {
      return alert("Please draft or select a reply intent before sending.");
    }
    dispatchQuickReplyWithUndo({ to, subject, body });
  });

  // Link account modal
  const openModalBtn = document.getElementById("btn-open-link-account");
  const linkModal = document.getElementById("link-email-modal");
  const cancelLinkBtn = document.getElementById("btn-cancel-link-account");
  const cancelDemoBtn = document.getElementById("btn-cancel-demo-account");
  const closeIconBtn = document.getElementById("btn-close-link-modal");
  const unlinkBtn = document.getElementById("btn-unlink-account");
  const cancelGoogleBtn = document.getElementById("btn-cancel-google-account");
  const btnTopManage = document.getElementById("btn-top-manage-account");
  const btnGoogleModalDisconnect = document.getElementById("btn-google-modal-disconnect");

  const openLinkModal = () => {
    linkModal?.classList.remove("hidden");
    const emailInput = document.getElementById("link-imap-email");
    const tabGoogle = document.getElementById("tab-account-google");
    const tabImap = document.getElementById("tab-account-imap");
    const googleConnectedView = document.getElementById("google-pane-connected-view");
    const googleLoginView = document.getElementById("google-pane-login-view");
    const googleEmailLabel = document.getElementById("modal-google-connected-email");

    const isGoogleOAuth = activeAccountType === "google_oauth" || activeAccountType === "google";
    const isRealImap = activeAccountType === "imap" && activeConnectedEmail && !activeConnectedEmail.includes("demo.executive");

    if (isGoogleOAuth) {
      tabGoogle?.click();
      if (googleConnectedView) googleConnectedView.style.display = "block";
      if (googleLoginView) googleLoginView.style.display = "none";
      if (googleEmailLabel) googleEmailLabel.textContent = `Connected: ${activeConnectedEmail}`;
    } else {
      if (googleConnectedView) googleConnectedView.style.display = "none";
      if (googleLoginView) googleLoginView.style.display = "block";
    }

    if (isRealImap) {
      tabImap?.click();
      if (emailInput) emailInput.value = activeConnectedEmail;
      if (activeConnectedEmail.includes("@gmail.com")) {
        btnProvGoogle?.click();
      } else if (activeConnectedEmail.includes("@outlook.com") || activeConnectedEmail.includes("@office365.com")) {
        btnProvOutlook?.click();
      }
      if (unlinkBtn) unlinkBtn.style.display = "inline-flex";
    } else if (!isGoogleOAuth) {
      tabGoogle?.click();
      if (unlinkBtn) unlinkBtn.style.display = "none";
      if (emailInput && emailInput.value.includes("demo.executive")) {
        emailInput.value = "";
      }
    }
  };

  const closeLinkModal = () => {
    linkModal?.classList.add("hidden");
  };

  openModalBtn?.addEventListener("click", openLinkModal);
  btnTopManage?.addEventListener("click", () => {
    document.getElementById("google-account-popover")?.classList.add("hidden");
    openLinkModal();
  });
  cancelLinkBtn?.addEventListener("click", closeLinkModal);
  cancelDemoBtn?.addEventListener("click", closeLinkModal);
  cancelGoogleBtn?.addEventListener("click", closeLinkModal);
  closeIconBtn?.addEventListener("click", closeLinkModal);

  btnGoogleModalDisconnect?.addEventListener("click", async () => {
    const confirmed = confirm(`Disconnect Google account (${activeConnectedEmail}) and return to offline sandbox?`);
    if (!confirmed) return;
    try {
      const res = await fetch("/api/email/account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "demo.executive@local.ai", account_type: "demo" })
      });
      const data = await res.json();
      if (data.success) {
        closeLinkModal();
        await fetchEmailAccount();
        await syncEmailInbox();
      }
    } catch (e) {
      alert("Error disconnecting account: " + e.message);
    }
  });

  // Close modal when clicking backdrop outside card
  linkModal?.addEventListener("click", (e) => {
    if (e.target === linkModal) closeLinkModal();
  });

  // Disconnect / Unlink Account
  unlinkBtn?.addEventListener("click", async () => {
    const confirmed = confirm(`Disconnect ${activeConnectedEmail || "your email account"} and return to offline sandbox mode?`);
    if (!confirmed) return;

    try {
      const res = await fetch("/api/email/account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "demo.executive@local.ai", account_type: "demo" })
      });
      const data = await res.json();
      if (data.success) {
        closeLinkModal();
        await fetchEmailAccount();
        await syncEmailInbox();
      }
    } catch (e) {
      alert("Error disconnecting account: " + e.message);
    }
  });

  // Link account tabs
  const tabGoogle = document.getElementById("tab-account-google");
  const tabDemo = document.getElementById("tab-account-demo");
  const tabImap = document.getElementById("tab-account-imap");
  const paneGoogle = document.getElementById("pane-account-google");
  const paneDemo = document.getElementById("pane-account-demo");
  const paneImap = document.getElementById("pane-account-imap");

  tabGoogle?.addEventListener("click", () => {
    tabGoogle.classList.add("active");
    tabDemo?.classList.remove("active");
    tabImap?.classList.remove("active");
    paneGoogle?.classList.remove("hidden");
    paneDemo?.classList.add("hidden");
    paneImap?.classList.add("hidden");
  });

  tabDemo?.addEventListener("click", () => {
    tabDemo.classList.add("active");
    tabGoogle?.classList.remove("active");
    tabImap?.classList.remove("active");
    paneDemo?.classList.remove("hidden");
    paneGoogle?.classList.add("hidden");
    paneImap?.classList.add("hidden");
  });

  tabImap?.addEventListener("click", () => {
    tabImap.classList.add("active");
    tabGoogle?.classList.remove("active");
    tabDemo?.classList.remove("active");
    paneImap?.classList.remove("hidden");
    paneGoogle?.classList.add("hidden");
    paneDemo?.classList.add("hidden");
  });

  // Email provider presets
  const btnProvGoogle = document.getElementById("btn-provider-google");
  const btnProvOutlook = document.getElementById("btn-provider-outlook");
  const btnProvCustom = document.getElementById("btn-provider-custom");
  const provNotice = document.getElementById("email-provider-notice");
  const inputImapHost = document.getElementById("link-imap-host");
  const inputImapPort = document.getElementById("link-imap-port");
  const inputSmtpHost = document.getElementById("link-smtp-host");
  const inputSmtpPort = document.getElementById("link-smtp-port");

  const setProviderActive = (activeBtn) => {
    [btnProvGoogle, btnProvOutlook, btnProvCustom].forEach(b => b?.classList.remove("active"));
    activeBtn?.classList.add("active");
  };

  btnProvGoogle?.addEventListener("click", () => {
    setProviderActive(btnProvGoogle);
    if (inputImapHost) inputImapHost.value = "imap.gmail.com";
    if (inputImapPort) inputImapPort.value = "993";
    if (inputSmtpHost) inputSmtpHost.value = "smtp.gmail.com";
    if (inputSmtpPort) inputSmtpPort.value = "587";
    if (provNotice) {
      provNotice.innerHTML = `
        <strong style="color: #2563eb;">Gmail Configuration:</strong> Google requires a <strong>16-character App Password</strong> (not your standard password). Generate one at <a href="https://myaccount.google.com/apppasswords" target="_blank" style="color: #2563eb; text-decoration: underline;">myaccount.google.com/apppasswords</a> with 2-Step Verification turned on.
      `;
    }
  });

  btnProvOutlook?.addEventListener("click", () => {
    setProviderActive(btnProvOutlook);
    if (inputImapHost) inputImapHost.value = "outlook.office365.com";
    if (inputImapPort) inputImapPort.value = "993";
    if (inputSmtpHost) inputSmtpHost.value = "smtp.office365.com";
    if (inputSmtpPort) inputSmtpPort.value = "587";
    if (provNotice) {
      provNotice.innerHTML = `
        <strong style="color: #0284c7;">Microsoft Outlook / 365:</strong> Pre-configured for Microsoft Cloud endpoints (<code>outlook.office365.com:993</code> and <code>smtp.office365.com:587</code>). Enter your account email and App Password.
      `;
    }
  });

  btnProvCustom?.addEventListener("click", () => {
    setProviderActive(btnProvCustom);
    if (inputImapHost) inputImapHost.value = "";
    if (inputImapPort) inputImapPort.value = "993";
    if (inputSmtpHost) inputSmtpHost.value = "";
    if (inputSmtpPort) inputSmtpPort.value = "587";
    if (provNotice) {
      provNotice.innerHTML = `
        <strong style="color: #475569;">Custom IMAP / SMTP:</strong> Enter your mail server's custom IMAP/SMTP hostname, port numbers, and authentication credentials.
      `;
    }
  });

  // Activate Sandbox button
  document.getElementById("btn-activate-sandbox")?.addEventListener("click", async () => {
    try {
      const res = await fetch("/api/email/account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: "demo.executive@local.ai", account_type: "demo" })
      });
      const data = await res.json();
      if (data.success) {
        closeLinkModal();
        await fetchEmailAccount();
        await syncEmailInbox();
      }
    } catch (e) {
      console.error(e);
    }
  });

  // Save IMAP Account button
  document.getElementById("btn-save-link-account")?.addEventListener("click", async () => {
    const email = document.getElementById("link-imap-email")?.value.trim();
    let imap_host = document.getElementById("link-imap-host")?.value.trim();
    const imap_port = parseInt(document.getElementById("link-imap-port")?.value || "993", 10);
    let smtp_host = document.getElementById("link-smtp-host")?.value.trim();
    const smtp_port = parseInt(document.getElementById("link-smtp-port")?.value || "587", 10);
    const password = document.getElementById("link-imap-pass")?.value;

    if (!email || !email.includes("@")) {
      return alert("Please enter a valid email address.");
    }
    if (!password) {
      return alert("Please enter your 16-character Google App Password (or IMAP password).");
    }

    if (!imap_host && email.includes("@gmail.com")) imap_host = "imap.gmail.com";
    if (!smtp_host && email.includes("@gmail.com")) smtp_host = "smtp.gmail.com";

    const saveBtn = document.getElementById("btn-save-link-account");
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = "Connecting & Syncing...";
    }

    try {
      const res = await fetch("/api/email/account", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email,
          account_type: "imap",
          imap_host,
          imap_port,
          smtp_host,
          smtp_port,
          password
        })
      });
      const data = await res.json();
      if (data.success) {
        closeLinkModal();
        await fetchEmailAccount();
        await syncEmailInbox();
      } else {
        alert("Account link error: " + (data.error || "Failed to connect."));
      }
    } catch (e) {
      alert("Error linking account: " + e.message);
    } finally {
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = "Connect & Sync";
      }
    }
  });

  // Sync Mail button
  document.getElementById("btn-sync-emails")?.addEventListener("click", syncEmailInbox);

  // New Compose button
  document.getElementById("btn-new-email-draft")?.addEventListener("click", () => {
    activeEmailId = null;
    document.querySelectorAll(".inbox-card-item.active").forEach(el => el.classList.remove("active"));
    document.getElementById("detail-empty-placeholder")?.classList.add("hidden");
    const activeView = document.getElementById("detail-active-view");
    activeView?.classList.remove("hidden");

    document.getElementById("detail-subject-title").textContent = "New Outbound Message";
    document.getElementById("detail-sender-name").textContent = "Draft Message";
    document.getElementById("detail-sender-email").textContent = "<staging locally>";
    document.getElementById("detail-timestamp").textContent = "Now";
    document.getElementById("detail-body-text").textContent = "Compose your message using the smart draft editor below.";
    document.getElementById("ai-summary-content").textContent = "Executive Summary: Staging new outbound communication.";

    const toInput = document.getElementById("reply-to");
    const subjInput = document.getElementById("reply-subject");
    const bodyInput = document.getElementById("reply-body");
    if (toInput) toInput.value = "";
    if (subjInput) subjInput.value = "";
    if (bodyInput) bodyInput.value = "";
    toInput?.focus();
  });

  // Category Folders Rail
  const railItems = document.querySelectorAll(".rail-item");
  railItems.forEach(item => {
    item.addEventListener("click", () => {
      railItems.forEach(r => r.classList.remove("active"));
      item.classList.add("active");
      activeEmailCategory = item.getAttribute("data-category") || "all";
      fetchEmailInbox();
    });
  });

  // Priority Filter Pills
  const tagPills = document.querySelectorAll(".rail-tag-pill");
  tagPills.forEach(pill => {
    pill.addEventListener("click", () => {
      tagPills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      activeEmailPriority = pill.getAttribute("data-tag") || "all";
      fetchEmailInbox();
    });
  });

  // Search Input with Debounce & Clear
  const searchInput = document.getElementById("email-search-input");
  const clearBtn = document.getElementById("btn-clear-email-search");

  searchInput?.addEventListener("input", () => {
    const query = searchInput.value;
    if (clearBtn) clearBtn.classList.toggle("hidden", !query);

    clearTimeout(emailSearchDebounce);
    emailSearchDebounce = setTimeout(() => {
      fetchEmailInbox(query);
    }, 250);
  });

  clearBtn?.addEventListener("click", () => {
    if (searchInput) searchInput.value = "";
    clearBtn.classList.add("hidden");
    fetchEmailInbox();
  });

  // Tone selector
  const tonePills = document.querySelectorAll(".tone-pill");
  tonePills.forEach(pill => {
    pill.addEventListener("click", () => {
      tonePills.forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      activeReplyTone = pill.getAttribute("data-tone") || "professional";
    });
  });

  // Generate Reply with AI button
  document.getElementById("btn-generate-ai-reply")?.addEventListener("click", () => {
    if (!activeEmailId) {
      return alert("Please select an email message first.");
    }
    generateSmartReply(activeEmailId);
  });

  // Regenerate summary button
  document.getElementById("btn-regenerate-summary")?.addEventListener("click", () => {
    if (activeEmailId) {
      fetchEmailSummary(activeEmailId, true);
    }
  });

  // Quick reply scroll trigger
  document.getElementById("btn-quick-reply-trigger")?.addEventListener("click", () => {
    document.getElementById("ai-reply-card")?.scrollIntoView({ behavior: "smooth" });
    document.getElementById("reply-guidance-input")?.focus();
  });

  // Stage Draft button
  document.getElementById("btn-stage-reply-draft")?.addEventListener("click", stageReplyDraft);

  // Send Reply button
  document.getElementById("btn-send-reply")?.addEventListener("click", sendReplyEmail);

  // Keyboard Shortcuts (j / k / ArrowDown / ArrowUp / r / /)
  document.addEventListener("keydown", (e) => {
    const activeTab = document.querySelector(".view-pane.active");
    if (!activeTab || activeTab.id !== "tab-inbox") return;
    
    // Ignore when focus is inside text fields
    if (["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName)) {
      if (e.key === "Escape") document.activeElement.blur();
      return;
    }

    if (e.key === "/" && !e.ctrlKey && !e.metaKey) {
      e.preventDefault();
      document.getElementById("email-search-input")?.focus();
      return;
    }

    const cards = Array.from(document.querySelectorAll(".inbox-card-item"));
    if (!cards.length) return;
    const currentIndex = cards.findIndex(c => c.dataset.id === activeEmailId);

    if (e.key === "ArrowDown" || e.key === "j") {
      e.preventDefault();
      const nextIdx = Math.min(currentIndex + 1, cards.length - 1);
      if (nextIdx >= 0 && nextIdx < cards.length) {
        selectEmailMessage(cards[nextIdx].dataset.id);
        cards[nextIdx].scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    } else if (e.key === "ArrowUp" || e.key === "k") {
      e.preventDefault();
      const prevIdx = Math.max(currentIndex - 1, 0);
      if (prevIdx >= 0 && prevIdx < cards.length) {
        selectEmailMessage(cards[prevIdx].dataset.id);
        cards[prevIdx].scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    } else if (e.key === "r") {
      e.preventDefault();
      document.getElementById("ai-reply-card")?.scrollIntoView({ behavior: "smooth" });
      document.getElementById("reply-guidance-input")?.focus();
    }
  });
}

async function fetchEmailAccount() {
  const statusLabel = document.getElementById("account-status-text");
  const linkAccountBtn = document.getElementById("btn-open-link-account");
  try {
    const res = await fetch("/api/email/account");
    const data = await res.json();
    if (data.success) {
      activeConnectedEmail = data.email || "";
      activeAccountType = data.account_type || "demo";
      const isGoogleOAuth = activeAccountType === "google_oauth" || activeAccountType === "google";
      const isRealImap = activeAccountType === "imap" && activeConnectedEmail && !activeConnectedEmail.includes("demo.executive");

      if (statusLabel) {
        if (isGoogleOAuth) {
          statusLabel.textContent = `Google: ${data.email}`;
          if (statusLabel.parentElement) {
            statusLabel.parentElement.title = `Connected to ${data.email} via Google Cloud OAuth (Click to manage)`;
          }
        } else if (isRealImap) {
          statusLabel.textContent = `Connected: ${data.email}`;
          if (statusLabel.parentElement) {
            statusLabel.parentElement.title = `Connected to ${data.email} via IMAP (Click to manage)`;
          }
        } else {
          statusLabel.textContent = `Sandbox: demo.executive@local.ai`;
          if (statusLabel.parentElement) {
            statusLabel.parentElement.title = `Offline Sandbox: demo.executive@local.ai (Not connected to Google; click to link live email)`;
          }
        }
      }

      // If a real account is linked, remove/hide the Link Account button option
      if (linkAccountBtn) {
        if (isGoogleOAuth || isRealImap) {
          linkAccountBtn.style.display = "none";
        } else {
          linkAccountBtn.style.display = "inline-flex";
        }
      }

      // Top bar Google button & popover update
      const topGoogleLabel = document.getElementById("top-google-label");
      const topPopoverEmail = document.getElementById("top-popover-email");
      const topPopoverStatus = document.getElementById("top-popover-status");
      const topInitials = document.getElementById("top-user-avatar-initials");
      const btnTopLogin = document.getElementById("btn-top-google-login");
      const btnTopLogout = document.getElementById("btn-top-google-logout");

      if (isGoogleOAuth) {
        const fullEmail = data.email || "";
        const shortName = fullEmail.split("@")[0] || "Google";
        if (topGoogleLabel) topGoogleLabel.textContent = shortName;
        if (topPopoverEmail) topPopoverEmail.textContent = fullEmail;
        if (topPopoverStatus) topPopoverStatus.textContent = "Google OAuth Active";
        if (topInitials) topInitials.textContent = shortName.slice(0, 2).toUpperCase();
        if (btnTopLogin) btnTopLogin.style.display = "none";
        if (btnTopLogout) btnTopLogout.style.display = "block";
      } else {
        if (topGoogleLabel) topGoogleLabel.textContent = "Google";
        if (topPopoverEmail) topPopoverEmail.textContent = "Not connected";
        if (topPopoverStatus) topPopoverStatus.textContent = "Offline Sandbox";
        if (topInitials) topInitials.textContent = "G";
        if (btnTopLogin) btnTopLogin.style.display = "flex";
        if (btnTopLogout) btnTopLogout.style.display = "none";
      }
    }
  } catch (e) {
    if (statusLabel) statusLabel.textContent = "Sandbox: demo.executive@local.ai";
    if (linkAccountBtn) linkAccountBtn.style.display = "inline-flex";
  }
}

async function syncEmailInbox() {
  const tableSyncBtn = document.getElementById("btn-table-sync");
  if (tableSyncBtn) tableSyncBtn.classList.add("spinning");
  try {
    const res = await fetch("/api/email/sync", { method: "POST" });
    const data = await res.json();
    if (data.warning) {
      alert("Mail Sync Notice:\n\n" + data.warning);
    }
    await fetchEmailAccount();
    await fetchEmailInbox();
  } catch (e) {
    console.warn("Sync failed:", e);
  } finally {
    if (tableSyncBtn) tableSyncBtn.classList.remove("spinning");
  }
}

function openEmailDetailView(messageId) {
  activeEmailId = messageId;
  document.getElementById("inbox-list-view")?.classList.add("hidden");
  document.getElementById("inbox-detail-view")?.classList.remove("hidden");
  loadEmailDetails(messageId);
}

function closeEmailDetailView() {
  document.getElementById("inbox-detail-view")?.classList.add("hidden");
  document.getElementById("inbox-list-view")?.classList.remove("hidden");
  fetchEmailInbox();
}

function openEmailComposerDraft() {
  document.getElementById("inbox-list-view")?.classList.add("hidden");
  document.getElementById("inbox-detail-view")?.classList.remove("hidden");

  document.getElementById("detail-subject-title").textContent = "New Message";
  document.getElementById("detail-sender-name").textContent = "Me";
  document.getElementById("detail-sender-email").textContent = "";
  document.getElementById("detail-timestamp").textContent = "Draft";
  document.getElementById("detail-body-text").textContent = "Compose your message using the drafter below.";
  document.getElementById("ai-summary-card")?.classList.add("collapsed");

  const toInput = document.getElementById("reply-to");
  const subjInput = document.getElementById("reply-subject");
  const bodyInput = document.getElementById("reply-body");
  if (toInput) toInput.value = "";
  if (subjInput) subjInput.value = "";
  if (bodyInput) bodyInput.value = "";

  document.getElementById("ai-reply-card")?.scrollIntoView({ behavior: "smooth" });
  toInput?.focus();
}

async function fetchEmailInbox(query = "") {
  const container = document.getElementById("inbox-rows-container");
  if (!container) return;

  try {
    let url = `/api/email/inbox?query=${encodeURIComponent(query)}&category=${encodeURIComponent(activeEmailCategory)}`;
    const res = await fetch(url);
    const data = await res.json();

    let items = data.messages || [];

    // Client-side priority filter if set
    if (activeEmailPriority && activeEmailPriority !== "all") {
      items = items.filter(m => (m.priority || "normal").toLowerCase() === activeEmailPriority.toLowerCase());
    }

    // Calculate category counts
    const totalCount = items.length;
    const unreadCount = items.filter(m => !m.is_read).length;
    const urgentCount = items.filter(m => (m.priority || "").toLowerCase() === "high" || (m.category || "").toLowerCase() === "urgent").length;
    const actionCount = items.filter(m => (m.category || "").toLowerCase() === "action" || (m.priority || "").toLowerCase() === "high").length;

    const badgeAll = document.getElementById("tab-badge-all");
    const badgeUnread = document.getElementById("tab-badge-unread");
    const badgeUrgent = document.getElementById("tab-badge-urgent");
    const badgeAction = document.getElementById("tab-badge-action");
    if (badgeAll) badgeAll.textContent = totalCount;
    if (badgeUnread) badgeUnread.textContent = unreadCount;
    if (badgeUrgent) badgeUrgent.textContent = urgentCount;
    if (badgeAction) badgeAction.textContent = actionCount;

    fetchNotifications();
    fetchEmailIntelligenceStats();

    let displayItems = items;
    if (isThreadedView) {
      const threadMap = new Map();
      items.forEach(msg => {
        const key = normalizeThreadSubject(msg.subject);
        if (!threadMap.has(key)) {
          threadMap.set(key, []);
        }
        threadMap.get(key).push(msg);
      });

      displayItems = [];
      threadMap.forEach((msgs) => {
        msgs.sort((a, b) => new Date(b.received_at) - new Date(a.received_at));
        const leadMsg = { ...msgs[0] };
        leadMsg.threadCount = msgs.length;
        displayItems.push(leadMsg);
      });
    }

    const paginationInfo = document.getElementById("email-pagination-info");
    if (paginationInfo) {
      paginationInfo.textContent = displayItems.length > 0
        ? `1–${displayItems.length} of ${totalCount}`
        : "0 messages";
    }

    if (!displayItems.length) {
      container.innerHTML = "<div class='empty-state'>No matching messages in this view.</div>";
      return;
    }

    container.innerHTML = "";
    displayItems.forEach(msg => {
      const row = document.createElement("div");
      const isUnread = !msg.is_read;
      row.className = `email-row ${isUnread ? "unread" : "read"}`;
      row.dataset.id = msg.id;

      const avatar = getSenderAvatar(msg.sender);
      const cleanSnippetText = cleanSnippet(msg.body_preview || msg.body);
      const relativeTime = formatEmailTime(msg.received_at);

      const catKey = msg.classification_category || msg.category || "work";
      const catLabel = catKey === "review_required" ? "Review" : (catKey.charAt(0).toUpperCase() + catKey.slice(1));
      let badgeHtml = `<span class="row-cat-pill row-cat-${catKey}">${catLabel}</span>`;

      if (msg.priority === "high" || msg.category === "urgent") {
        badgeHtml += `<span class="row-badge row-badge-urgent">Urgent</span>`;
      } else if ((msg.subject || "").toLowerCase().includes("security") || (msg.subject || "").toLowerCase().includes("password")) {
        badgeHtml += `<span class="row-badge row-badge-security">Security</span>`;
      }

      const threadBadgeHtml = msg.threadCount && msg.threadCount > 1
        ? `<span class="row-thread-count">${msg.threadCount}</span>`
        : "";

      row.innerHTML = `
        <div class="row-check-cell">
          <input type="checkbox" class="row-checkbox">
        </div>
        <div class="row-star-cell ${msg.is_starred ? 'starred' : ''}" title="${msg.is_starred ? 'Starred' : 'Star message'}">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="${msg.is_starred ? '#eab308' : 'none'}" stroke="${msg.is_starred ? '#eab308' : 'currentColor'}" stroke-width="2">
            <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"></polygon>
          </svg>
        </div>
        <div class="row-sender-cell">
          <span class="row-sender-name" title="${escapeHtml(msg.sender)}">${escapeHtml(avatar.cleanName)}</span>
          ${threadBadgeHtml}
        </div>
        <div class="row-content-cell">
          <span class="row-subject">${escapeHtml(msg.subject || "(No Subject)")}</span>
          <span class="row-snippet"> - ${escapeHtml(cleanSnippetText)}</span>
        </div>
        ${badgeHtml}
        <div class="row-actions-cell">
          <button class="row-action-btn btn-row-read-toggle" title="${isUnread ? 'Mark read' : 'Mark unread'}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle cx="12" cy="12" r="10"></circle>
            </svg>
          </button>
          <button class="row-action-btn btn-row-delete" title="Delete">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <polyline points="3 6 5 6 21 6"></polyline>
              <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
            </svg>
          </button>
        </div>
        <div class="row-date-cell">${relativeTime}</div>
      `;

      // Clicking row opens focused detail view
      row.addEventListener("click", () => {
        openEmailDetailView(msg.id);
      });

      // Internal row action controls
      row.querySelector(".row-checkbox")?.addEventListener("click", (e) => e.stopPropagation());
      row.querySelector(".row-star-cell")?.addEventListener("click", async (e) => {
        e.stopPropagation();
        const starEl = e.currentTarget;
        try {
          const res = await fetch("/api/email/star", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message_id: msg.id })
          });
          const data = await res.json();
          if (data.success) {
            const isNowStarred = data.is_starred;
            starEl.classList.toggle("starred", isNowStarred);
            const svg = starEl.querySelector("svg");
            if (svg) {
              svg.setAttribute("fill", isNowStarred ? "#eab308" : "none");
              svg.setAttribute("stroke", isNowStarred ? "#eab308" : "currentColor");
            }
          }
        } catch (err) {
          console.warn("Error toggling star:", err);
        }
      });
      row.querySelector(".btn-row-read-toggle")?.addEventListener("click", (e) => {
        e.stopPropagation();
        const unreadNow = row.classList.toggle("unread");
        row.classList.toggle("read", !unreadNow);
      });
      row.querySelector(".btn-row-delete")?.addEventListener("click", (e) => {
        e.stopPropagation();
        row.remove();
      });

      container.appendChild(row);
    });
  } catch (e) {
    container.innerHTML = `<div class='empty-state'>Failed to load inbox: ${e.message}</div>`;
  }
}

async function loadEmailDetails(messageId) {
  activeEmailId = messageId;

  try {
    const res = await fetch(`/api/email/read?id=${encodeURIComponent(messageId)}`);
    const data = await res.json();
    if (!data.success || !data.message) return;

    fetchNotifications();

    const msg = data.message;
    const avatar = getSenderAvatar(msg.sender);

    document.getElementById("detail-subject-title").textContent = msg.subject || "(No Subject)";
    document.getElementById("detail-sender-name").textContent = avatar.cleanName;
    document.getElementById("detail-sender-email").textContent = avatar.rawEmail ? `<${avatar.rawEmail}>` : "";

    // Avatar badge
    const avatarBadge = document.getElementById("detail-sender-avatar");
    if (avatarBadge) {
      avatarBadge.textContent = avatar.char;
      avatarBadge.style.background = avatar.bg;
      avatarBadge.style.color = avatar.text;
    }

    // Formatted time
    const dateFormatted = msg.received_at ? new Date(msg.received_at).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : "";
    document.getElementById("detail-timestamp").textContent = dateFormatted;

    // Email Intelligence Category & Sender Metadata
    const catSelect = document.getElementById("detail-category-select");
    if (catSelect) {
      catSelect.value = msg.classification_category || msg.category || "work";
    }

    const confPill = document.getElementById("detail-confidence-pill");
    if (confPill) {
      const conf = Math.round((msg.classification_confidence !== undefined ? msg.classification_confidence : 0.95) * 100);
      confPill.textContent = `${conf}% Conf`;
    }

    const reviewFlag = document.getElementById("detail-review-flag");
    if (reviewFlag) {
      reviewFlag.classList.toggle("hidden", !msg.is_flagged_review && (msg.classification_category !== "review_required"));
    }

    const repLabel = document.getElementById("detail-sender-rep-label");
    if (repLabel) {
      const rep = msg.sender_reputation || "neutral";
      repLabel.textContent = `Sender: ${rep.charAt(0).toUpperCase() + rep.slice(1)}`;
      repLabel.className = `sender-rep-label ${rep}`;
    }

    // Body with clean link & image parsing
    const bodyContainer = document.getElementById("detail-body-text");
    if (bodyContainer) {
      bodyContainer.innerHTML = formatEmailBody(msg.body);
    }

    // Populate dynamic instant reply suggestions directly under body
    const chipsContainer = document.getElementById("inline-replies-chips");
    if (chipsContainer) {
      chipsContainer.innerHTML = "";
      let suggestions = [];
      const lowerSubj = (msg.subject || "").toLowerCase();
      const lowerBody = (msg.body || "").toLowerCase();

      if (lowerSubj.includes("hacked") || lowerBody.includes("llm") || lowerSubj.includes("security")) {
        suggestions = [
          "I am the local AI agent running securely on this machine. How can I assist you?",
          "Challenge received. Local LLM is active and ready for your instructions.",
          "Received. What task or test would you like to run?",
          "Acknowledged. Workstation security normal."
        ];
      } else if (msg.priority === "high" || msg.category === "urgent") {
        suggestions = [
          "Acknowledged. I am looking into this urgently.",
          "Received. I will complete this and update you shortly.",
          "Could you provide additional specifications?",
          "Unable to fulfill this immediately due to scheduling."
        ];
      } else {
        suggestions = [
          "Thanks for the update, noted.",
          "I will review this and get back to you shortly.",
          "Could you send over additional details?",
          "Acknowledged and confirmed."
        ];
      }

      suggestions.forEach(text => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "inline-reply-pill";
        btn.innerHTML = `<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:3px;"><polyline points="9 17 4 12 9 7"></polyline><path d="M20 18v-2a4 4 0 0 0-4-4H4"></path></svg> <span>${escapeHtml(text)}</span>`;
        btn.addEventListener("click", () => {
          const replyArea = document.getElementById("reply-body");
          if (replyArea) {
            replyArea.value = text;
            document.getElementById("ai-reply-card")?.scrollIntoView({ behavior: "smooth" });
            replyArea.focus();
          }
        });
        chipsContainer.appendChild(btn);
      });

      // Add custom reply shortcut pill (no emojis)
      const customPill = document.createElement("button");
      customPill.type = "button";
      customPill.className = "inline-reply-pill pill-custom";
      customPill.innerHTML = `<span>Custom Reply</span>`;
      customPill.addEventListener("click", () => {
        document.getElementById("ai-reply-card")?.scrollIntoView({ behavior: "smooth" });
        document.getElementById("reply-body")?.focus();
      });
      chipsContainer.appendChild(customPill);
    }

    // Original formatted HTML view in isolated sandbox frame
    const htmlFrame = document.getElementById("email-html-frame");
    if (htmlFrame) {
      const htmlContent = msg.raw_html || `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; padding: 20px; line-height: 1.6; color: #1e293b; background: #fff; }
            p { margin-bottom: 1em; }
          </style>
        </head>
        <body>
          ${formatEmailBody(msg.body)}
        </body>
        </html>
      `;
      htmlFrame.srcdoc = htmlContent;
    }

    // Respect user's selected view mode (Clean Text vs Formatted View)
    if (currentEmailViewMode === "html") {
      document.getElementById("detail-body-html")?.classList.remove("hidden");
      document.getElementById("detail-body-text")?.classList.add("hidden");
    } else {
      document.getElementById("detail-body-text")?.classList.remove("hidden");
      document.getElementById("detail-body-html")?.classList.add("hidden");
    }

    // Pre-fill composer
    const replyToInput = document.getElementById("reply-to");
    const replySubjectInput = document.getElementById("reply-subject");
    if (replyToInput) replyToInput.value = avatar.rawEmail || msg.sender;
    if (replySubjectInput) {
      replySubjectInput.value = msg.subject && msg.subject.toLowerCase().startsWith("re:") ? msg.subject : `Re: ${msg.subject || ""}`;
    }

    // Context-aware evaluation of briefing action buttons
    activeEmailMsg = msg;
    updateBriefingActionButtons(msg, msg.summary || "");

    // Load AI Executive Summary
    fetchEmailSummary(messageId, false, msg.summary);

    // Load Conversation Context (Thread History, Prior Sender Interactions, Commitments)
    loadEmailConversationContext(messageId);
  } catch (e) {
    console.error("Failed to load message:", e);
  }
}

async function fetchEmailIntelligenceStats() {
  try {
    const res = await fetch("/api/email/intelligence/stats");
    const data = await res.json();
    if (data.success && data.stats) {
      const s = data.stats;
      const bAll = document.getElementById("tab-badge-all");
      const bWork = document.getElementById("tab-badge-work");
      const bCollege = document.getElementById("tab-badge-college");
      const bPersonal = document.getElementById("tab-badge-personal");
      const bPromotions = document.getElementById("tab-badge-promotions");
      const bSpam = document.getElementById("tab-badge-spam");
      const bUnnecessary = document.getElementById("tab-badge-unnecessary");
      const bReview = document.getElementById("tab-badge-review");

      if (bAll) bAll.textContent = s.total || 0;
      if (bWork) bWork.textContent = s.work || 0;
      if (bCollege) bCollege.textContent = s.college || 0;
      if (bPersonal) bPersonal.textContent = s.personal || 0;
      if (bPromotions) bPromotions.textContent = s.promotions || 0;
      if (bSpam) bSpam.textContent = s.spam || 0;
      if (bUnnecessary) bUnnecessary.textContent = s.unnecessary || 0;
      if (bReview) bReview.textContent = s.review_required || 0;
    }
  } catch (err) {
    console.warn("Failed to fetch intelligence stats:", err);
  }
}

async function openBulkCleanupModal() {
  const modal = document.getElementById("modal-bulk-cleanup");
  const tbody = document.getElementById("cleanup-table-body");
  const countDisp = document.getElementById("cleanup-count-display");
  const confirmBtn = document.getElementById("btn-confirm-cleanup");
  const selectAll = document.getElementById("cleanup-select-all-check");
  const statusMsg = document.getElementById("cleanup-status-message");

  if (!modal || !tbody) return;
  modal.classList.remove("hidden");
  if (statusMsg) statusMsg.classList.add("hidden");
  if (selectAll) selectAll.checked = false;
  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Move Selected to Trash";
  }
  if (countDisp) countDisp.textContent = "Selected: 0 emails";
  tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:18px; color:#64748b;">Loading cleanup candidates...</td></tr>`;

  try {
    const res = await fetch("/api/email/cleanup/candidates");
    const data = await res.json();
    const candidates = data.candidates || [];

    if (!candidates.length) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:22px; color:#059669; font-weight:600;">✓ Inbox is clean! No unnecessary or promotional emails found.</td></tr>`;
      return;
    }

    tbody.innerHTML = "";
    candidates.forEach(m => {
      const tr = document.createElement("tr");
      tr.dataset.id = m.id;
      const avatar = getSenderAvatar(m.sender);
      const dateStr = formatEmailTime(m.received_at);
      const catKey = m.classification_category || m.category;
      const catClass = catKey === "promotions" ? "row-cat-promotions" : "row-cat-unnecessary";
      const catName = catKey === "promotions" ? "Promotion" : "Unnecessary";
      const confPct = Math.round((m.classification_confidence || 0.9) * 100);
      const reasonText = m.classification_reason || "Identified promotional/unnecessary marketing pattern";

      tr.innerHTML = `
        <td><input type="checkbox" class="cleanup-row-check" data-id="${m.id}"></td>
        <td><strong>${escapeHtml(avatar.cleanName)}</strong></td>
        <td>${escapeHtml(m.subject || "(No Subject)")}</td>
        <td><span class="row-cat-pill ${catClass}">${catName}</span></td>
        <td><span class="confidence-badge" style="font-size:11px; padding:2px 6px; border-radius:4px; background:#f1f5f9; font-weight:600; color:#334155;">${confPct}%</span></td>
        <td style="font-size:11.5px; color:#475569; max-width:200px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${escapeHtml(reasonText)}">${escapeHtml(reasonText)}</td>
        <td style="color:#64748b; white-space:nowrap;">${dateStr}</td>
      `;
      tbody.appendChild(tr);
    });

    const updateSelectedCount = () => {
      const checkedBoxes = Array.from(tbody.querySelectorAll(".cleanup-row-check:checked"));
      const count = checkedBoxes.length;
      if (countDisp) countDisp.textContent = `Selected: ${count} of ${candidates.length} emails`;
      if (confirmBtn) {
        confirmBtn.disabled = count === 0;
        confirmBtn.textContent = count > 0 ? `Move ${count} Selected to Trash` : "Move Selected to Trash";
      }
      if (selectAll) {
        selectAll.checked = count === candidates.length && candidates.length > 0;
      }
    };

    tbody.querySelectorAll(".cleanup-row-check").forEach(cb => {
      cb.addEventListener("change", updateSelectedCount);
    });

    if (selectAll) {
      selectAll.onchange = (e) => {
        const isChecked = e.target.checked;
        tbody.querySelectorAll(".cleanup-row-check").forEach(cb => { cb.checked = isChecked; });
        updateSelectedCount();
      };
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:#dc2626; padding:18px;">Error loading cleanup candidates: ${err.message}</td></tr>`;
  }
}

async function executeBulkCleanup() {
  const tbody = document.getElementById("cleanup-table-body");
  const confirmBtn = document.getElementById("btn-confirm-cleanup");
  const statusMsg = document.getElementById("cleanup-status-message");
  const selectedBoxes = Array.from(tbody?.querySelectorAll(".cleanup-row-check:checked") || []);
  const ids = selectedBoxes.map(b => b.dataset.id).filter(Boolean);

  if (!ids.length) return alert("Please select at least one email to clean.");

  const confirmed = confirm(`Are you sure you want to move ${ids.length} unnecessary/promotional email(s) to Trash?\n\nThis operation is safely reversible from the email Trash folder and is recorded in the security audit trail.`);
  if (!confirmed) return;

  if (confirmBtn) {
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Moving to Trash...";
  }

  try {
    const res = await fetch("/api/email/cleanup/execute", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_ids: ids, confirm: true })
    });
    const data = await res.json();
    if (data.success) {
      if (statusMsg) {
        statusMsg.className = "cleanup-status-message success";
        statusMsg.textContent = `Success: Moved ${data.deleted_count || ids.length} email(s) to Trash with audit logging.`;
        statusMsg.classList.remove("hidden");
      }
      showSystemToast(`Cleaned ${data.deleted_count || ids.length} unnecessary emails.`);
      setTimeout(() => {
        document.getElementById("modal-bulk-cleanup")?.classList.add("hidden");
      }, 1200);
      await fetchEmailIntelligenceStats();
      await fetchEmailInbox();
    } else {
      if (statusMsg) {
        statusMsg.className = "cleanup-status-message error";
        statusMsg.textContent = `Cleanup error: ${data.error || "Operation failed"}. Failed IDs: ${(data.failed_ids || []).join(", ")}`;
        statusMsg.classList.remove("hidden");
      }
    }
  } catch (err) {
    alert("Bulk cleanup error: " + err.message);
  } finally {
    if (confirmBtn) {
      confirmBtn.disabled = false;
      confirmBtn.textContent = "Move Selected to Trash";
    }
  }
}

async function loadEmailConversationContext(messageId) {
  const contextBody = document.getElementById("email-context-content");
  const threadBadge = document.getElementById("context-thread-badge");
  if (!contextBody) return;

  contextBody.innerHTML = `<div class="context-loading">Analyzing thread history and past interactions with sender...</div>`;

  try {
    const res = await fetch(`/api/email/context?id=${encodeURIComponent(messageId)}`);
    const data = await res.json();
    if (!data.success) {
      contextBody.innerHTML = `<div style="color:#64748b; padding:8px;">No prior conversation context found for this sender.</div>`;
      return;
    }

    if (threadBadge) {
      threadBadge.textContent = `${data.thread_message_count || 1} Message(s) in Thread`;
    }

    // 1. Thread Chronological Turns ("Who said what")
    let turnsHtml = "";
    const turns = data.chronological_turns && data.chronological_turns.length > 0 
      ? data.chronological_turns 
      : (data.thread_messages || []).map((t, idx) => ({
          speaker: (t.sender || "").split("<")[0].trim() || "Participant",
          date: formatEmailTime(t.received_at),
          text: cleanSnippet(t.body_snippet || t.body || "").slice(0, 140) + "..."
        }));

    if (turns.length > 0) {
      turnsHtml = `
        <div class="context-block" style="grid-column: 1 / -1;">
          <div class="context-block-title" style="display:flex; justify-content:space-between; align-items:center;">
            <span>Chronological Conversation Sequence (${turns.length})</span>
            <span style="font-size:11px; font-weight:normal; color:#64748b;">Chronological order</span>
          </div>
          <div style="display:flex; flex-direction:column; gap:6px; max-height:160px; overflow-y:auto; padding-right:4px;">
            ${turns.map((t, idx) => `
              <div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:6px 10px; font-size:11.5px;">
                <div style="display:flex; justify-content:space-between; margin-bottom:2px;">
                  <strong style="color:#0f172a;">${escapeHtml(t.speaker || "Participant")}</strong>
                  <span style="color:#64748b; font-size:10.5px;">${t.date ? escapeHtml(t.date) : `#${idx+1}`}</span>
                </div>
                <div style="color:#334155; line-height:1.4;">${escapeHtml(t.text || "")}</div>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    // 2. Confirmed Commitments vs. Suggestions & Questions
    let commitmentsHtml = "";
    const confirmed = data.confirmed_commitments || data.commitments || [];
    const suggestions = data.suggestions || [];
    const questions = data.pending_questions || [];

    if (confirmed.length > 0 || suggestions.length > 0 || questions.length > 0) {
      commitmentsHtml = `
        <div class="context-block">
          <div class="context-block-title">Commitments & Open Items</div>
          <div style="display:flex; flex-direction:column; gap:6px; font-size:11.5px;">
            ${confirmed.map(c => `
              <div style="display:flex; align-items:flex-start; gap:6px;">
                <span style="color:#16a34a; font-weight:700;">✓</span>
                <div><span style="font-weight:600; color:#15803d;">[Confirmed Commitment]</span> ${escapeHtml(c)}</div>
              </div>
            `).join("")}
            ${suggestions.map(s => `
              <div style="display:flex; align-items:flex-start; gap:6px;">
                <span style="color:#d97706; font-weight:700;">•</span>
                <div><span style="font-weight:600; color:#b45309;">[Suggestion/Idea]</span> ${escapeHtml(s)}</div>
              </div>
            `).join("")}
            ${questions.map(q => `
              <div style="display:flex; align-items:flex-start; gap:6px;">
                <span style="color:#2563eb; font-weight:700;">?</span>
                <div><span style="font-weight:600; color:#1d4ed8;">[Pending Question]</span> ${escapeHtml(q)}</div>
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    // 3. Persistent SQLite Email Memory
    let memoryHtml = "";
    const memories = data.memories || [];
    if (memories.length > 0) {
      memoryHtml = `
        <div class="context-block">
          <div class="context-block-title">Persistent Email Memory (${memories.length})</div>
          <div style="display:flex; flex-direction:column; gap:6px; font-size:11.5px;">
            ${memories.map(m => `
              <div style="background:#f1f5f9; padding:6px 8px; border-radius:4px; border-left:3px solid #2563eb;">
                <div style="display:flex; justify-content:space-between; align-items:center;">
                  <strong style="color:#1e293b; text-transform:capitalize;">${escapeHtml(m.key_topic || m.category)}</strong>
                  <span style="font-size:10px; padding:1px 5px; border-radius:3px; background:${m.status === 'completed' ? '#dcfce7; color:#15803d;' : '#fef3c7; color:#b45309;'} font-weight:600;">${escapeHtml(m.status || 'pending')}</span>
                </div>
                <div style="color:#334155; margin-top:2px;">${escapeHtml(m.content)}</div>
                ${m.due_date ? `<div style="font-size:10.5px; color:#64748b; margin-top:2px;">Due: ${escapeHtml(m.due_date)}</div>` : ''}
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    // 4. Decisions & Deadlines
    let decisionsHtml = "";
    const decisions = data.decisions || [];
    const deadlines = data.deadlines || [];
    if (decisions.length > 0 || deadlines.length > 0) {
      decisionsHtml = `
        <div class="context-block">
          <div class="context-block-title">Decisions & Deadlines</div>
          <div style="display:flex; flex-direction:column; gap:4px; font-size:11.5px;">
            ${decisions.map(d => `<div style="color:#0f172a;"><span style="color:#059669; font-weight:700;">★</span> <strong>Decision:</strong> ${escapeHtml(d)}</div>`).join("")}
            ${deadlines.map(dl => `<div style="color:#b91c1c;"><span style="font-weight:700;">⏰</span> <strong>Deadline:</strong> ${escapeHtml(dl)}</div>`).join("")}
          </div>
        </div>
      `;
    }

    // 5. Prior Sender Communications
    let senderHistoryHtml = "";
    if (data.sender_history && data.sender_history.length > 0) {
      senderHistoryHtml = `
        <div class="context-block">
          <div class="context-block-title">Prior Communications (${data.sender_history.length})</div>
          <div style="font-size:11.5px; max-height:100px; overflow-y:auto;">
            ${data.sender_history.map(s => `
              <div style="margin-bottom:4px;">
                <span style="color:#2563eb;">•</span> <strong>${escapeHtml(s.subject)}</strong> (${formatEmailTime(s.received_at)})
              </div>
            `).join("")}
          </div>
        </div>
      `;
    }

    contextBody.innerHTML = `
      <div class="context-grid">
        ${turnsHtml}
        ${commitmentsHtml}
        ${memoryHtml}
        ${decisionsHtml}
        ${senderHistoryHtml || `<div class="context-block"><div class="context-block-title">Sender History</div><div style="color:#64748b; font-size:11.5px;">First interaction recorded in this mailbox.</div></div>`}
      </div>
    `;
  } catch (err) {
    contextBody.innerHTML = `<div style="color:#dc2626; padding:8px;">Failed to load context: ${err.message}</div>`;
  }
}

async function generateContextAwareReply(messageId, replyType) {
  const replyBodyArea = document.getElementById("reply-body");
  const replySubjInput = document.getElementById("reply-subject");
  const replyToInput = document.getElementById("reply-to");
  const guidanceInput = document.getElementById("reply-guidance-input");
  const userGuidance = guidanceInput ? guidanceInput.value.trim() : "";

  // Set active button state
  document.querySelectorAll(".btn-context-reply").forEach(btn => {
    btn.classList.toggle("active", btn.getAttribute("data-reply-type") === replyType);
  });

  const activeBtn = document.querySelector(`.btn-context-reply[data-reply-type="${replyType}"]`);
  const origText = activeBtn ? activeBtn.innerHTML : "";
  if (activeBtn) {
    activeBtn.disabled = true;
    activeBtn.innerHTML = `<span>Synthesizing Context...</span>`;
  }

  try {
    const res = await fetch("/api/email/context_reply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message_id: messageId,
        reply_type: replyType,
        user_guidance: userGuidance
      })
    });
    const data = await res.json();
    if (data.success && data.body) {
      if (replyBodyArea) replyBodyArea.value = data.body;
      if (replySubjInput && data.subject) replySubjInput.value = data.subject;
      if (replyToInput && data.to) replyToInput.value = data.to;
      showSystemToast(`Context reply drafted (${replyType.replace('_', ' ')}). Please review before sending.`);
      document.getElementById("ai-reply-card")?.scrollIntoView({ behavior: "smooth" });
      replyBodyArea?.focus();
    } else {
      alert("Drafting error: " + (data.error || "Could not generate reply"));
    }
  } catch (err) {
    alert("Reply generation failed: " + err.message);
  } finally {
    if (activeBtn) {
      activeBtn.disabled = false;
      activeBtn.innerHTML = origText;
    }
  }
}

async function fetchEmailSummary(messageId, force = false, existingSummary = null) {
  const container = document.getElementById("ai-summary-content");
  if (!container) return;

  if (existingSummary && !force) {
    container.innerHTML = formatBentoSummary(existingSummary);
    updateBriefingActionButtons(activeEmailMsg, existingSummary);
    return;
  }

  container.innerHTML = `<span class="summary-loading">Synthesizing executive briefing with local model...</span>`;

  try {
    const res = await fetch("/api/email/summarize", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message_id: messageId })
    });
    const data = await res.json();
    if (data.success && data.summary) {
      container.innerHTML = formatBentoSummary(data.summary);
      if (activeEmailMsg) activeEmailMsg.summary = data.summary;
      updateBriefingActionButtons(activeEmailMsg, data.summary);
    } else {
      container.textContent = "Summary generation unavailable for this message.";
      updateBriefingActionButtons(activeEmailMsg, "");
    }
  } catch (e) {
    container.textContent = "Executive Summary: Actionable communication requiring review.";
    updateBriefingActionButtons(activeEmailMsg, "");
  }
}

async function generateSmartReply(messageId) {
  const btn = document.getElementById("btn-generate-ai-reply");
  const notes = document.getElementById("reply-guidance-input")?.value.trim() || "";
  const replyBodyArea = document.getElementById("reply-body");

  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span>Drafting with AI...</span>`;
  }

  try {
    const res = await fetch("/api/email/generate_reply", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message_id: messageId,
        tone: activeReplyTone,
        user_notes: notes
      })
    });
    const data = await res.json();
    if (data.success && data.body) {
      if (replyBodyArea) replyBodyArea.value = data.body;
      if (data.to && document.getElementById("reply-to")) document.getElementById("reply-to").value = data.to;
      if (data.subject && document.getElementById("reply-subject")) document.getElementById("reply-subject").value = data.subject;
      replyBodyArea?.focus();
    } else {
      alert("AI Reply drafting error: " + (data.error || "Unable to synthesize response"));
    }
  } catch (e) {
    alert("Error generating reply: " + e.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <path d="M12 2L14.4 9.6L22 12L14.4 14.4L12 22L9.6 14.4L2 12L9.6 9.6L12 2Z"></path>
        </svg>
        <span>Draft Reply</span>
      `;
    }
  }
}

async function stageReplyDraft() {
  const to = document.getElementById("reply-to")?.value.trim();
  const subject = document.getElementById("reply-subject")?.value.trim();
  const body = document.getElementById("reply-body")?.value.trim();

  if (!to || !subject || !body) {
    return alert("Please ensure Recipient, Subject, and Body are filled.");
  }

  try {
    const res = await fetch("/api/email/draft", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to, subject, body })
    });
    const data = await res.json();
    if (data.success) {
      alert(`Draft staged locally (Draft ID: #${data.draft_id}). Saved without external dispatch.`);
    } else {
      alert("Draft error: " + (data.error || "Failed to save draft."));
    }
  } catch (e) {
    alert("Error saving draft: " + e.message);
  }
}

async function sendReplyEmail() {
  const to = document.getElementById("reply-to")?.value.trim();
  const subject = document.getElementById("reply-subject")?.value.trim();
  const body = document.getElementById("reply-body")?.value.trim();

  if (!to || !subject || !body) {
    return alert("Please ensure Recipient, Subject, and Body are filled.");
  }

  const confirmed = confirm(`Confirm dispatch of outbound email to ${to}?\nSubject: ${subject}\n\nThis is a HIGH RISK side-effect action.`);
  if (!confirmed) return;

  try {
    const res = await fetch("/api/email/send", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ to, subject, body })
    });
    const data = await res.json();
    if (data.success) {
      alert(`Outbound message successfully dispatched to ${to} and recorded in audit log.`);
      if (document.getElementById("reply-body")) document.getElementById("reply-body").value = "";
    } else {
      alert("Send error: " + (data.error || "Delivery failed."));
    }
  } catch (e) {
    alert("Error sending email: " + e.message);
  }
}

let quickSendTimer = null;
let pendingQuickPayload = null;

function dispatchQuickReplyWithUndo(payload) {
  pendingQuickPayload = payload;
  let toast = document.getElementById("quick-send-undo-toast");
  if (!toast) {
    toast = document.createElement("div");
    toast.id = "quick-send-undo-toast";
    toast.className = "quick-send-toast";
    document.body.appendChild(toast);
  }

  let countdown = 5;
  toast.innerHTML = `
    <span>Sending to <strong>${escapeHtml(payload.to)}</strong> in <strong id="quick-undo-sec">${countdown}</strong>s...</span>
    <button type="button" id="btn-abort-quick-send">Undo</button>
  `;
  toast.style.display = "flex";

  const ticker = setInterval(() => {
    countdown -= 1;
    const secEl = document.getElementById("quick-undo-sec");
    if (secEl) secEl.textContent = countdown;
    if (countdown <= 0) clearInterval(ticker);
  }, 1000);

  document.getElementById("btn-abort-quick-send")?.addEventListener("click", () => {
    if (quickSendTimer) clearTimeout(quickSendTimer);
    clearInterval(ticker);
    pendingQuickPayload = null;
    toast.style.display = "none";
    showSystemToast("Reply dispatch cancelled.");
  });

  if (quickSendTimer) clearTimeout(quickSendTimer);
  quickSendTimer = setTimeout(async () => {
    clearInterval(ticker);
    toast.style.display = "none";
    if (!pendingQuickPayload) return;

    try {
      const res = await fetch("/api/email/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(pendingQuickPayload)
      });
      const data = await res.json();
      if (data.success) {
        showSystemToast(`Reply sent successfully to ${pendingQuickPayload.to}`);
        const replyArea = document.getElementById("reply-body");
        if (replyArea) replyArea.value = "";
      } else {
        alert(`Failed to send reply: ${data.error || "Unknown error"}`);
      }
    } catch (e) {
      alert(`Send error: ${e.message}`);
    } finally {
      pendingQuickPayload = null;
    }
  }, 5000);
}

// ----------------------------------------------------------------------------
// Multi-Calendar Executive Engine (Row-Based Agenda & Quick Booking)
// ----------------------------------------------------------------------------
let cachedCalendarEvents = [];
let activeCalendarFilter = "all";
let calendarSearchQuery = "";

function formatCalendarEventDateTime(isoStr) {
  if (!isoStr) return { month: "CAL", day: "--", time: "--", isToday: false, isTomorrow: false, isPast: false, relText: "" };
  try {
    const d = new Date(isoStr);
    if (isNaN(d.getTime())) {
      return { month: "CAL", day: "--", time: isoStr.replace("T", " "), isToday: false, isTomorrow: false, isPast: false, relText: isoStr };
    }
    const month = d.toLocaleDateString("en-US", { month: "short" }).toUpperCase();
    const day = String(d.getDate()).padStart(2, "0");
    const time = d.toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });

    const now = new Date();
    const isToday = d.toDateString() === now.toDateString();
    const tomorrow = new Date(now);
    tomorrow.setDate(now.getDate() + 1);
    const isTomorrow = d.toDateString() === tomorrow.toDateString();
    const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const isPast = d < todayMidnight;

    let relText = d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
    if (isToday) relText = "Today";
    else if (isTomorrow) relText = "Tomorrow";
    else if (isPast) relText = "Past";

    return { month, day, time, isToday, isTomorrow, isPast, relText };
  } catch (e) {
    return { month: "CAL", day: "--", time: isoStr, isToday: false, isTomorrow: false, isPast: false, relText: "" };
  }
}

function renderCalendarEventsList() {
  const container = document.getElementById("calendar-events-container");
  const countBadge = document.getElementById("cal-total-count");
  if (!container) return;

  if (countBadge) {
    countBadge.textContent = `${cachedCalendarEvents.length} Event${cachedCalendarEvents.length !== 1 ? "s" : ""}`;
  }

  let filtered = [...cachedCalendarEvents];

  // Apply search query
  if (calendarSearchQuery) {
    const q = calendarSearchQuery.toLowerCase();
    filtered = filtered.filter(ev =>
      (ev.title || "").toLowerCase().includes(q) ||
      (ev.description || "").toLowerCase().includes(q) ||
      (ev.start_time || "").toLowerCase().includes(q)
    );
  }

  // Apply tab filter
  const now = new Date();
  const todayStr = now.toDateString();
  const todayMidnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());

  if (activeCalendarFilter === "today") {
    filtered = filtered.filter(ev => {
      const d = new Date(ev.start_time);
      return !isNaN(d.getTime()) && d.toDateString() === todayStr;
    });
  } else if (activeCalendarFilter === "upcoming") {
    filtered = filtered.filter(ev => {
      const d = new Date(ev.start_time);
      return !isNaN(d.getTime()) && d >= todayMidnight;
    });
  }

  if (!filtered.length) {
    const emptyMsg = calendarSearchQuery
      ? `No events matching "${calendarSearchQuery}".`
      : activeCalendarFilter === "today"
      ? "No events scheduled for today."
      : "No upcoming calendar events found.";
    container.innerHTML = `
      <div class="empty-state" style="padding: 40px 20px; text-align: center;">
        <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5" style="margin-bottom: 8px;">
          <rect x="3" y="4" width="18" height="18" rx="2" ry="2"></rect>
          <line x1="16" y1="2" x2="16" y2="6"></line>
          <line x1="8" y1="2" x2="8" y2="6"></line>
          <line x1="3" y1="10" x2="21" y2="10"></line>
        </svg>
        <p style="color: #64748b; font-size: 13px;">${emptyMsg}</p>
      </div>
    `;
    return;
  }

  container.innerHTML = "";
  filtered.forEach(ev => {
    const startMeta = formatCalendarEventDateTime(ev.start_time);
    const endMeta = formatCalendarEventDateTime(ev.end_time);

    let relBadgeClass = "cal-rel-upcoming";
    if (startMeta.isToday) relBadgeClass = "cal-rel-today";
    else if (startMeta.isTomorrow) relBadgeClass = "cal-rel-tomorrow";
    else if (startMeta.isPast) relBadgeClass = "cal-rel-past";

    const row = document.createElement("div");
    row.className = "cal-event-row";
    row.dataset.eventId = ev.id;

    row.innerHTML = `
      <div class="cal-event-date-chip">
        <span class="cal-date-month">${startMeta.month}</span>
        <span class="cal-date-day">${startMeta.day}</span>
      </div>
      <div class="cal-event-time-col">
        <div class="cal-event-time-text">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="10"></circle>
            <polyline points="12 6 12 12 16 14"></polyline>
          </svg>
          <span>${startMeta.time} – ${endMeta.time}</span>
        </div>
        <span class="cal-event-rel-badge ${relBadgeClass}">${startMeta.relText}</span>
      </div>
      <div class="cal-event-info-col">
        <div class="cal-event-title" title="${ev.title}">${ev.title}</div>
        ${ev.description ? `<div class="cal-event-desc" title="${ev.description}">${ev.description}</div>` : ""}
      </div>
      <span class="cal-event-status-chip">Confirmed</span>
      <button class="cal-event-del-btn" title="Delete event" data-event-id="${ev.id}">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
          <polyline points="3 6 5 6 21 6"></polyline>
          <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
        </svg>
      </button>
    `;

    row.querySelector(".cal-event-del-btn")?.addEventListener("click", async (e) => {
      e.stopPropagation();
      await deleteCalendarEvent(ev.id, ev.title);
    });

    container.appendChild(row);
  });
}

async function deleteCalendarEvent(eventId, eventTitle) {
  if (!confirm(`Are you sure you want to delete "${eventTitle}"?`)) return;
  try {
    const res = await fetch(`/api/calendar/events/${eventId}`, { method: "DELETE" });
    const data = await res.json();
    if (data.success) {
      cachedCalendarEvents = cachedCalendarEvents.filter(ev => ev.id !== eventId);
      renderCalendarEventsList();
      showSystemToast(`Deleted event: "${eventTitle}"`);
    } else {
      alert("Error deleting event: " + (data.error || "Unknown"));
    }
  } catch (err) {
    alert("Error deleting event: " + err.message);
  }
}

async function fetchCalendarEvents() {
  const container = document.getElementById("calendar-events-container");
  if (!container) return;

  try {
    const res = await fetch("/api/calendar/events");
    const data = await res.json();
    cachedCalendarEvents = data.events || [];
    renderCalendarEventsList();
  } catch (e) {
    container.innerHTML = `<div class='empty-state'>Failed to load events: ${e.message}</div>`;
  }
}

function initCalendarSchedulerControls() {
  // Preset buttons
  document.getElementById("preset-today-3pm")?.addEventListener("click", () => {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    const startInput = document.getElementById("cal-start");
    const endInput = document.getElementById("cal-end");
    if (startInput) startInput.value = `${y}-${m}-${d}T15:00`;
    if (endInput) endInput.value = `${y}-${m}-${d}T16:00`;
  });

  document.getElementById("preset-tomorrow-10am")?.addEventListener("click", () => {
    const tmrw = new Date();
    tmrw.setDate(tmrw.getDate() + 1);
    const y = tmrw.getFullYear();
    const m = String(tmrw.getMonth() + 1).padStart(2, "0");
    const d = String(tmrw.getDate()).padStart(2, "0");
    const startInput = document.getElementById("cal-start");
    const endInput = document.getElementById("cal-end");
    if (startInput) startInput.value = `${y}-${m}-${d}T10:00`;
    if (endInput) endInput.value = `${y}-${m}-${d}T11:00`;
  });

  document.getElementById("preset-plus-1hr")?.addEventListener("click", () => {
    const now = new Date();
    now.setHours(now.getHours() + 1, 0, 0, 0);
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    const h = String(now.getHours()).padStart(2, "0");
    const startStr = `${y}-${m}-${d}T${h}:00`;

    now.setHours(now.getHours() + 1);
    const y2 = now.getFullYear();
    const m2 = String(now.getMonth() + 1).padStart(2, "0");
    const d2 = String(now.getDate()).padStart(2, "0");
    const h2 = String(now.getHours()).padStart(2, "0");
    const endStr = `${y2}-${m2}-${d2}T${h2}:00`;

    const startInput = document.getElementById("cal-start");
    const endInput = document.getElementById("cal-end");
    if (startInput) startInput.value = startStr;
    if (endInput) endInput.value = endStr;
  });

  // Search input
  const searchInput = document.getElementById("cal-search-input");
  searchInput?.addEventListener("input", (e) => {
    calendarSearchQuery = e.target.value.trim();
    renderCalendarEventsList();
  });

  // Filter pills
  document.querySelectorAll(".cal-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".cal-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      activeCalendarFilter = pill.dataset.calFilter || "all";
      renderCalendarEventsList();
    });
  });

  // Refresh button
  document.getElementById("btn-refresh-calendar")?.addEventListener("click", () => {
    fetchCalendarEvents();
    showSystemToast("Calendar schedule refreshed");
  });

  // Toggle button (scroll to or focus sidebar)
  document.getElementById("btn-toggle-new-event")?.addEventListener("click", () => {
    const titleInput = document.getElementById("cal-title");
    titleInput?.focus();
    titleInput?.scrollIntoView({ behavior: "smooth", block: "center" });
  });

  // Schedule event button
  document.getElementById("btn-schedule-event")?.addEventListener("click", async () => {
    const title = document.getElementById("cal-title")?.value.trim();
    let start_time = document.getElementById("cal-start")?.value.trim();
    let end_time = document.getElementById("cal-end")?.value.trim();
    const description = document.getElementById("cal-desc")?.value.trim() || "";

    if (!title) return alert("Please enter an event title.");
    if (!start_time || !end_time) return alert("Please select both start and end times.");

    // Format datetime-local to ISO string if needed
    if (start_time.length === 16) start_time += ":00";
    if (end_time.length === 16) end_time += ":00";

    try {
      const res = await fetch("/api/calendar/create", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, start_time, end_time, description })
      });
      const data = await res.json();

      if (data.success) {
        showSystemToast(`Event scheduled: "${title}"`);
        const titleEl = document.getElementById("cal-title");
        const descEl = document.getElementById("cal-desc");
        if (titleEl) titleEl.value = "";
        if (descEl) descEl.value = "";
        fetchCalendarEvents();
      } else {
        alert("Scheduling error: " + (data.error || "Conflict detected"));
      }
    } catch (e) {
      alert("Error creating event: " + e.message);
    }
  });

  // Set default datetime values on first load
  const now = new Date();
  now.setHours(now.getHours() + 1, 0, 0, 0);
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  const h = String(now.getHours()).padStart(2, "0");
  const defaultStart = `${y}-${m}-${d}T${h}:00`;

  now.setHours(now.getHours() + 1);
  const y2 = now.getFullYear();
  const m2 = String(now.getMonth() + 1).padStart(2, "0");
  const d2 = String(now.getDate()).padStart(2, "0");
  const h2 = String(now.getHours()).padStart(2, "0");
  const defaultEnd = `${y2}-${m2}-${d2}T${h2}:00`;

  const startInput = document.getElementById("cal-start");
  const endInput = document.getElementById("cal-end");
  if (startInput && !startInput.value) {
    startInput.value = defaultStart;
  }
  if (endInput && !endInput.value) {
    endInput.value = defaultEnd;
  }
}

// ----------------------------------------------------------------------------
// Workspaces
// ----------------------------------------------------------------------------
// ----------------------------------------------------------------------------
// Workspaces
// ----------------------------------------------------------------------------
// Workspaces & Storage Management
// ----------------------------------------------------------------------------
let cachedWorkspacePresets = null;
let accessModeWired = false;

async function fetchAccessMode() {
  const badge = document.getElementById("badge-file-access-mode");
  const btn = document.getElementById("btn-toggle-access-mode");
  try {
    const res = await fetch("/api/system/access_mode");
    const data = await res.json();
    if (data && badge && btn) {
      if (data.all_files_mode) {
        badge.className = "risk-badge risk-low";
        badge.textContent = "ALL FILES ACCESS: ACTIVE";
        btn.textContent = "Mode: All Files";
        btn.title = "Current: All Files Access. Click to isolate to Sandboxed Workspaces.";
      } else {
        badge.className = "risk-badge risk-med";
        badge.textContent = "SANDBOX ISOLATED";
        btn.textContent = "Mode: Sandboxed";
        btn.title = "Current: Sandboxed Workspaces. Click to grant All Files Access.";
      }
    }
  } catch (_) {}

  if (!accessModeWired && btn) {
    accessModeWired = true;
    btn.addEventListener("click", async () => {
      try {
        const curRes = await fetch("/api/system/access_mode");
        const curData = await curRes.json();
        const nextState = !curData.all_files_mode;
        btn.disabled = true;
        await fetch("/api/system/access_mode", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ all_files_mode: nextState })
        });
        fetchAccessMode();
      } catch (_) {
      } finally {
        btn.disabled = false;
      }
    });
  }
}

async function fetchWorkspaces() {
  fetchAccessMode();
  const container = document.getElementById("workspaces-list-container");
  if (!container) return;

  try {
    const res = await fetch("/api/workspaces");
    const workspaces = await res.json();

    if (!workspaces.length) {
      container.innerHTML = `
        <div class="empty-state" style="padding: 40px 20px; text-align: center;">
          <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="#94a3b8" stroke-width="1.5" style="margin-bottom: 8px;">
            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
          </svg>
          <p style="color: #64748b; font-size: 13px;">No authorized workspaces registered yet.</p>
          <button type="button" class="pill-btn pill-btn-outline" style="margin-top: 10px;" onclick="document.getElementById('btn-open-add-ws-modal')?.click()">+ Authorize Workspace</button>
        </div>
      `;
      return;
    }

    container.innerHTML = "";
    workspaces.forEach(ws => {
      const div = document.createElement("div");
      div.className = "panel-card";
      div.style.position = "relative";

      const permBadges = (ws.permissions || []).map(p => {
        let badgeColor = "#475569";
        if (p === "READ") badgeColor = "#2563eb";
        if (p === "WRITE") badgeColor = "#0891b2";
        if (p === "DELETE") badgeColor = "#dc2626";
        return `<span style="display:inline-block; font-size:10.5px; font-weight:600; padding:2px 8px; border-radius:12px; background:#f1f5f9; color:${badgeColor}; border:1px solid #e2e8f0; margin-right:4px;">${p}</span>`;
      }).join("");

      div.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom: 10px;">
          <div>
            <h4 style="font-weight:700; font-size:15px; margin-bottom:2px; color:#0f172a;">${ws.name}</h4>
            <div style="margin-top:4px;">${permBadges}</div>
          </div>
          <span class="risk-badge ${ws.enabled ? "risk-low" : "risk-high"}">${ws.enabled ? "ENABLED" : "DISABLED"}</span>
        </div>
        <p style="font-family:var(--font-mono); font-size:12px; color:#475569; word-break:break-all; background:#f8fafc; padding:8px 10px; border-radius:6px; border:1px solid #f1f5f9; margin-bottom:12px;">${ws.path}</p>
        <div style="display:flex; justify-content:flex-end; gap:8px; border-top:1px solid #f1f5f9; padding-top:10px;">
          <button type="button" class="pill-btn pill-btn-outline btn-sm btn-toggle-ws" data-ws-id="${ws.workspace_id || ws.name}" style="font-size:11.5px; padding:4px 10px;">
            ${ws.enabled ? "Disable" : "Enable"}
          </button>
          <button type="button" class="pill-btn pill-btn-outline btn-sm btn-del-ws" data-ws-id="${ws.workspace_id || ws.name}" data-ws-name="${ws.name}" style="font-size:11.5px; padding:4px 10px; color:#dc2626; border-color:#fecaca;">
            Remove
          </button>
        </div>
      `;

      div.querySelector(".btn-toggle-ws")?.addEventListener("click", async (e) => {
        const targetId = e.currentTarget.getAttribute("data-ws-id");
        try {
          const res = await fetch(`/api/workspaces/${encodeURIComponent(targetId)}/toggle`, { method: "PATCH" });
          const data = await res.json();
          if (data.success) {
            fetchWorkspaces();
            fetchStatus();
          } else {
            alert("Error toggling workspace: " + (data.detail || "Unknown error"));
          }
        } catch (err) {
          alert("Error: " + err.message);
        }
      });

      div.querySelector(".btn-del-ws")?.addEventListener("click", async (e) => {
        const targetId = e.currentTarget.getAttribute("data-ws-id");
        const targetName = e.currentTarget.getAttribute("data-ws-name");
        if (!confirm(`Are you sure you want to unregister workspace "${targetName}"? Files on disk will NOT be deleted.`)) return;
        try {
          const res = await fetch(`/api/workspaces/${encodeURIComponent(targetId)}`, { method: "DELETE" });
          const data = await res.json();
          if (data.success) {
            fetchWorkspaces();
            fetchStatus();
          } else {
            alert("Error removing workspace: " + (data.detail || "Unknown error"));
          }
        } catch (err) {
          alert("Error: " + err.message);
        }
      });

      container.appendChild(div);
    });
  } catch (e) {
    container.innerHTML = `<div class='empty-state'>Failed to load workspaces: ${e.message}</div>`;
  }
}

async function loadWorkspacePresets() {
  if (cachedWorkspacePresets) return cachedWorkspacePresets;
  try {
    const res = await fetch("/api/workspaces/presets");
    cachedWorkspacePresets = await res.json();
    return cachedWorkspacePresets;
  } catch (e) {
    return null;
  }
}

function initWorkspaces() {
  const modal = document.getElementById("add-workspace-modal");
  const btnOpen = document.getElementById("btn-open-add-ws-modal");
  const btnCancel = document.getElementById("btn-cancel-add-ws");
  const btnSubmit = document.getElementById("btn-submit-add-ws");

  const inputName = document.getElementById("ws-input-name");
  const inputPath = document.getElementById("ws-input-path");
  const permWrite = document.getElementById("ws-perm-write");
  const permDelete = document.getElementById("ws-perm-delete");
  const hintEl = document.getElementById("ws-path-status-hint");

  const openModal = async () => {
    if (modal) modal.classList.remove("hidden");
    if (inputName) inputName.value = "";
    if (inputPath) inputPath.value = "";
    if (permWrite) permWrite.checked = true;
    if (permDelete) permDelete.checked = false;
    if (hintEl) {
      hintEl.textContent = "Select a quick preset or enter an absolute path on this machine.";
      hintEl.style.color = "#64748b";
    }
    await loadWorkspacePresets();
  };

  const closeModal = () => {
    if (modal) modal.classList.add("hidden");
  };

  btnOpen?.addEventListener("click", openModal);
  btnCancel?.addEventListener("click", closeModal);

  modal?.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  // Wire up quick preset buttons
  document.querySelectorAll("#ws-presets-container button[data-preset]")?.forEach(btn => {
    btn.addEventListener("click", async () => {
      const presetKey = btn.getAttribute("data-preset");
      const presets = await loadWorkspacePresets();
      if (presets && presets[presetKey]) {
        const item = presets[presetKey];
        if (inputName) inputName.value = item.name;
        if (inputPath) inputPath.value = item.path;
        if (hintEl) {
          hintEl.textContent = `Preset applied for ${item.name} (${item.exists ? "Path verified on disk" : "Local path"})`;
          hintEl.style.color = "#2563eb";
        }
      }
    });
  });

  btnSubmit?.addEventListener("click", async () => {
    const name = inputName?.value.trim();
    const path = inputPath?.value.trim();
    if (!name || !path) {
      alert("Please provide both a Workspace Name and Directory Path.");
      return;
    }

    const perms = ["READ"];
    if (permWrite?.checked) perms.push("WRITE");
    if (permDelete?.checked) perms.push("DELETE");

    try {
      btnSubmit.disabled = true;
      btnSubmit.textContent = "Authorizing...";
      const res = await fetch("/api/workspaces", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, path, permissions: perms })
      });
      const data = await res.json();
      if (data.success) {
        closeModal();
        fetchWorkspaces();
        fetchStatus();
      } else {
        alert("Failed to add workspace: " + (data.detail || data.error || "Unknown error"));
      }
    } catch (e) {
      alert("Error adding workspace: " + e.message);
    } finally {
      if (btnSubmit) {
        btnSubmit.disabled = false;
        btnSubmit.textContent = "Authorize Workspace";
      }
    }
  });

  // Also initialize Google Calendar Sync Modal
  initGoogleCalendarSync();
}

function initGoogleCalendarSync() {
  const modal = document.getElementById("gcal-sync-modal");
  const btnOpen = document.getElementById("btn-open-gcal-sync");
  const btnCancel = document.getElementById("btn-cancel-gcal-sync");
  const btnSubmit = document.getElementById("btn-submit-gcal-sync");
  const btnModeIcal = document.getElementById("gcal-mode-ical");
  const btnModeRest = document.getElementById("gcal-mode-rest");
  const sectionIcal = document.getElementById("gcal-section-ical");
  const sectionRest = document.getElementById("gcal-section-rest");
  const inputSource = document.getElementById("gcal-input-source");
  const inputCalId = document.getElementById("gcal-input-calid");
  const inputApiKey = document.getElementById("gcal-input-apikey");
  const inputToken = document.getElementById("gcal-input-token");
  const checkRemember = document.getElementById("gcal-remember-settings");
  const feedbackEl = document.getElementById("gcal-sync-feedback");

  let activeMode = "ical"; // 'ical' or 'rest'

  const setMode = (mode) => {
    activeMode = mode;
    if (mode === "ical") {
      btnModeIcal?.classList.remove("pill-btn-outline");
      btnModeIcal?.classList.add("pill-btn-dark");
      btnModeRest?.classList.remove("pill-btn-dark");
      btnModeRest?.classList.add("pill-btn-outline");
      if (sectionIcal) sectionIcal.style.display = "block";
      if (sectionRest) sectionRest.style.display = "none";
    } else {
      btnModeRest?.classList.remove("pill-btn-outline");
      btnModeRest?.classList.add("pill-btn-dark");
      btnModeIcal?.classList.remove("pill-btn-dark");
      btnModeIcal?.classList.add("pill-btn-outline");
      if (sectionIcal) sectionIcal.style.display = "none";
      if (sectionRest) sectionRest.style.display = "block";
    }
  };

  btnModeIcal?.addEventListener("click", () => setMode("ical"));
  btnModeRest?.addEventListener("click", () => setMode("rest"));

  const loadSavedSettings = () => {
    try {
      const savedMode = localStorage.getItem("gcal_sync_mode") || "ical";
      const savedSource = localStorage.getItem("gcal_sync_source") || "";
      const savedCalId = localStorage.getItem("gcal_sync_calid") || "primary";
      const savedApiKey = localStorage.getItem("gcal_sync_apikey") || "";
      const savedToken = localStorage.getItem("gcal_sync_token") || "";

      if (inputSource && savedSource) inputSource.value = savedSource;
      if (inputCalId && savedCalId) inputCalId.value = savedCalId;
      if (inputApiKey && savedApiKey) inputApiKey.value = savedApiKey;
      if (inputToken && savedToken) inputToken.value = savedToken;

      setMode(savedMode);
    } catch (_) {
      setMode("ical");
    }
  };

  const openModal = () => {
    if (modal) modal.classList.remove("hidden");
    if (feedbackEl) feedbackEl.style.display = "none";
    loadSavedSettings();
  };

  const closeModal = () => {
    if (modal) modal.classList.add("hidden");
  };

  btnOpen?.addEventListener("click", openModal);
  btnCancel?.addEventListener("click", closeModal);

  modal?.addEventListener("click", (e) => {
    if (e.target === modal) closeModal();
  });

  btnSubmit?.addEventListener("click", async () => {
    let sourcePayload = "";
    let apiKeyPayload = undefined;
    let tokenPayload = undefined;

    if (activeMode === "ical") {
      sourcePayload = inputSource?.value.trim() || "";
      if (!sourcePayload) {
        if (feedbackEl) {
          feedbackEl.style.display = "block";
          feedbackEl.style.background = "#fef2f2";
          feedbackEl.style.color = "#991b1b";
          feedbackEl.textContent = "Please enter your Google Calendar Secret iCal Address URL.";
        }
        return;
      }
    } else {
      sourcePayload = inputCalId?.value.trim() || "primary";
      apiKeyPayload = inputApiKey?.value.trim() || undefined;
      tokenPayload = inputToken?.value.trim() || undefined;

      if (!apiKeyPayload && !tokenPayload) {
        if (feedbackEl) {
          feedbackEl.style.display = "block";
          feedbackEl.style.background = "#fef2f2";
          feedbackEl.style.color = "#991b1b";
          feedbackEl.textContent = "REST API v3 requires a Google Cloud API Key or an OAuth Bearer Token.";
        }
        return;
      }
    }

    if (checkRemember?.checked) {
      try {
        localStorage.setItem("gcal_sync_mode", activeMode);
        if (inputSource?.value) localStorage.setItem("gcal_sync_source", inputSource.value.trim());
        if (inputCalId?.value) localStorage.setItem("gcal_sync_calid", inputCalId.value.trim());
        if (inputApiKey?.value) localStorage.setItem("gcal_sync_apikey", inputApiKey.value.trim());
        if (inputToken?.value) localStorage.setItem("gcal_sync_token", inputToken.value.trim());
      } catch (_) {}
    }

    if (feedbackEl) {
      feedbackEl.style.display = "block";
      feedbackEl.style.background = "#eff6ff";
      feedbackEl.style.color = "#1e40af";
      feedbackEl.textContent = activeMode === "rest"
        ? "Connecting to Google Calendar REST API v3..."
        : "Fetching events from Google Calendar iCal feed...";
    }

    try {
      btnSubmit.disabled = true;
      btnSubmit.textContent = "Syncing...";
      const res = await fetch("/api/calendar/google/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          calendar_id_or_url: sourcePayload,
          api_key: apiKeyPayload,
          access_token: tokenPayload
        })
      });
      const data = await res.json();
      if (data.success) {
        if (feedbackEl) {
          feedbackEl.style.background = "#f0fdf4";
          feedbackEl.style.color = "#166534";
          feedbackEl.textContent = `Sync completed: ${data.synced_count} event(s) retrieved (${data.newly_added} newly stored).`;
        }
        fetchCalendarEvents();
        setTimeout(closeModal, 1500);
      } else {
        if (feedbackEl) {
          feedbackEl.style.background = "#fef2f2";
          feedbackEl.style.color = "#991b1b";
          feedbackEl.textContent = data.error || "Sync failed. Please verify credentials or URL.";
        }
      }
    } catch (e) {
      if (feedbackEl) {
        feedbackEl.style.background = "#fef2f2";
        feedbackEl.style.color = "#991b1b";
        feedbackEl.textContent = "Network error: " + e.message;
      }
    } finally {
      if (btnSubmit) {
        btnSubmit.disabled = false;
        btnSubmit.textContent = "Sync Schedule";
      }
    }
  });
}


// ----------------------------------------------------------------------------
// Tasks & Audit Logs
// ----------------------------------------------------------------------------
async function fetchTasksList() {
  const tbody = document.getElementById("tasks-table-body");
  if (!tbody) return;

  try {
    const res = await fetch("/api/tasks");
    const tasks = await res.json();

    if (!tasks.length) {
      tbody.innerHTML = "<tr><td colspan='4' class='text-center'>No task execution records found.</td></tr>";
      return;
    }

    tbody.innerHTML = "";
    tasks.forEach(t => {
      const tr = document.createElement("tr");
      const statusClass = t.status === "COMPLETED" ? "risk-low" : t.status === "FAILED" ? "risk-high" : "risk-med";
      tr.innerHTML = `
        <td style="font-family:var(--font-mono); font-size:12px;">${t.task_id}</td>
        <td>${t.goal || "—"}</td>
        <td><span class="risk-badge ${statusClass}">${t.status}</span></td>
        <td style="font-size:12px; color:#64748b;">${t.created_at || "—"}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan='4' class='text-center'>Failed to load tasks: ${e.message}</td></tr>`;
  }
}

async function fetchAuditLogs() {
  const tbody = document.getElementById("audit-table-body");
  if (!tbody) return;

  try {
    const res = await fetch("/api/audit?limit=20");
    const logs = await res.json();

    if (!logs.length) {
      tbody.innerHTML = "<tr><td colspan='6' class='text-center'>No audit records found.</td></tr>";
      return;
    }

    tbody.innerHTML = "";
    logs.forEach(l => {
      const tr = document.createElement("tr");
      const statusClass = l.execution_status === "SUCCESS" || l.execution_status === "COMPLETED" ? "risk-low" : "risk-high";
      tr.innerHTML = `
        <td style="font-family:var(--font-mono); font-size:11.5px;">${l.id || l.log_id || "—"}</td>
        <td style="font-family:var(--font-mono); font-weight:600;">${l.action}</td>
        <td style="font-size:11.5px; color:#475569; max-width:260px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">${JSON.stringify(l.params || l.details || {})}</td>
        <td><span class="risk-badge ${l.approval_result === "APPROVED" ? "risk-low" : "risk-med"}">${l.approval_result}</span></td>
        <td><span class="risk-badge ${statusClass}">${l.execution_status}</span></td>
        <td style="font-size:11.5px; color:#64748b;">${l.timestamp || "—"}</td>
      `;
      tbody.appendChild(tr);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan='6' class='text-center'>Failed to load audit logs: ${e.message}</td></tr>`;
  }
}

function initAudit() {
  document.getElementById("btn-refresh-audit")?.addEventListener("click", fetchAuditLogs);
}


// ============================================================================
// GitHub Integration Dashboard (Milestone 9)
// ============================================================================

let githubConnectedAccount = null;
let githubTrackedRepos = [];

const GITHUB_LANG_COLORS = {
  Python: "#3572A5", JavaScript: "#f1e05a", TypeScript: "#3178c6",
  Java: "#b07219", "C++": "#f34b7d", C: "#555555", "C#": "#178600",
  Go: "#00ADD8", Rust: "#dea584", PHP: "#4F5D95", Ruby: "#701516",
  Swift: "#F05138", Kotlin: "#A97BFF", Dart: "#00B4AB", HTML: "#e34c26",
  CSS: "#563d7c", Shell: "#89e051", Vue: "#41b883", default: "#64748b"
};

async function initGithubDashboard() {
  // Check URL query parameters for OAuth redirect callbacks
  const urlParams = new URLSearchParams(window.location.search);
  if (urlParams.get("github_auth") === "success") {
    const login = urlParams.get("login") || "";
    window.history.replaceState({}, document.title, window.location.pathname + "#tab-github");
    setTimeout(() => {
      document.querySelector('.nav-item[data-tab="tab-github"]')?.click();
      showSystemToast(login ? `GitHub account @${login} connected successfully!` : "GitHub account connected successfully!");
    }, 150);
  } else if (urlParams.get("github_error")) {
    const err = urlParams.get("github_error");
    window.history.replaceState({}, document.title, window.location.pathname + "#tab-github");
    setTimeout(() => {
      document.querySelector('.nav-item[data-tab="tab-github"]')?.click();
      alert("GitHub Connection Failed: " + err);
    }, 150);
  }

  // Load initial status
  await loadGithubStatus();

  // Navigation button click refresh
  document.getElementById("nav-btn-github")?.addEventListener("click", () => {
    loadGithubStatus();
  });

  // Connect Buttons (both header button and main card button)
  const triggerGithubLogin = () => {
    window.location.href = "/api/github/auth/login";
  };
  document.getElementById("btn-github-connect")?.addEventListener("click", triggerGithubLogin);
  document.getElementById("btn-github-oauth-main")?.addEventListener("click", triggerGithubLogin);

  // Upload ZIP Archive Trigger
  document.getElementById("btn-github-upload-zip-trigger")?.addEventListener("click", () => {
    document.getElementById("github-zip-file-input")?.click();
  });

  document.getElementById("github-zip-file-input")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (file) {
      await handleZipUpload(file);
      e.target.value = "";
    }
  });

  // Back from Analysis Button
  document.getElementById("btn-github-analysis-back")?.addEventListener("click", () => {
    const container = document.getElementById("github-analysis-container");
    const reposPanel = document.getElementById("github-repos-panel");
    const addPanel = document.getElementById("github-repo-add-panel");
    if (container) container.style.display = "none";
    if (reposPanel) reposPanel.style.display = "block";
    if (addPanel && githubConnectedAccount) addPanel.style.display = "block";
  });

  // Re-run Analysis Button
  document.getElementById("btn-github-analysis-rerun")?.addEventListener("click", async () => {
    if (currentAnalysisRepoId) {
      await openRepositoryAnalysis(currentAnalysisRepoId, currentAnalysisRepoName, true);
    } else if (currentAnalysisData) {
      showSystemToast("ZIP snapshot analyses are static. Re-upload archive to re-analyze.");
    }
  });

  // Chat with Repo Button from Analysis Header
  document.getElementById("btn-github-analysis-chat")?.addEventListener("click", () => {
    if (currentAnalysisRepoName) {
      switchGithubSubnav("chat");
      loadAnalyzedReposForChat(currentAnalysisRepoName);
    }
  });

  // Subnav Switcher Buttons
  document.getElementById("btn-github-subnav-repos")?.addEventListener("click", () => {
    switchGithubSubnav("repos");
  });
  document.getElementById("btn-github-subnav-chat")?.addEventListener("click", () => {
    switchGithubSubnav("chat");
  });

  // Initialize Repository Chat Controls
  initGithubChat();

  // Initialize Developer Workbench Controls (Prompt 4)
  if (typeof initGithubWorkbench === 'function') initGithubWorkbench();

  // Analysis Panels Navigation Tabs
  document.querySelectorAll(".github-tab-btn").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".github-tab-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const targetPanelId = btn.getAttribute("data-analysis-panel");
      document.querySelectorAll(".github-analysis-panel").forEach(p => {
        p.style.display = (p.id === targetPanelId) ? "block" : "none";
      });
    });
  });

  // Disconnect Button
  document.getElementById("btn-github-disconnect")?.addEventListener("click", async () => {
    if (!confirm("Are you sure you want to disconnect your GitHub account? Connected repositories will remain tracked.")) {
      return;
    }
    try {
      const res = await fetch("/api/github/auth/disconnect", { method: "POST" });
      const data = await res.json();
      if (data.success) {
        showSystemToast("GitHub account disconnected.");
        await loadGithubStatus();
      } else {
        alert("Disconnect failed: " + (data.error || "Unknown error"));
      }
    } catch (e) {
      alert("Disconnect error: " + e.message);
    }
  });

  // Refresh Button
  document.getElementById("btn-github-refresh")?.addEventListener("click", async () => {
    await loadGithubStatus();
    showSystemToast("GitHub dashboard refreshed.");
  });

  // Add Repository by URL
  document.getElementById("btn-github-add-repo-url")?.addEventListener("click", async () => {
    const input = document.getElementById("github-repo-url-input");
    const statusEl = document.getElementById("github-add-repo-status");
    const val = input ? input.value.trim() : "";
    if (!val) {
      if (statusEl) {
        statusEl.className = "error";
        statusEl.textContent = "Please enter a repository URL or owner/repo format.";
      }
      return;
    }

    const btn = document.getElementById("btn-github-add-repo-url");
    const origText = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Adding...";
    }
    if (statusEl) {
      statusEl.className = "";
      statusEl.textContent = "Validating and fetching repository...";
    }

    try {
      const res = await fetch("/api/github/repos/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo: val })
      });
      const data = await res.json();
      if (data.success) {
        if (input) input.value = "";
        if (statusEl) {
          statusEl.className = "success";
          statusEl.textContent = `Repository '${data.full_name}' added successfully!`;
        }
        showSystemToast(`Repository '${data.full_name}' added.`);
        await loadGithubStatus();
      } else {
        if (statusEl) {
          statusEl.className = "error";
          statusEl.textContent = data.error || "Failed to add repository.";
        }
      }
    } catch (e) {
      if (statusEl) {
        statusEl.className = "error";
        statusEl.textContent = "Error: " + e.message;
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = origText;
      }
    }
  });

  // Add Repository from User Dropdown
  document.getElementById("btn-github-add-selected")?.addEventListener("click", async () => {
    const select = document.getElementById("github-user-repos-select");
    const statusEl = document.getElementById("github-add-repo-status");
    const val = select ? select.value.trim() : "";
    if (!val) {
      if (statusEl) {
        statusEl.className = "error";
        statusEl.textContent = "Please select a repository from the list.";
      }
      return;
    }

    const btn = document.getElementById("btn-github-add-selected");
    const origText = btn ? btn.innerHTML : "";
    if (btn) {
      btn.disabled = true;
      btn.textContent = "Adding...";
    }

    try {
      const res = await fetch("/api/github/repos/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo: val })
      });
      const data = await res.json();
      if (data.success) {
        if (statusEl) {
          statusEl.className = "success";
          statusEl.textContent = `Repository '${data.full_name}' added!`;
        }
        showSystemToast(`Repository '${data.full_name}' added.`);
        await loadGithubStatus();
      } else {
        if (statusEl) {
          statusEl.className = "error";
          statusEl.textContent = data.error || "Failed to add repository.";
        }
      }
    } catch (e) {
      if (statusEl) {
        statusEl.className = "error";
        statusEl.textContent = "Error: " + e.message;
      }
    } finally {
      if (btn) {
        btn.disabled = false;
        btn.innerHTML = origText;
      }
    }
  });

  // Search, filter, and sort listeners
  document.getElementById("github-repos-search")?.addEventListener("input", filterAndRenderConnectedRepos);
  document.getElementById("github-repos-filter")?.addEventListener("change", filterAndRenderConnectedRepos);
  document.getElementById("github-repos-sort")?.addEventListener("change", filterAndRenderConnectedRepos);
}

async function loadGithubStatus() {
  try {
    const res = await fetch("/api/github/auth/status");
    const data = await res.json();

    const isConnected = !!data.connected;
    githubConnectedAccount = isConnected ? data : null;

    // Update connection badge
    const badge = document.getElementById("github-connection-badge");
    if (badge) {
      badge.textContent = isConnected ? `Connected: @${data.login}` : "Not Connected";
      badge.className = `risk-badge ${isConnected ? "risk-low" : "risk-med"}`;
    }

    // Update stat card values
    const acctVal = document.getElementById("github-stat-account-val");
    if (acctVal) acctVal.textContent = isConnected ? `@${data.login}` : "—";

    const totalVal = document.getElementById("github-stat-total-val");
    if (totalVal) totalVal.textContent = data.total_repos_connected ?? 0;

    const pubVal = document.getElementById("github-stat-public-val");
    if (pubVal) pubVal.textContent = isConnected ? (data.public_repos ?? 0) : "—";

    const privVal = document.getElementById("github-stat-private-val");
    if (privVal) privVal.textContent = isConnected ? (data.private_repos ?? 0) : "—";

    // Toggle panels based on connection status
    const connectCard = document.getElementById("github-connect-card");
    const addPanel = document.getElementById("github-repo-add-panel");
    const reposPanel = document.getElementById("github-repos-panel");
    const headerConnectBtn = document.getElementById("btn-github-connect");
    const headerDisconnectBtn = document.getElementById("btn-github-disconnect");

    if (isConnected) {
      if (connectCard) connectCard.style.display = "none";
      if (addPanel) addPanel.style.display = "block";
      if (reposPanel) reposPanel.style.display = "block";
      if (headerConnectBtn) headerConnectBtn.style.display = "none";
      if (headerDisconnectBtn) headerDisconnectBtn.style.display = "inline-flex";

      // Load user repos dropdown
      loadGithubUserReposDropdown();
    } else {
      if (connectCard) connectCard.style.display = "block";
      if (addPanel) addPanel.style.display = "none";
      // If there are locally tracked repos, we can still show the repos panel
      if (reposPanel) reposPanel.style.display = (data.total_repos_connected > 0) ? "block" : "none";
      if (headerConnectBtn) headerConnectBtn.style.display = "inline-flex";
      if (headerDisconnectBtn) headerDisconnectBtn.style.display = "none";
    }

    // Always load connected repos (even if disconnected, they are stored locally in DB)
    await loadGithubConnectedRepos();
  } catch (err) {
    console.error("Error loading GitHub status:", err);
  }
}

async function loadGithubUserReposDropdown() {
  const select = document.getElementById("github-user-repos-select");
  if (!select) return;

  try {
    const res = await fetch("/api/github/repos/user?per_page=100");
    const data = await res.json();
    if (data.success && Array.isArray(data.repos)) {
      select.innerHTML = '<option value="">Select from your repositories...</option>';
      data.repos.forEach(r => {
        const opt = document.createElement("option");
        opt.value = r.full_name;
        opt.textContent = `${r.full_name} (${r.private ? "Private" : "Public"})`;
        select.appendChild(opt);
      });
    }
  } catch (e) {
    console.error("Error loading user repos for dropdown:", e);
  }
}

async function loadGithubConnectedRepos() {
  try {
    const res = await fetch("/api/github/repos/connected");
    const data = await res.json();
    if (data.success && Array.isArray(data.repos)) {
      githubTrackedRepos = data.repos;
      filterAndRenderConnectedRepos();
      if (typeof updateWorkbenchGlobalRepoSelect === 'function') updateWorkbenchGlobalRepoSelect();
    }
  } catch (e) {
    console.error("Error loading connected repos:", e);
  }
}

function filterAndRenderConnectedRepos() {
  const grid = document.getElementById("github-repos-grid");
  if (!grid) return;

  const searchVal = (document.getElementById("github-repos-search")?.value || "").toLowerCase().trim();
  const filterVal = document.getElementById("github-repos-filter")?.value || "all";
  const sortVal = document.getElementById("github-repos-sort")?.value || "updated";

  let filtered = [...githubTrackedRepos];

  // Search filter
  if (searchVal) {
    filtered = filtered.filter(r =>
      (r.full_name && r.full_name.toLowerCase().includes(searchVal)) ||
      (r.description && r.description.toLowerCase().includes(searchVal)) ||
      (r.language && r.language.toLowerCase().includes(searchVal))
    );
  }

  // Visibility filter
  if (filterVal === "public") {
    filtered = filtered.filter(r => !r.private);
  } else if (filterVal === "private") {
    filtered = filtered.filter(r => !!r.private);
  }

  // Sorting
  if (sortVal === "name") {
    filtered.sort((a, b) => (a.full_name || "").localeCompare(b.full_name || ""));
  } else if (sortVal === "stars") {
    filtered.sort((a, b) => (b.stars || 0) - (a.stars || 0));
  } else {
    // updated
    filtered.sort((a, b) => {
      const dateA = a.last_synced_at || a.added_at || "";
      const dateB = b.last_synced_at || b.added_at || "";
      return dateB.localeCompare(dateA);
    });
  }

  if (filtered.length === 0) {
    grid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1; padding: 32px 16px; text-align: center; color: #94a3b8;">No matching repositories found.</div>';
    return;
  }

  grid.innerHTML = "";
  filtered.forEach(repo => {
    const card = document.createElement("div");
    card.className = "github-repo-card";

    const langColor = GITHUB_LANG_COLORS[repo.language] || GITHUB_LANG_COLORS.default;
    const visibilityClass = repo.private ? "private" : "public";
    const visibilityText = repo.private ? "Private" : "Public";
    const updatedTime = repo.last_synced_at || repo.added_at || "Recently";

    card.innerHTML = `
      <div>
        <div class="github-repo-header">
          <a href="${escapeHtml(repo.html_url || `https://github.com/${repo.full_name}`)}" target="_blank" class="github-repo-title">
            ${escapeHtml(repo.full_name)}
          </a>
          <span class="github-visibility-badge ${visibilityClass}">${visibilityText}</span>
        </div>
        <p class="github-repo-desc">${escapeHtml(repo.description || "No description provided.")}</p>
      </div>

      <div>
        <div class="github-repo-meta">
          ${repo.language ? `
            <div class="github-meta-item">
              <span class="github-lang-dot" style="background:${langColor};"></span>
              <span>${escapeHtml(repo.language)}</span>
            </div>
          ` : ""}
          <div class="github-meta-item">
            <span>★</span>
            <span>${repo.stars || 0}</span>
          </div>
          <div class="github-meta-item">
            <span>⎇</span>
            <span>${escapeHtml(repo.default_branch || "main")}</span>
          </div>
          <div class="github-meta-item" style="font-size:11px; color:#94a3b8;">
            <span>Updated ${escapeHtml(updatedTime)}</span>
          </div>
        </div>

        <div class="github-repo-actions">
          <button class="pill-btn pill-btn-primary btn-github-analyze" data-id="${repo.id}" data-name="${escapeHtml(repo.full_name)}" style="font-size:11px; padding:4px 10px;">
            ⚡ Analyze
          </button>
          <button class="pill-btn pill-btn-outline btn-github-chat-quick" data-id="${repo.id}" data-name="${escapeHtml(repo.full_name)}" style="font-size:11px; padding:4px 10px;">
            💬 Chat
          </button>
          <a href="${escapeHtml(repo.html_url || `https://github.com/${repo.full_name}`)}" target="_blank" class="pill-btn pill-btn-outline" style="font-size:11px; padding:4px 10px;">
            Open on GitHub ↗
          </a>
          <button class="pill-btn pill-btn-outline btn-github-remove" data-id="${repo.id}" data-name="${escapeHtml(repo.full_name)}" style="font-size:11px; padding:4px 10px; color:#dc2626; border-color:#fecaca;">
            Remove
          </button>
        </div>
      </div>
    `;

    // Add analyze event listener
    const analyzeBtn = card.querySelector(".btn-github-analyze");
    analyzeBtn?.addEventListener("click", () => {
      const repoId = analyzeBtn.getAttribute("data-id");
      const repoName = analyzeBtn.getAttribute("data-name");
      openRepositoryAnalysis(repoId, repoName, false);
    });

    // Add chat quick event listener
    const chatBtn = card.querySelector(".btn-github-chat-quick");
    chatBtn?.addEventListener("click", () => {
      const repoName = chatBtn.getAttribute("data-name");
      switchGithubSubnav("chat");
      loadAnalyzedReposForChat(repoName);
    });

    // Add remove event listener
    const removeBtn = card.querySelector(".btn-github-remove");
    removeBtn?.addEventListener("click", async () => {
      const repoId = removeBtn.getAttribute("data-id");
      const repoName = removeBtn.getAttribute("data-name");
      if (!confirm(`Remove repository '${repoName}' from this dashboard?\n(This will NOT delete the repository from GitHub)`)) {
        return;
      }
      try {
        const res = await fetch(`/api/github/repos/${repoId}`, { method: "DELETE" });
        const d = await res.json();
        if (d.success) {
          showSystemToast(`Removed '${repoName}' from dashboard.`);
          await loadGithubStatus();
        } else {
          alert("Removal failed: " + (d.error || "Unknown error"));
        }
      } catch (e) {
        alert("Removal error: " + e.message);
      }
    });

    grid.appendChild(card);
  });
}

// ============================================================================
// AI Repository Intelligence Handlers & Renderers (Milestone 9 - Prompt 2)
// ============================================================================

let currentAnalysisRepoId = null;
let currentAnalysisRepoName = "";
let currentAnalysisData = null;

async function openRepositoryAnalysis(repoId, repoName, forceRefresh = false) {
  currentAnalysisRepoId = repoId;
  currentAnalysisRepoName = repoName;

  const container = document.getElementById("github-analysis-container");
  const loading = document.getElementById("github-analysis-loading");
  const content = document.getElementById("github-analysis-content");
  const errorEl = document.getElementById("github-analysis-error");
  const reposPanel = document.getElementById("github-repos-panel");
  const addPanel = document.getElementById("github-repo-add-panel");
  const titleEl = document.getElementById("github-analysis-title");

  if (reposPanel) reposPanel.style.display = "none";
  if (addPanel) addPanel.style.display = "none";
  if (container) container.style.display = "block";
  if (loading) loading.style.display = "block";
  if (content) content.style.display = "none";
  if (errorEl) errorEl.style.display = "none";
  if (titleEl) titleEl.textContent = repoName;

  container.scrollIntoView({ behavior: "smooth" });

  try {
    const res = await fetch(`/api/github/repos/${repoId}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force_refresh: forceRefresh })
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || data.detail || "Analysis failed.");
    }
    renderRepositoryAnalysis(data);
  } catch (err) {
    if (loading) loading.style.display = "none";
    if (errorEl) {
      errorEl.textContent = `Analysis error: ${err.message}`;
      errorEl.style.display = "block";
    }
  }
}

async function handleZipUpload(file) {
  const container = document.getElementById("github-analysis-container");
  const loading = document.getElementById("github-analysis-loading");
  const content = document.getElementById("github-analysis-content");
  const errorEl = document.getElementById("github-analysis-error");
  const reposPanel = document.getElementById("github-repos-panel");
  const addPanel = document.getElementById("github-repo-add-panel");
  const titleEl = document.getElementById("github-analysis-title");

  if (reposPanel) reposPanel.style.display = "none";
  if (addPanel) addPanel.style.display = "none";
  if (container) container.style.display = "block";
  if (loading) loading.style.display = "block";
  if (content) content.style.display = "none";
  if (errorEl) errorEl.style.display = "none";
  if (titleEl) titleEl.textContent = file.name;

  currentAnalysisRepoId = null;
  currentAnalysisRepoName = file.name;

  container.scrollIntoView({ behavior: "smooth" });

  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch("/api/github/repos/upload-zip", {
      method: "POST",
      body: formData
    });
    const data = await res.json();
    if (!res.ok || !data.success) {
      throw new Error(data.error || data.detail || "ZIP upload analysis failed.");
    }
    renderRepositoryAnalysis(data);
  } catch (err) {
    if (loading) loading.style.display = "none";
    if (errorEl) {
      errorEl.textContent = `Upload error: ${err.message}`;
      errorEl.style.display = "block";
    }
  }
}

function renderRepositoryAnalysis(analysis) {
  currentAnalysisData = analysis;

  const loading = document.getElementById("github-analysis-loading");
  const content = document.getElementById("github-analysis-content");
  const errorEl = document.getElementById("github-analysis-error");
  const titleEl = document.getElementById("github-analysis-title");
  const commitBadge = document.getElementById("github-analysis-commit-badge");
  const dateBadge = document.getElementById("github-analysis-date-badge");
  const providerBadge = document.getElementById("github-analysis-provider-badge");

  if (loading) loading.style.display = "none";
  if (errorEl) errorEl.style.display = "none";
  if (content) content.style.display = "block";

  if (titleEl) titleEl.textContent = analysis.repo_name || "Repository Intelligence";
  if (commitBadge) {
    const sha = (analysis.commit_sha || "snapshot").substring(0, 8);
    commitBadge.textContent = `Commit: ${sha}`;
  }
  if (dateBadge) {
    dateBadge.textContent = `Analyzed: ${analysis.timestamp || analysis.created_at || "Just now"}`;
  }
  if (providerBadge) {
    const prov = analysis.llm_provider || "deterministic-fallback";
    providerBadge.textContent = prov === "ollama" ? "Ollama (Local)" : (prov === "groq" ? "Groq (Cloud)" : "Deterministic Engine");
  }

  // 1. Summary Cards
  // Languages Card
  const langCardVal = document.getElementById("analysis-card-languages");
  const langBar = document.getElementById("analysis-card-lang-bar");
  const langs = analysis.languages || {};
  const langKeys = Object.keys(langs);

  if (langCardVal) {
    langCardVal.textContent = langKeys.length > 0 ? `${langKeys[0]} (${langs[langKeys[0]].percentage}%)` : "Multi-language";
  }

  if (langBar) {
    langBar.innerHTML = "";
    langKeys.forEach(k => {
      const seg = document.createElement("div");
      seg.className = "github-lang-bar-segment";
      const color = GITHUB_LANG_COLORS[k] || GITHUB_LANG_COLORS.default;
      seg.style.background = color;
      seg.style.width = `${langs[k].percentage}%`;
      seg.title = `${k}: ${langs[k].percentage}%`;
      langBar.appendChild(seg);
    });
  }

  // Frameworks Card
  const frameworksCardVal = document.getElementById("analysis-card-frameworks");
  const frameworksRow = document.getElementById("analysis-card-framework-tags");
  const frameworks = analysis.frameworks || [];

  if (frameworksCardVal) {
    frameworksCardVal.textContent = frameworks.length > 0 ? `${frameworks.length} Identified` : "None Detected";
  }

  if (frameworksRow) {
    frameworksRow.innerHTML = "";
    frameworks.slice(0, 5).forEach(fw => {
      const pill = document.createElement("span");
      pill.className = "github-tag-pill";
      pill.textContent = fw;
      frameworksRow.appendChild(pill);
    });
  }

  // Dependencies Card
  const depsCardVal = document.getElementById("analysis-card-dependencies");
  const manifestsSub = document.getElementById("analysis-card-manifests");
  const totalDeps = analysis.total_dependencies_count || (analysis.dependencies ? analysis.dependencies.length : 0);
  const pkgManagers = (analysis.package_managers || []).join(", ") || "package manifests";

  if (depsCardVal) depsCardVal.textContent = totalDeps;
  if (manifestsSub) manifestsSub.textContent = `Managed via ${pkgManagers}`;

  // Coverage Card
  const filesCardVal = document.getElementById("analysis-card-files");
  const coverageSub = document.getElementById("analysis-card-coverage-sub");
  if (filesCardVal) {
    filesCardVal.textContent = `${analysis.inspected_files_count || 0} / ${analysis.total_files_count || 0}`;
  }
  if (coverageSub) {
    coverageSub.textContent = `${analysis.skipped_files_count || 0} binary/media/oversized skipped`;
  }

  // 2. Panels
  // A. Overview Panel
  const overviewSummary = document.getElementById("analysis-overview-summary");
  if (overviewSummary) {
    overviewSummary.textContent = analysis.summary || "No high-level summary generated.";
  }

  const entryPointsList = document.getElementById("analysis-overview-entry-points");
  if (entryPointsList) {
    entryPointsList.innerHTML = "";
    const eps = analysis.entry_points || [];
    if (eps.length === 0) {
      entryPointsList.innerHTML = `<div class="github-item-card-desc">No explicit entry point scripts detected in root.</div>`;
    } else {
      eps.forEach(ep => {
        const item = document.createElement("div");
        item.className = "github-item-card";
        item.innerHTML = `
          <div class="github-item-card-title">
            <span style="font-family:monospace; color:#2563eb;">${escapeHtml(ep.path)}</span>
          </div>
          <div class="github-item-card-desc">${escapeHtml(ep.description)}</div>
        `;
        entryPointsList.appendChild(item);
      });
    }
  }

  const langsOverview = document.getElementById("analysis-overview-languages");
  if (langsOverview) {
    langsOverview.innerHTML = "";
    if (langKeys.length === 0) {
      langsOverview.innerHTML = `<div class="github-item-card-desc">No language statistics computed.</div>`;
    } else {
      langKeys.forEach(lk => {
        const ldata = langs[lk];
        const item = document.createElement("div");
        item.className = "github-item-card";
        const color = GITHUB_LANG_COLORS[lk] || GITHUB_LANG_COLORS.default;
        item.innerHTML = `
          <div class="github-item-card-title">
            <span style="display:flex; align-items:center; gap:6px;">
              <span class="github-lang-dot" style="background:${color};"></span>
              <strong>${escapeHtml(lk)}</strong>
            </span>
            <span>${ldata.percentage}%</span>
          </div>
          <div class="github-item-card-desc">${ldata.files} file(s), ${Math.round(ldata.bytes / 1024)} KB inspected</div>
        `;
        langsOverview.appendChild(item);
      });
    }
  }

  // B. Architecture Panel
  const archComponents = document.getElementById("analysis-arch-components");
  if (archComponents) {
    archComponents.innerHTML = "";
    const comps = analysis.components || [];
    if (comps.length === 0) {
      archComponents.innerHTML = `<div class="github-item-card-desc">No component breakdown available.</div>`;
    } else {
      comps.forEach(c => {
        const card = document.createElement("div");
        card.className = "github-component-card";
        const filesStr = (c.primary_files || []).join(", ");
        card.innerHTML = `
          <div class="github-component-title">${escapeHtml(c.name)}</div>
          <div class="github-component-resp">${escapeHtml(c.responsibility)}</div>
          ${filesStr ? `<div class="github-component-files">📁 ${escapeHtml(filesStr)}</div>` : ""}
        `;
        archComponents.appendChild(card);
      });
    }
  }

  const archFlow = document.getElementById("analysis-arch-flow");
  const archGrounding = document.getElementById("analysis-arch-grounding");
  const flowData = analysis.architecture_flow || {};
  if (archFlow) {
    archFlow.textContent = flowData.data_and_control_flow || "Standard module structure; control flows through entry point handlers.";
  }
  if (archGrounding) {
    archGrounding.textContent = `Evidence Grounding: ${flowData.grounding_notes || "Derived directly from inspected project manifest and source imports."}`;
  }

  // C. Folder Structure & Explorer
  const treeContainer = document.getElementById("analysis-file-tree");
  const treeStats = document.getElementById("analysis-tree-stats");
  if (treeStats) {
    treeStats.textContent = `${analysis.total_files_count || 0} total entries`;
  }
  if (treeContainer) {
    treeContainer.innerHTML = "";
    const tree = analysis.tree || [];
    if (tree.length === 0) {
      treeContainer.innerHTML = `<div style="padding:10px; color:#64748b;">No file tree available.</div>`;
    } else {
      tree.forEach(node => {
        treeContainer.appendChild(renderFileTreeNode(node));
      });
    }
  }

  const folderModulesList = document.getElementById("analysis-folder-modules");
  if (folderModulesList) {
    folderModulesList.innerHTML = "";
    const fmods = analysis.folder_modules || [];
    fmods.forEach(fm => {
      const item = document.createElement("div");
      item.className = "github-item-card";
      const sample = (fm.sample_files || []).join(", ");
      item.innerHTML = `
        <div class="github-item-card-title">
          <span style="font-family:monospace; color:#1e40af;">📁 ${escapeHtml(fm.folder)}/</span>
          <span class="github-badge" style="font-size:10px;">${fm.files_count} file(s)</span>
        </div>
        <div class="github-item-card-desc"><strong>${escapeHtml(fm.role)}</strong></div>
        ${sample ? `<div class="github-item-card-desc" style="font-family:monospace; font-size:11px; margin-top:2px;">Files: ${escapeHtml(sample)}</div>` : ""}
      `;
      folderModulesList.appendChild(item);
    });
  }

  // D. Dependencies Table
  const depsTbody = document.getElementById("analysis-deps-tbody");
  const depsCounter = document.getElementById("analysis-deps-counter");
  const deps = analysis.dependencies || [];
  if (depsCounter) depsCounter.textContent = `${deps.length} package(s) displayed`;
  if (depsTbody) {
    depsTbody.innerHTML = "";
    if (deps.length === 0) {
      depsTbody.innerHTML = `<tr><td colspan="4" style="text-align:center; color:#64748b; padding:16px;">No package dependencies discovered in manifests.</td></tr>`;
    } else {
      deps.forEach(d => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td><strong>${escapeHtml(d.name)}</strong></td>
          <td><code style="background:#f1f5f9; padding:2px 6px; border-radius:4px;">${escapeHtml(d.version || "*")}</code></td>
          <td><span class="github-tag-pill" style="font-size:10.5px;">${escapeHtml(d.type || "runtime")}</span></td>
          <td style="font-family:monospace; font-size:11.5px; color:#64748b;">${escapeHtml(d.source || "manifest")}</td>
        `;
        depsTbody.appendChild(tr);
      });
    }
  }

  // E. Instructions Panel
  const runInst = document.getElementById("analysis-run-instructions");
  const testInst = document.getElementById("analysis-test-instructions");
  const rinfo = analysis.run_instructions || {};
  const tinfo = analysis.test_info || {};

  if (runInst) {
    runInst.innerHTML = "";
    const installs = rinfo.install || [];
    const runs = rinfo.run || [];
    const builds = rinfo.build || [];

    if (installs.length > 0) {
      runInst.innerHTML += `<h4 style="margin:8px 0 4px; font-size:13px;">Installation</h4><div class="github-cmd-block">${escapeHtml(installs.join("\n"))}</div>`;
    }
    if (runs.length > 0) {
      runInst.innerHTML += `<h4 style="margin:12px 0 4px; font-size:13px;">Running & Execution</h4><div class="github-cmd-block">${escapeHtml(runs.join("\n"))}</div>`;
    }
    if (builds.length > 0) {
      runInst.innerHTML += `<h4 style="margin:12px 0 4px; font-size:13px;">Build</h4><div class="github-cmd-block">${escapeHtml(builds.join("\n"))}</div>`;
    }
    if (installs.length === 0 && runs.length === 0 && builds.length === 0) {
      runInst.innerHTML = `<div class="github-item-card-desc">No explicit installation or run commands found in README or manifests.</div>`;
    }
  }

  if (testInst) {
    testInst.innerHTML = "";
    const testDirs = tinfo.test_dirs || [];
    const testCount = tinfo.test_files_count || 0;
    const testCmds = rinfo.test || [];
    const sampleTests = tinfo.sample_test_files || [];

    testInst.innerHTML += `
      <div style="font-size:13px; margin-bottom:8px;">
        <strong>Test Status:</strong> ${tinfo.has_tests ? `✅ ${testCount} automated test file(s) discovered` : "⚠️ No test suite detected"}
      </div>
    `;
    if (testDirs.length > 0) {
      testInst.innerHTML += `<div style="font-size:12.5px; color:#64748b; margin-bottom:8px;">Test Directories: <code>${escapeHtml(testDirs.join(", "))}</code></div>`;
    }
    if (testCmds.length > 0) {
      testInst.innerHTML += `<h4 style="margin:8px 0 4px; font-size:13px;">Test Execution Command</h4><div class="github-cmd-block">${escapeHtml(testCmds.join("\n"))}</div>`;
    }
    if (sampleTests.length > 0) {
      testInst.innerHTML += `<h4 style="margin:10px 0 4px; font-size:13px;">Discovered Test Files</h4><div style="font-family:monospace; font-size:11.5px; color:#475569;">${sampleTests.map(s => escapeHtml(s)).join("<br>")}</div>`;
    }
  }

  // F. Findings & Observations Panel
  const obsList = document.getElementById("analysis-observations-list");
  const unknownsBox = document.getElementById("analysis-unknowns-box");
  const observations = analysis.observations || [];
  const unknowns = analysis.unknowns || {};

  if (obsList) {
    obsList.innerHTML = "";
    if (observations.length === 0) {
      obsList.innerHTML = `<div class="github-item-card-desc">No notable maintainability or configuration discrepancies detected.</div>`;
    } else {
      observations.forEach(o => {
        const item = document.createElement("div");
        item.className = "github-observation-item";
        item.innerHTML = `
          <div class="github-observation-header">
            <span>${escapeHtml(o.type || o.category || "Observation")}</span>
            <span class="github-badge" style="font-size:10px;">${escapeHtml(o.category || "General")}</span>
          </div>
          <div class="github-observation-desc">${escapeHtml(o.observation || o.description || "")}</div>
          ${o.path ? `<div style="font-family:monospace; font-size:11px; color:#64748b; margin-top:4px;">Reference: ${escapeHtml(o.path)}</div>` : ""}
        `;
        obsList.appendChild(item);
      });
    }
  }

  if (unknownsBox) {
    const skippedCnt = unknowns.skipped_files_count || 0;
    const skippedItems = unknowns.skipped_items_sample || [];
    unknownsBox.innerHTML = `
      <p style="margin:0 0 8px 0;"><strong>${skippedCnt} files/items</strong> were not inspected due to binary format, archive status, or file size limits.</p>
      <div style="font-size:12px; color:#64748b;">
        <strong>Excluded standard directories:</strong> <code>${(unknowns.excluded_directories || []).slice(0, 8).join(", ")}, ...</code>
      </div>
      ${skippedItems.length > 0 ? `
        <div style="margin-top:10px; font-size:11.5px; color:#64748b;">
          <strong>Sample Skipped Items:</strong><br>
          ${skippedItems.slice(0, 6).map(it => `• <code>${escapeHtml(it.path)}</code> (${escapeHtml(it.reason)})`).join("<br>")}
        </div>
      ` : ""}
    `;
  }

  // Activate first tab by default
  document.querySelector('.github-tab-btn[data-analysis-panel="panel-analysis-overview"]')?.click();
}

function renderFileTreeNode(node) {
  if (node.type === "dir") {
    const dirEl = document.createElement("div");
    dirEl.className = "tree-node-dir";
    const rowEl = document.createElement("div");
    rowEl.className = "tree-node-row tree-node-folder";
    rowEl.innerHTML = `<span>📁</span> <span>${escapeHtml(node.name)}</span>`;
    const childrenEl = document.createElement("div");
    childrenEl.className = "tree-node-children";
    if (node.children && node.children.length > 0) {
      node.children.forEach(c => childrenEl.appendChild(renderFileTreeNode(c)));
    }
    rowEl.addEventListener("click", () => {
      childrenEl.style.display = childrenEl.style.display === "none" ? "block" : "none";
    });
    dirEl.appendChild(rowEl);
    dirEl.appendChild(childrenEl);
    return dirEl;
  } else {
    const fileEl = document.createElement("div");
    fileEl.className = "tree-node-row tree-node-file";
    const sizeStr = node.size ? ` (${Math.round(node.size / 1024)} KB)` : "";
    const langBadge = node.language && node.language !== "Other" ? ` <span style="font-size:10px; color:#64748b; background:#e2e8f0; padding:1px 4px; border-radius:3px;">${escapeHtml(node.language)}</span>` : "";
    fileEl.innerHTML = `<span>📄</span> <span>${escapeHtml(node.name)}</span>${sizeStr}${langBadge}`;
    return fileEl;
  }
}

// ============================================================================
// AI Repository Chat & Grounded Retrieval (Milestone 9 - Prompt 3)
// ============================================================================

let githubChatReposList = [];
let currentChatRepoName = "";
let currentChatCommitSha = "";
let currentChatRepoId = null;
let currentChatSessionId = null;
let isChatSubmitting = false;

let currentWorkbenchRepo = "";
let currentWorkbenchSubnav = "overview";
let currentWorkbenchIssue = null;
let currentWorkbenchPR = null;
let currentWorkbenchRun = null;
let currentPendingApprovalAction = null;

function switchGithubSubnav(target) {
  const subnavKeys = ["overview", "repos", "analysis", "chat", "issues", "prs", "commits", "actions"];
  const viewMap = {
    overview: "github-workbench-overview-view",
    repos: "github-repos-main-view",
    analysis: "github-analysis-container",
    chat: "github-chat-container",
    issues: "github-workbench-issues-view",
    prs: "github-workbench-prs-view",
    commits: "github-workbench-commits-view",
    actions: "github-workbench-actions-view"
  };

  subnavKeys.forEach(k => {
    document.getElementById(`btn-github-subnav-${k}`)?.classList.toggle("active", k === target);
    const panel = document.getElementById(viewMap[k]);
    if (panel) panel.style.display = (k === target) ? "block" : "none";
  });

  currentWorkbenchSubnav = target;

  if (target === "overview") loadWorkbenchOverview(currentWorkbenchRepo);
  else if (target === "repos") filterAndRenderConnectedRepos();
  else if (target === "analysis") {
    if (currentWorkbenchRepo && typeof currentAnalysisRepoName !== "undefined"
        && (!currentAnalysisData || currentAnalysisRepoName !== currentWorkbenchRepo)) {
      const match = githubTrackedRepos.find(r => r.full_name === currentWorkbenchRepo);
      if (match) openRepositoryAnalysis(match.id, match.full_name, false);
    }
  }
  else if (target === "chat") loadAnalyzedReposForChat(currentWorkbenchRepo);
  else if (target === "issues") loadWorkbenchIssues(currentWorkbenchRepo);
  else if (target === "prs") loadWorkbenchPRs(currentWorkbenchRepo);
  else if (target === "commits") loadWorkbenchCommits(currentWorkbenchRepo);
  else if (target === "actions") loadWorkbenchActions(currentWorkbenchRepo);
}

async function loadAnalyzedReposForChat(preselectRepoName = null) {
  try {
    const res = await fetch("/api/github/chat/repos");
    const data = await res.json();
    if (!data.success) return;

    githubChatReposList = data.repositories || [];
    const select = document.getElementById("github-chat-repo-select");
    if (!select) return;

    const previousVal = preselectRepoName || select.value || currentChatRepoName;
    select.innerHTML = '<option value="">Select analyzed repository...</option>';

    githubChatReposList.forEach(r => {
      const opt = document.createElement("option");
      opt.value = r.repo_name;
      const statusSuffix = r.is_indexed ? ` (${r.chunks_count} chunks indexed)` : " (Not indexed)";
      opt.textContent = `${r.repo_name}${statusSuffix}`;
      select.appendChild(opt);
    });

    if (previousVal && githubChatReposList.some(r => r.repo_name === previousVal)) {
      select.value = previousVal;
      onChatRepositorySelected(previousVal);
    } else if (githubChatReposList.length === 1 && !select.value) {
      select.value = githubChatReposList[0].repo_name;
      onChatRepositorySelected(githubChatReposList[0].repo_name);
    } else {
      onChatRepositorySelected(select.value);
    }
  } catch (err) {
    console.error("Failed to load analyzed repos for chat:", err);
  }
}

async function onChatRepositorySelected(repoName) {
  currentChatRepoName = repoName || "";
  currentChatSessionId = null;

  const emptyState = document.getElementById("github-chat-empty-state");
  const noIndexState = document.getElementById("github-chat-noindex-state");
  const activeArea = document.getElementById("github-chat-active-area");
  const commitBadge = document.getElementById("github-chat-commit-badge");
  const indexedBadge = document.getElementById("github-chat-indexed-badge");
  const btnOpenAnalysis = document.getElementById("btn-github-chat-open-analysis");
  const staleBanner = document.getElementById("github-chat-stale-banner");

  if (staleBanner) staleBanner.style.display = "none";

  if (!repoName) {
    if (emptyState) emptyState.style.display = "flex";
    if (noIndexState) noIndexState.style.display = "none";
    if (activeArea) activeArea.style.display = "none";
    if (commitBadge) commitBadge.style.display = "none";
    if (indexedBadge) indexedBadge.style.display = "none";
    if (btnOpenAnalysis) btnOpenAnalysis.style.display = "none";
    return;
  }

  const repoData = githubChatReposList.find(r => r.repo_name === repoName);
  currentChatCommitSha = repoData?.commit_sha || "snapshot";
  currentChatRepoId = repoData?.repo_id || null;

  if (commitBadge) {
    commitBadge.style.display = "inline-flex";
    commitBadge.textContent = `Commit: ${currentChatCommitSha.slice(0, 8)}`;
  }

  if (btnOpenAnalysis) {
    btnOpenAnalysis.style.display = "inline-flex";
  }

  if (!repoData || !repoData.is_indexed) {
    if (emptyState) emptyState.style.display = "none";
    if (noIndexState) noIndexState.style.display = "flex";
    if (activeArea) activeArea.style.display = "none";
    if (indexedBadge) indexedBadge.style.display = "none";
    return;
  }

  if (indexedBadge) {
    indexedBadge.style.display = "inline-flex";
    indexedBadge.textContent = `Indexed (${repoData.chunks_count} chunks)`;
  }

  if (emptyState) emptyState.style.display = "none";
  if (noIndexState) noIndexState.style.display = "none";
  if (activeArea) activeArea.style.display = "flex";

  // Load chat history for this repository
  await loadRepoChatHistory(repoName);
}

async function loadRepoChatHistory(repoName) {
  const messagesContainer = document.getElementById("github-chat-messages");
  if (!messagesContainer) return;
  messagesContainer.innerHTML = '<div style="color:#94a3b8; font-size:12px; text-align:center; padding:12px;">Loading chat history...</div>';

  try {
    const res = await fetch(`/api/github/chat/history?repo_name=${encodeURIComponent(repoName)}`);
    const data = await res.json();
    messagesContainer.innerHTML = "";

    const messages = data.messages || [];
    if (data.session_id) {
      currentChatSessionId = data.session_id;
    }

    if (messages.length === 0) {
      messagesContainer.innerHTML = `
        <div style="text-align:center; padding:24px 12px; color:#64748b;">
          <div style="font-size:24px; margin-bottom:8px;">💡</div>
          <p style="margin:0 0 4px; font-weight:600; color:#334155;">Ready to explore ${escapeHtml(repoName)}</p>
          <p style="margin:0; font-size:12px; color:#94a3b8;">Ask questions about implementation details, architecture, endpoints, or run commands.</p>
        </div>
      `;
      return;
    }

    messages.forEach(msg => {
      appendChatMessageToUI(msg.role, msg.content, msg.sources || [], msg.created_at, msg.commit_sha, msg.is_stale);
    });
    scrollChatToBottom();
  } catch (err) {
    console.error("Failed to load chat history:", err);
    messagesContainer.innerHTML = '<div style="color:#ef4444; font-size:12px; text-align:center; padding:12px;">Failed to load chat history.</div>';
  }
}

async function sendRepositoryChatMessage(overrideQuestion = null) {
  if (isChatSubmitting) return;

  const inputEl = document.getElementById("github-chat-input");
  const question = (overrideQuestion || inputEl?.value || "").trim();
  if (!question) return;

  if (!currentChatRepoName) {
    showSystemToast("Please select an analyzed repository first.");
    return;
  }

  isChatSubmitting = true;
  if (inputEl) inputEl.value = "";

  // Append user message to UI immediately
  appendChatMessageToUI("user", question, [], new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), currentChatCommitSha);
  scrollChatToBottom();

  // Show inline loader
  const loader = document.getElementById("github-chat-loading");
  if (loader) loader.style.display = "flex";

  try {
    const res = await fetch("/api/github/chat/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo_name: currentChatRepoName,
        commit_sha: currentChatCommitSha,
        repo_id: currentChatRepoId,
        session_id: currentChatSessionId,
        message: question,
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      throw new Error(data.detail || "Query failed");
    }

    if (data.session_id) {
      currentChatSessionId = data.session_id;
    }

    // Handle stale commit warning
    const staleBanner = document.getElementById("github-chat-stale-banner");
    const staleText = document.getElementById("github-chat-stale-text");
    if (data.is_stale && data.warning) {
      if (staleBanner) staleBanner.style.display = "flex";
      if (staleText) staleText.textContent = data.warning;
    } else {
      if (staleBanner) staleBanner.style.display = "none";
    }

    // Append assistant response
    appendChatMessageToUI("assistant", data.answer, data.sources || [], new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }), data.commit_sha, data.is_stale);
    scrollChatToBottom();
  } catch (err) {
    appendChatMessageToUI("assistant", `❌ Error answering question: ${err.message}`, [], new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    scrollChatToBottom();
  } finally {
    isChatSubmitting = false;
    if (loader) loader.style.display = "none";
  }
}

function appendChatMessageToUI(role, content, sources = [], timestamp = "", commitSha = "", isStale = false) {
  const container = document.getElementById("github-chat-messages");
  if (!container) return;

  const msgEl = document.createElement("div");
  msgEl.className = `github-chat-msg ${role}`;

  const timeLabel = timestamp || new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const roleLabel = role === "user" ? "You" : "Repository AI";
  const staleChip = isStale ? `<span style="color:#d97706; font-size:10.5px; margin-left:6px;">(Stale Commit)</span>` : "";

  let sourcesHtml = "";
  if (sources && sources.length > 0) {
    const itemsHtml = sources.map((src, idx) => {
      const codeSnippet = src.code_snippet || src.content || "";
      const linesLabel = src.start_line ? `L${src.start_line}-L${src.end_line}` : "";
      return `
        <div class="github-citation-item">
          <div class="github-citation-header">
            <span>📄 ${escapeHtml(src.file_path)} <span style="color:#64748b; font-weight:normal;">${escapeHtml(linesLabel)}</span></span>
            <span style="font-size:10px; color:#94a3b8;">#${idx + 1}</span>
          </div>
          ${codeSnippet ? `<div class="github-citation-code">${escapeHtml(codeSnippet.slice(0, 300))}</div>` : ""}
        </div>
      `;
    }).join("");

    sourcesHtml = `
      <div class="github-citations-box">
        <div class="github-citations-toggle" onclick="this.nextElementSibling.style.display = this.nextElementSibling.style.display === 'none' ? 'flex' : 'none';">
          <span>📎 Sources / Citations (${sources.length})</span>
          <span style="font-size:10px;">▾</span>
        </div>
        <div class="github-citations-list" style="display:none;">
          ${itemsHtml}
        </div>
      </div>
    `;
  }

  // Format content using formatMarkdown
  const formattedBody = formatMarkdown(content);

  msgEl.innerHTML = `
    <div class="github-msg-meta">
      <strong>${escapeHtml(roleLabel)}</strong> • <span>${escapeHtml(timeLabel)}</span>${staleChip}
    </div>
    <div class="github-msg-body">
      ${formattedBody}
    </div>
    ${sourcesHtml}
  `;

  // Attach code copy listeners inside markdown
  msgEl.querySelectorAll(".btn-copy-code").forEach(btn => {
    btn.addEventListener("click", () => {
      const code = btn.closest(".code-block-container")?.querySelector("pre code")?.textContent || "";
      navigator.clipboard.writeText(code).then(() => {
        btn.textContent = "Copied!";
        setTimeout(() => { btn.textContent = "Copy"; }, 2000);
      });
    });
  });

  container.appendChild(msgEl);
}

function scrollChatToBottom() {
  const container = document.getElementById("github-chat-messages");
  if (container) {
    container.scrollTop = container.scrollHeight;
  }
}

async function startNewRepoChatSession() {
  if (!currentChatRepoName) {
    showSystemToast("Select a repository first.");
    return;
  }
  try {
    const res = await fetch("/api/github/chat/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo_name: currentChatRepoName,
        commit_sha: currentChatCommitSha,
        repo_id: currentChatRepoId,
      }),
    });
    const data = await res.json();
    if (data.session_id) {
      currentChatSessionId = data.session_id;
    }
    const container = document.getElementById("github-chat-messages");
    if (container) {
      container.innerHTML = `
        <div style="text-align:center; padding:24px 12px; color:#64748b;">
          <div style="font-size:24px; margin-bottom:8px;">✨</div>
          <p style="margin:0 0 4px; font-weight:600; color:#334155;">New Chat Session Started</p>
          <p style="margin:0; font-size:12px; color:#94a3b8;">Ask questions grounded in commit <code>${escapeHtml(currentChatCommitSha.slice(0, 8))}</code>.</p>
        </div>
      `;
    }
    showSystemToast("Started new chat session.");
  } catch (err) {
    console.error("Failed to start new chat session:", err);
  }
}

async function clearRepoChatHistory() {
  if (!currentChatRepoName) return;
  if (!confirm(`Are you sure you want to clear chat history for ${currentChatRepoName}?`)) {
    return;
  }
  try {
    await fetch("/api/github/chat/clear", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        repo_name: currentChatRepoName,
        session_id: currentChatSessionId,
      }),
    });
    currentChatSessionId = null;
    const container = document.getElementById("github-chat-messages");
    if (container) {
      container.innerHTML = `
        <div style="text-align:center; padding:24px 12px; color:#64748b;">
          <div style="font-size:24px; margin-bottom:8px;">🗑</div>
          <p style="margin:0 0 4px; font-weight:600; color:#334155;">Chat History Cleared</p>
          <p style="margin:0; font-size:12px; color:#94a3b8;">Ask a question to begin a new grounded conversation.</p>
        </div>
      `;
    }
    showSystemToast("Chat history cleared.");
  } catch (err) {
    console.error("Failed to clear chat history:", err);
  }
}

function initGithubChat() {
  // Subnav switching
  document.getElementById("btn-github-subnav-repos")?.addEventListener("click", () => switchGithubSubnav("repos"));
  document.getElementById("btn-github-subnav-chat")?.addEventListener("click", () => switchGithubSubnav("chat"));

  // Repository dropdown selector
  document.getElementById("github-chat-repo-select")?.addEventListener("change", (e) => {
    onChatRepositorySelected(e.target.value);
  });

  // Action buttons
  document.getElementById("btn-github-chat-new")?.addEventListener("click", startNewRepoChatSession);
  document.getElementById("btn-github-chat-clear")?.addEventListener("click", clearRepoChatHistory);

  // Send button and enter key
  document.getElementById("btn-github-chat-send")?.addEventListener("click", () => sendRepositoryChatMessage());
  document.getElementById("github-chat-input")?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendRepositoryChatMessage();
    }
  });

  // Suggested prompt chips
  document.querySelectorAll(".github-prompt-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const query = chip.getAttribute("data-query");
      if (query) {
        sendRepositoryChatMessage(query);
      }
    });
  });

  // Re-analyze triggers when stale or unindexed
  const triggerReanalyze = () => {
    if (currentChatRepoId) {
      switchGithubSubnav("repos");
      openRepositoryAnalysis(currentChatRepoId, currentChatRepoName, true);
    } else {
      showSystemToast("ZIP snapshot analyses are static. Please re-upload archive to re-index.");
    }
  };
  document.getElementById("btn-github-chat-reanalyze")?.addEventListener("click", triggerReanalyze);
  document.getElementById("btn-github-chat-trigger-analyze")?.addEventListener("click", triggerReanalyze);

  // Open Analysis button
  document.getElementById("btn-github-chat-open-analysis")?.addEventListener("click", () => {
    if (currentChatRepoId) {
      switchGithubSubnav("repos");
      openRepositoryAnalysis(currentChatRepoId, currentChatRepoName, false);
    }
  });
}



// ============================================================================
// Developer Workbench & Safe Automation (Milestone 9 - Prompt 4)
// ============================================================================

function debounce(fn, delay) {
  let timer;
  return function(...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

function updateWorkbenchGlobalRepoSelect() {
  const select = document.getElementById("github-global-repo-select");
  if (!select) return;
  const prevValue = select.value || currentWorkbenchRepo;
  select.innerHTML = '<option value="">Select active repository...</option>';
  githubTrackedRepos.forEach(repo => {
    const opt = document.createElement("option");
    opt.value = repo.full_name;
    opt.textContent = `${repo.full_name} (${repo.private ? "Private" : "Public"})`;
    select.appendChild(opt);
  });
  if (prevValue && githubTrackedRepos.some(r => r.full_name === prevValue)) {
    select.value = prevValue; currentWorkbenchRepo = prevValue;
  } else if (githubTrackedRepos.length > 0) {
    select.value = githubTrackedRepos[0].full_name;
    currentWorkbenchRepo = githubTrackedRepos[0].full_name;
  } else { select.value = ""; currentWorkbenchRepo = ""; }
}

// ---------- Safety Approval Modal ----------
function openGithubApprovalModal({ action, title, description, risk, previewHtml, onConfirm }) {
  const modal = document.getElementById("github-approval-modal");
  const titleEl = document.getElementById("github-modal-title");
  const descEl = document.getElementById("github-modal-desc");
  const riskBadge = document.getElementById("github-modal-risk-badge");
  const previewCard = document.getElementById("github-modal-preview");
  if (!modal) return;
  if (titleEl) titleEl.textContent = title || "Approve GitHub Action";
  if (descEl) descEl.textContent = description || "Review the action preview below.";
  if (riskBadge) {
    riskBadge.textContent = (risk || "MEDIUM RISK").toUpperCase();
    riskBadge.className = `risk-badge ${risk === "high" ? "risk-high" : "risk-medium"}`;
  }
  if (previewCard) previewCard.innerHTML = previewHtml || "";
  currentPendingApprovalAction = onConfirm;
  modal.classList.remove("hidden");
}

function closeGithubApprovalModal() {
  const modal = document.getElementById("github-approval-modal");
  if (modal) modal.classList.add("hidden");
  currentPendingApprovalAction = null;
}

// ---------- 1. Overview ----------
async function loadWorkbenchOverview(repoName) {
  const emptyEl = document.getElementById("github-overview-empty");
  const contentEl = document.getElementById("github-overview-content");
  if (!repoName) {
    if (emptyEl) emptyEl.style.display = "flex";
    if (contentEl) contentEl.style.display = "none";
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";
  if (contentEl) contentEl.style.display = "block";
  try {
    const res = await fetch(`/api/github/workbench/overview?repo_name=${encodeURIComponent(repoName)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    const rn = document.getElementById("overview-repo-name");
    const rd = document.getElementById("overview-repo-desc");
    const bb = document.getElementById("overview-branch-badge");
    const vb = document.getElementById("overview-visibility-badge");
    const gl = document.getElementById("overview-github-link");
    if (rn) rn.textContent = data.repo_name || repoName;
    if (rd) rd.textContent = data.description || "No description.";
    if (bb) bb.textContent = `Default: ${data.default_branch || "main"}`;
    if (vb) vb.textContent = data.private ? "Private" : "Public";
    if (gl) gl.href = data.html_url || `https://github.com/${repoName}`;
    const si = document.getElementById("overview-stat-issues");
    const sp = document.getElementById("overview-stat-prs");
    const sb = document.getElementById("overview-stat-branches");
    const sf = document.getElementById("overview-stat-failures");
    if (si) si.textContent = data.open_issues_count ?? 0;
    if (sp) sp.textContent = data.open_prs_count ?? 0;
    if (sb) sb.textContent = data.branches_count ?? 0;
    if (sf) {
      sf.textContent = data.workflow_failures_count ?? 0;
      sf.style.color = (data.workflow_failures_count > 0) ? "#ef4444" : "#10b981";
    }
    // Recent commits
    const cb = document.getElementById("overview-recent-commits-list");
    if (cb) {
      cb.innerHTML = "";
      const commits = data.recent_commits || [];
      if (!commits.length) {
        cb.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:8px 0;">No recent commits.</div>';
      } else {
        commits.slice(0, 5).forEach(c => {
          const d = document.createElement("div");
          d.className = "github-item-card"; d.style.padding = "8px 12px";
          d.innerHTML = `<div style="display:flex;justify-content:space-between;"><span style="font-family:monospace;font-weight:600;font-size:12px;color:#2563eb;">${escapeHtml((c.sha||"").slice(0,7))}</span><span style="font-size:11px;color:#94a3b8;">${escapeHtml(c.date||"")}</span></div><div style="font-size:12.5px;font-weight:500;margin-top:2px;">${escapeHtml(c.message||"")}</div><div style="font-size:11px;color:#64748b;margin-top:2px;">by ${escapeHtml(c.author||"Unknown")}</div>`;
          cb.appendChild(d);
        });
      }
    }
    // Recent workflow runs
    const ab = document.getElementById("overview-recent-actions-list");
    if (ab) {
      ab.innerHTML = "";
      const runs = data.recent_workflows || [];
      if (!runs.length) {
        ab.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:8px 0;">No workflow runs.</div>';
      } else {
        runs.slice(0, 5).forEach(r => {
          const d = document.createElement("div");
          d.className = "github-item-card"; d.style.padding = "8px 12px";
          const cls = r.conclusion === "success" ? "github-badge-success" : (r.conclusion === "failure" ? "github-badge-danger" : "github-badge-warn");
          d.innerHTML = `<div style="display:flex;justify-content:space-between;"><span style="font-weight:600;font-size:12.5px;">${escapeHtml(r.name||"Workflow")}</span><span class="github-badge ${cls}" style="font-size:10.5px;">${escapeHtml(r.conclusion||r.status||"queued")}</span></div><div style="font-size:11.5px;color:#64748b;margin-top:2px;">Branch: <code>${escapeHtml(r.branch||"main")}</code> &bull; SHA: <code>${escapeHtml(r.commit_sha||"")}</code></div>`;
          ab.appendChild(d);
        });
      }
    }
  } catch (err) { console.error("Overview load error:", err); }
}

// ---------- 2. Issues ----------
let loadedWorkbenchIssues = [];

async function loadWorkbenchIssues(repoName) {
  const emptyEl = document.getElementById("github-issues-empty-prompt");
  const contentEl = document.getElementById("github-issues-active-content");
  if (!repoName) {
    if (emptyEl) emptyEl.style.display = "flex";
    if (contentEl) contentEl.style.display = "none";
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";
  if (contentEl) contentEl.style.display = "block";
  const loader = document.getElementById("github-issues-loading");
  const lc = document.getElementById("github-issues-list-container");
  const state = document.getElementById("github-issues-state-select")?.value || "open";
  const q = document.getElementById("github-issues-search-input")?.value || "";
  if (loader) loader.style.display = "flex";
  if (lc) lc.innerHTML = "";
  try {
    const res = await fetch(`/api/github/workbench/issues?repo_name=${encodeURIComponent(repoName)}&state=${encodeURIComponent(state)}&q=${encodeURIComponent(q)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    loadedWorkbenchIssues = data.issues || [];
    renderWorkbenchIssuesList();
  } catch (err) {
    if (lc) lc.innerHTML = `<div style="color:#ef4444;font-size:12px;padding:12px;">Error: ${escapeHtml(err.message)}</div>`;
  } finally { if (loader) loader.style.display = "none"; }
}

function renderWorkbenchIssuesList() {
  const lc = document.getElementById("github-issues-list-container");
  if (!lc) return;
  lc.innerHTML = "";
  if (!loadedWorkbenchIssues.length) {
    lc.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:24px 12px;text-align:center;">No issues found.</div>';
    return;
  }
  loadedWorkbenchIssues.forEach(issue => {
    const card = document.createElement("div");
    card.className = "github-workbench-item-card";
    if (currentWorkbenchIssue && currentWorkbenchIssue.number === issue.number) card.classList.add("active");
    const labelsHtml = (issue.labels||[]).map(l => `<span class="github-badge" style="background:#e0f2fe;color:#0369a1;font-size:10px;padding:1px 6px;">${escapeHtml(l)}</span>`).join(" ");
    const isOpen = issue.state === "open";
    card.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;"><span style="font-weight:600;font-size:13px;">#${issue.number} ${escapeHtml(issue.title)}</span><span class="github-badge ${isOpen?"github-badge-success":"github-badge-danger"}" style="font-size:10px;">${isOpen?"Open":"Closed"}</span></div><div style="margin:6px 0 4px;display:flex;flex-wrap:wrap;gap:4px;">${labelsHtml}</div><div class="github-meta-sub" style="font-size:11px;">By ${escapeHtml(issue.author||"Unknown")} &bull; &#x1F4AC; ${issue.comments_count||0} &bull; ${escapeHtml(issue.updated_at||"")}</div>`;
    card.addEventListener("click", () => selectWorkbenchIssue(issue.number));
    lc.appendChild(card);
  });
}

async function selectWorkbenchIssue(issueNumber) {
  const placeholder = document.getElementById("github-issue-placeholder");
  const sel = document.getElementById("github-issue-selected-content");
  const aiBox = document.getElementById("issue-ai-box");
  if (placeholder) placeholder.style.display = "none";
  if (sel) sel.style.display = "block";
  if (aiBox) aiBox.style.display = "none";
  document.querySelectorAll("#github-issues-list-container .github-workbench-item-card").forEach(el => el.classList.remove("active"));
  try {
    const res = await fetch(`/api/github/workbench/issues/${issueNumber}?repo_name=${encodeURIComponent(currentWorkbenchRepo)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    currentWorkbenchIssue = data;
    const idt = document.getElementById("issue-detail-title");
    const idm = document.getElementById("issue-detail-meta");
    const idb_el = document.getElementById("issue-detail-state-badge");
    const tb = document.getElementById("btn-issue-toggle-state");
    if (idt) idt.textContent = `#${data.number} ${data.title}`;
    if (idm) idm.textContent = `Opened by ${data.author||"Unknown"} on ${data.created_at||"recently"}`;
    if (idb_el) { idb_el.textContent = data.state==="open"?"Open":"Closed"; idb_el.className=`github-badge ${data.state==="open"?"github-badge-success":"github-badge-danger"}`; }
    if (tb) tb.textContent = data.state==="open" ? "Close Issue" : "Reopen Issue";
    const bodyEl = document.getElementById("issue-detail-body");
    if (bodyEl) bodyEl.innerHTML = data.body ? formatMarkdown(data.body) : '<span style="color:#94a3b8;font-style:italic;">No description.</span>';
    const comments = data.comments || [];
    const cc = document.getElementById("issue-comments-counter");
    const cf = document.getElementById("issue-comments-feed");
    if (cc) cc.textContent = comments.length;
    if (cf) {
      cf.innerHTML = "";
      if (!comments.length) {
        cf.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:8px 0;">No comments.</div>';
      } else {
        comments.forEach(c => {
          const d = document.createElement("div");
          d.className = "github-comment-item";
          d.innerHTML = `<div class="github-comment-header"><strong>${escapeHtml(c.author||"User")}</strong> on ${escapeHtml(c.created_at||"")}</div><div class="github-comment-body">${formatMarkdown(c.body||"")}</div>`;
          cf.appendChild(d);
        });
      }
    }
  } catch (err) { showSystemToast("Error loading issue: " + err.message); }
}

async function runIssueAIInvestigation() {
  if (!currentWorkbenchIssue || !currentWorkbenchRepo) return;
  const btn = document.getElementById("btn-issue-ai-investigate");
  const aiBox = document.getElementById("issue-ai-box");
  const se = document.getElementById("issue-ai-summary");
  const ste = document.getElementById("issue-ai-steps");
  const de = document.getElementById("issue-ai-duplicates");
  if (btn) { btn.disabled = true; btn.textContent = "Analyzing..."; }
  try {
    const res = await fetch(`/api/github/workbench/issues/${currentWorkbenchIssue.number}/summarize`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({repo_name: currentWorkbenchRepo})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "AI analysis failed");
    if (aiBox) aiBox.style.display = "block";
    if (se) se.innerHTML = formatMarkdown(data.summary || "");
    if (ste) {
      const steps = data.investigation_steps || [];
      ste.innerHTML = steps.length ? `<strong style="display:block;margin-bottom:4px;font-size:12px;">Investigation Steps:</strong><ul style="margin:0;padding-left:18px;font-size:12px;">${steps.map(s=>`<li>${escapeHtml(s)}</li>`).join("")}</ul>` : "";
    }
    if (de) {
      const dups = data.potential_duplicates || [];
      de.innerHTML = dups.length ? `<div class="github-alert-notice" style="margin-top:8px;">&#x1F50D; <strong>Possible Duplicates (suggestions only):</strong><ul style="margin:4px 0 0;padding-left:18px;">${dups.map(d=>`<li>#${d.number} ${escapeHtml(d.title)} (${escapeHtml(d.state)})</li>`).join("")}</ul></div>` : "";
    }
  } catch (err) { showSystemToast("AI error: " + err.message); }
  finally { if (btn) { btn.disabled = false; btn.textContent = "\u2728 AI Investigation"; } }
}

function handleToggleIssueState() {
  if (!currentWorkbenchIssue || !currentWorkbenchRepo) return;
  const nextState = currentWorkbenchIssue.state === "open" ? "closed" : "open";
  const actionLabel = nextState === "closed" ? "Close Issue" : "Reopen Issue";
  openGithubApprovalModal({
    action: "github_update_issue", title: `Approve: ${actionLabel}`,
    description: `Confirm updating issue #${currentWorkbenchIssue.number}.`, risk: "medium",
    previewHtml: `<div style="font-size:12.5px;line-height:1.5;"><p><strong>Repo:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p><p><strong>Issue:</strong> #${currentWorkbenchIssue.number} &mdash; ${escapeHtml(currentWorkbenchIssue.title)}</p><p><strong>Action:</strong> <span style="font-weight:600;">${actionLabel}</span></p></div>`,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch(`/api/github/workbench/issues/${currentWorkbenchIssue.number}/update`, {
          method: "POST", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({repo_name: currentWorkbenchRepo, state: nextState, approved: true})
        });
        if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed"); }
        showSystemToast(`Issue #${currentWorkbenchIssue.number} ${nextState}.`);
        await loadWorkbenchIssues(currentWorkbenchRepo);
        await selectWorkbenchIssue(currentWorkbenchIssue.number);
      } catch (err) { showSystemToast("Update failed: " + err.message); }
    }
  });
}

function handleAddIssueComment() {
  if (!currentWorkbenchIssue || !currentWorkbenchRepo) return;
  const textarea = document.getElementById("issue-comment-textarea");
  const body = (textarea?.value || "").trim();
  if (!body) { showSystemToast("Enter a comment."); return; }
  openGithubApprovalModal({
    action: "github_add_issue_comment", title: "Approve: Post Comment",
    description: `Post comment on issue #${currentWorkbenchIssue.number}.`, risk: "medium",
    previewHtml: `<div style="font-size:12.5px;"><p><strong>Repo:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p><p><strong>Issue:</strong> #${currentWorkbenchIssue.number}</p><div style="max-height:120px;overflow-y:auto;padding:8px 10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;font-size:12px;white-space:pre-wrap;">${escapeHtml(body)}</div></div>`,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch(`/api/github/workbench/issues/${currentWorkbenchIssue.number}/comment`, {
          method: "POST", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({repo_name: currentWorkbenchRepo, body, approved: true})
        });
        if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed"); }
        if (textarea) textarea.value = "";
        showSystemToast("Comment posted.");
        await selectWorkbenchIssue(currentWorkbenchIssue.number);
      } catch (err) { showSystemToast("Failed: " + err.message); }
    }
  });
}

function handleCreateNewIssue() {
  if (!currentWorkbenchRepo) { showSystemToast("Select a repository first."); return; }
  document.getElementById("github-create-issue-modal")?.classList.remove("hidden");
}

function submitNewIssueFromModal() {
  const title = (document.getElementById("modal-issue-title-input")?.value || "").trim();
  const body = (document.getElementById("modal-issue-body-textarea")?.value || "").trim();
  const labelsRaw = (document.getElementById("modal-issue-labels-input")?.value || "").trim();
  const labels = labelsRaw ? labelsRaw.split(",").map(l => l.trim()).filter(Boolean) : [];
  if (!title) { showSystemToast("Issue title required."); return; }
  document.getElementById("github-create-issue-modal")?.classList.add("hidden");
  openGithubApprovalModal({
    action: "github_create_issue", title: "Approve: Create New Issue",
    description: `Create new issue on ${currentWorkbenchRepo}.`, risk: "medium",
    previewHtml: `<div style="font-size:12.5px;"><p><strong>Repo:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p><p><strong>Title:</strong> ${escapeHtml(title)}</p><p><strong>Labels:</strong> ${labels.length ? labels.map(l=>`<code>${escapeHtml(l)}</code>`).join(" ") : "None"}</p></div>`,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch("/api/github/workbench/issues/create", {
          method: "POST", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({repo_name: currentWorkbenchRepo, title, body, labels, approved: true})
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed");
        document.getElementById("modal-issue-title-input").value = "";
        document.getElementById("modal-issue-body-textarea").value = "";
        document.getElementById("modal-issue-labels-input").value = "";
        showSystemToast(`Created issue #${data.number || ""}`);
        await loadWorkbenchIssues(currentWorkbenchRepo);
      } catch (err) { showSystemToast("Create failed: " + err.message); }
    }
  });
}

// ---------- 3. Pull Requests ----------
let loadedWorkbenchPRs = [];

async function loadWorkbenchPRs(repoName) {
  const emptyEl = document.getElementById("github-prs-empty-prompt");
  const contentEl = document.getElementById("github-prs-active-content");
  if (!repoName) {
    if (emptyEl) emptyEl.style.display = "flex";
    if (contentEl) contentEl.style.display = "none";
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";
  if (contentEl) contentEl.style.display = "block";
  const loader = document.getElementById("github-prs-loading");
  const lc = document.getElementById("github-prs-list-container");
  const state = document.getElementById("github-prs-state-select")?.value || "open";
  if (loader) loader.style.display = "flex";
  if (lc) lc.innerHTML = "";
  try {
    const res = await fetch(`/api/github/workbench/prs?repo_name=${encodeURIComponent(repoName)}&state=${encodeURIComponent(state)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    loadedWorkbenchPRs = data.pull_requests || [];
    renderWorkbenchPRsList();
  } catch (err) {
    if (lc) lc.innerHTML = `<div style="color:#ef4444;font-size:12px;padding:12px;">Error: ${escapeHtml(err.message)}</div>`;
  } finally { if (loader) loader.style.display = "none"; }
}

function renderWorkbenchPRsList() {
  const lc = document.getElementById("github-prs-list-container");
  if (!lc) return;
  lc.innerHTML = "";
  if (!loadedWorkbenchPRs.length) {
    lc.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:24px 12px;text-align:center;">No PRs found.</div>';
    return;
  }
  loadedWorkbenchPRs.forEach(pr => {
    const card = document.createElement("div");
    card.className = "github-workbench-item-card";
    if (currentWorkbenchPR && currentWorkbenchPR.number === pr.number) card.classList.add("active");
    const isOpen = pr.state === "open";
    card.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;"><span style="font-weight:600;font-size:13px;">#${pr.number} ${escapeHtml(pr.title)}</span><span class="github-badge ${isOpen?"github-badge-success":"github-badge-danger"}" style="font-size:10px;">${isOpen?"Open":"Closed"}</span></div><div style="font-size:11px;font-family:monospace;color:#475569;margin:4px 0;">${escapeHtml(pr.head_branch||"branch")} &rarr; ${escapeHtml(pr.base_branch||"main")}</div><div class="github-meta-sub" style="font-size:11px;">By ${escapeHtml(pr.author||"Unknown")} &bull; ${escapeHtml(pr.updated_at||"")}</div>`;
    card.addEventListener("click", () => selectWorkbenchPR(pr.number));
    lc.appendChild(card);
  });
}

async function selectWorkbenchPR(prNumber) {
  const placeholder = document.getElementById("github-pr-placeholder");
  const sel = document.getElementById("github-pr-selected-content");
  const aiBox = document.getElementById("pr-ai-box");
  if (placeholder) placeholder.style.display = "none";
  if (sel) sel.style.display = "block";
  if (aiBox) aiBox.style.display = "none";
  document.querySelectorAll("#github-prs-list-container .github-workbench-item-card").forEach(el => el.classList.remove("active"));
  try {
    const [prRes, diffRes] = await Promise.all([
      fetch(`/api/github/workbench/prs/${prNumber}?repo_name=${encodeURIComponent(currentWorkbenchRepo)}`),
      fetch(`/api/github/workbench/prs/${prNumber}/diff?repo_name=${encodeURIComponent(currentWorkbenchRepo)}`)
    ]);
    const prData = await prRes.json();
    const diffData = await diffRes.json();
    if (!prRes.ok) throw new Error(prData.detail || "Failed");
    currentWorkbenchPR = prData;
    const pdt = document.getElementById("pr-detail-title");
    const pdb = document.getElementById("pr-detail-branches");
    const pdm = document.getElementById("pr-detail-meta");
    const pds = document.getElementById("pr-detail-state-badge");
    if (pdt) pdt.textContent = `#${prData.number} ${prData.title}`;
    if (pdb) pdb.textContent = `${prData.head_branch||"branch"} \u2192 ${prData.base_branch||"main"}`;
    if (pdm) pdm.textContent = `By ${prData.author||"Unknown"} \u2022 +${prData.additions||0}/-${prData.deletions||0} \u2022 ${prData.changed_files_count||0} files`;
    if (pds) { pds.textContent = prData.state==="open"?"Open":"Closed"; pds.className=`github-badge ${prData.state==="open"?"github-badge-success":"github-badge-danger"}`; }
    // Files
    const files = diffData.files || [];
    const pfc = document.getElementById("pr-files-counter");
    const pfl = document.getElementById("pr-files-list");
    if (pfc) pfc.textContent = files.length;
    if (pfl) {
      pfl.innerHTML = "";
      files.forEach(f => {
        const d = document.createElement("div");
        d.className = "github-item-card"; d.style.padding = "6px 10px";
        d.innerHTML = `<div style="display:flex;justify-content:space-between;font-size:12px;"><span style="font-family:monospace;font-weight:600;">${escapeHtml(f.filename)}</span><span style="font-size:11px;color:#64748b;">+${f.additions}/-${f.deletions} (${f.status})</span></div>`;
        pfl.appendChild(d);
      });
    }
    // Diff viewer
    const dv = document.getElementById("pr-diff-viewer");
    if (dv) {
      const rawDiff = diffData.diff_preview || "";
      if (!rawDiff) { dv.textContent = "No diff available."; }
      else {
        dv.innerHTML = rawDiff.split("\n").slice(0, 1500).map(line => {
          const esc = escapeHtml(line);
          if (line.startsWith("+++") || line.startsWith("---")) return `<div style="color:#64748b;font-weight:600;">${esc}</div>`;
          if (line.startsWith("+")) return `<div class="github-diff-add">${esc}</div>`;
          if (line.startsWith("-")) return `<div class="github-diff-del">${esc}</div>`;
          if (line.startsWith("@@")) return `<div class="github-diff-chunk-header">${esc}</div>`;
          if (line.startsWith("diff --git")) return `<div style="color:#2563eb;font-weight:700;margin-top:8px;">${esc}</div>`;
          return `<div>${esc}</div>`;
        }).join("");
      }
    }
  } catch (err) { showSystemToast("Error loading PR: " + err.message); }
}

async function runPRAICodeReview() {
  if (!currentWorkbenchPR || !currentWorkbenchRepo) return;
  const btn = document.getElementById("btn-pr-ai-review");
  const aiBox = document.getElementById("pr-ai-box");
  const se = document.getElementById("pr-ai-summary");
  const oe = document.getElementById("pr-ai-observations");
  if (btn) { btn.disabled = true; btn.textContent = "Reviewing..."; }
  try {
    const res = await fetch(`/api/github/workbench/prs/${currentWorkbenchPR.number}/review`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({repo_name: currentWorkbenchRepo})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "AI review failed");
    if (aiBox) aiBox.style.display = "block";
    if (se) se.innerHTML = formatMarkdown(data.summary || "");
    if (oe) {
      oe.innerHTML = "";
      const findings = data.observations || [];
      if (!findings.length) {
        oe.innerHTML = '<div style="color:#10b981;font-size:12px;padding:6px 0;">\u2705 No critical issues found in diff.</div>';
      } else {
        findings.forEach(f => {
          const d = document.createElement("div");
          d.className = "github-observation-item";
          const sev = f.severity || "medium";
          const cls = sev==="high"?"github-badge-danger":(sev==="medium"?"github-badge-warn":"github-badge-success");
          d.innerHTML = `<div class="github-observation-header"><div style="display:flex;align-items:center;gap:6px;"><span class="github-badge ${cls}" style="font-size:10px;">${escapeHtml(sev.toUpperCase())}</span><span style="font-weight:600;font-size:12.5px;">${escapeHtml(f.category||"General")}</span></div><span style="font-size:11px;font-family:monospace;color:#475569;">${escapeHtml(f.file||"")}</span></div><div class="github-observation-desc" style="margin-top:4px;">${escapeHtml(f.observation||"")}</div>`;
          oe.appendChild(d);
        });
      }
    }
  } catch (err) { showSystemToast("Review error: " + err.message); }
  finally { if (btn) { btn.disabled = false; btn.textContent = "\u2728 AI Review"; } }
}

function handleAddPRComment() {
  if (!currentWorkbenchPR || !currentWorkbenchRepo) return;
  const textarea = document.getElementById("pr-comment-textarea");
  const body = (textarea?.value || "").trim();
  if (!body) { showSystemToast("Enter a review comment."); return; }
  openGithubApprovalModal({
    action: "github_create_pr_comment", title: "Approve: Post PR Comment",
    description: `Post comment on PR #${currentWorkbenchPR.number}.`, risk: "medium",
    previewHtml: `<div style="font-size:12.5px;"><p><strong>Repo:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p><p><strong>PR:</strong> #${currentWorkbenchPR.number} &mdash; ${escapeHtml(currentWorkbenchPR.title)}</p><div style="max-height:120px;overflow-y:auto;padding:8px 10px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;font-size:12px;white-space:pre-wrap;">${escapeHtml(body)}</div><div style="margin-top:10px;font-size:11.5px;color:#64748b;">&#x1F512; Auto-merges and auto-approvals are permanently disabled.</div></div>`,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch(`/api/github/workbench/prs/${currentWorkbenchPR.number}/comment`, {
          method: "POST", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({repo_name: currentWorkbenchRepo, body, approved: true})
        });
        if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Failed"); }
        if (textarea) textarea.value = "";
        showSystemToast("PR comment posted.");
      } catch (err) { showSystemToast("Failed: " + err.message); }
    }
  });
}

// ---------- 4. Commits & Branches ----------
async function loadWorkbenchCommits(repoName) {
  const emptyEl = document.getElementById("github-commits-empty-prompt");
  const contentEl = document.getElementById("github-commits-active-content");
  if (!repoName) {
    if (emptyEl) emptyEl.style.display = "flex";
    if (contentEl) contentEl.style.display = "none";
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";
  if (contentEl) contentEl.style.display = "block";
  await loadCommitsHistoryTab(repoName);
}

async function loadCommitsHistoryTab(repoName) {
  const le = document.getElementById("github-commits-list");
  if (!le) return;
  le.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:12px;">Loading commits...</div>';
  try {
    const res = await fetch(`/api/github/workbench/commits?repo_name=${encodeURIComponent(repoName)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    le.innerHTML = "";
    const commits = data.commits || [];
    if (!commits.length) { le.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:12px;">No commits found.</div>'; return; }
    commits.forEach(c => {
      const d = document.createElement("div"); d.className = "github-item-card";
      d.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;"><span style="font-family:monospace;font-weight:700;font-size:12.5px;color:#2563eb;">${escapeHtml((c.sha||"").slice(0,7))}</span><span style="font-size:11px;color:#94a3b8;">${escapeHtml(c.date||"")}</span></div><div style="font-weight:600;font-size:13px;margin:4px 0 2px;">${escapeHtml(c.message||"")}</div><div class="github-meta-sub" style="font-size:11px;">Author: ${escapeHtml(c.author||"Unknown")}</div>`;
      le.appendChild(d);
    });
  } catch (err) { le.innerHTML = `<div style="color:#ef4444;font-size:12px;padding:12px;">Error: ${escapeHtml(err.message)}</div>`; }
}

async function runWorkbenchCompare() {
  if (!currentWorkbenchRepo) return;
  const base = (document.getElementById("github-compare-base-input")?.value||"").trim();
  const head = (document.getElementById("github-compare-head-input")?.value||"").trim();
  if (!base || !head) { showSystemToast("Enter both base and head refs."); return; }
  const rb = document.getElementById("github-compare-results");
  const br = document.getElementById("github-compare-badge-row");
  const fl = document.getElementById("github-compare-files-list");
  if (rb) rb.style.display = "block";
  if (br) br.innerHTML = '<div style="color:#94a3b8;font-size:12px;">Comparing...</div>';
  if (fl) fl.innerHTML = "";
  try {
    const res = await fetch(`/api/github/workbench/compare?repo_name=${encodeURIComponent(currentWorkbenchRepo)}&base=${encodeURIComponent(base)}&head=${encodeURIComponent(head)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Compare failed");
    if (br) br.innerHTML = `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;"><span class="github-badge" style="background:#e0e7ff;color:#3730a3;font-weight:600;">Status: ${escapeHtml(data.status||"diverged")}</span><span class="github-badge github-badge-success">Ahead: ${data.ahead_by??0}</span><span class="github-badge github-badge-danger">Behind: ${data.behind_by??0}</span><span class="github-badge" style="background:#f1f5f9;color:#475569;">${data.total_commits??0} commits</span></div>`;
    if (fl) {
      const files = data.files || [];
      if (!files.length) { fl.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:8px 0;">No changed files.</div>'; }
      else { files.forEach(f => { const d = document.createElement("div"); d.className = "github-item-card"; d.style.padding = "6px 10px"; d.innerHTML = `<div style="display:flex;justify-content:space-between;font-size:12px;"><span style="font-family:monospace;font-weight:600;">${escapeHtml(f.filename)}</span><span style="font-size:11px;color:#64748b;">+${f.additions}/-${f.deletions} (${f.status})</span></div>`; fl.appendChild(d); }); }
    }
  } catch (err) { if (br) br.innerHTML = `<div style="color:#ef4444;font-size:12px;">Error: ${escapeHtml(err.message)}</div>`; }
}

async function loadWorkbenchBranchesTab(repoName) {
  const le = document.getElementById("github-branches-list");
  if (!le) return;
  le.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:12px;">Loading branches...</div>';
  try {
    const res = await fetch(`/api/github/workbench/branches?repo_name=${encodeURIComponent(repoName)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    le.innerHTML = "";
    const branches = data.branches || [];
    if (!branches.length) { le.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:12px;">No branches.</div>'; return; }
    branches.forEach(b => {
      const d = document.createElement("div"); d.className = "github-item-card";
      d.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;"><div style="display:flex;align-items:center;gap:8px;"><span style="font-family:monospace;font-weight:700;font-size:13px;">${escapeHtml(b.name)}</span>${b.protected?'<span class="github-badge github-badge-warn" style="font-size:10px;">Protected</span>':''}</div><span style="font-family:monospace;font-size:11.5px;color:#64748b;">SHA: ${escapeHtml(b.commit_sha||"")}</span></div>`;
      le.appendChild(d);
    });
  } catch (err) { le.innerHTML = `<div style="color:#ef4444;font-size:12px;padding:12px;">Error: ${escapeHtml(err.message)}</div>`; }
}

// ---------- 5. GitHub Actions ----------
let loadedWorkbenchRuns = [];

async function loadWorkbenchActions(repoName) {
  const emptyEl = document.getElementById("github-actions-empty-prompt");
  const contentEl = document.getElementById("github-actions-active-content");
  if (!repoName) {
    if (emptyEl) emptyEl.style.display = "flex";
    if (contentEl) contentEl.style.display = "none";
    return;
  }
  if (emptyEl) emptyEl.style.display = "none";
  if (contentEl) contentEl.style.display = "block";
  const loader = document.getElementById("github-actions-loading");
  const lc = document.getElementById("github-actions-runs-container");
  const status = document.getElementById("github-actions-status-select")?.value || "";
  if (loader) loader.style.display = "flex";
  if (lc) lc.innerHTML = "";
  try {
    const res = await fetch(`/api/github/workbench/actions/runs?repo_name=${encodeURIComponent(repoName)}&status=${encodeURIComponent(status)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    loadedWorkbenchRuns = data.runs || [];
    renderWorkbenchActionsList();
  } catch (err) {
    if (lc) lc.innerHTML = `<div style="color:#ef4444;font-size:12px;padding:12px;">Error: ${escapeHtml(err.message)}</div>`;
  } finally { if (loader) loader.style.display = "none"; }
}

function renderWorkbenchActionsList() {
  const lc = document.getElementById("github-actions-runs-container");
  if (!lc) return;
  lc.innerHTML = "";
  if (!loadedWorkbenchRuns.length) {
    lc.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:24px 12px;text-align:center;">No workflow runs found.</div>';
    return;
  }
  loadedWorkbenchRuns.forEach(run => {
    const card = document.createElement("div");
    card.className = "github-workbench-item-card";
    if (currentWorkbenchRun && currentWorkbenchRun.id === run.id) card.classList.add("active");
    const isFail = run.conclusion === "failure";
    const isOk = run.conclusion === "success";
    const cls = isOk?"github-badge-success":(isFail?"github-badge-danger":"github-badge-warn");
    card.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:flex-start;gap:8px;"><span style="font-weight:600;font-size:13px;">${escapeHtml(run.name||"Workflow")}</span><span class="github-badge ${cls}" style="font-size:10px;">${escapeHtml(run.conclusion||run.status||"queued")}</span></div><div style="font-size:11px;font-family:monospace;color:#475569;margin:4px 0;">Branch: ${escapeHtml(run.head_branch||"main")} &bull; SHA: ${escapeHtml(run.head_sha||"")}</div><div class="github-meta-sub" style="font-size:11px;">Trigger: ${escapeHtml(run.event||"push")} &bull; ${escapeHtml(run.created_at||"")}</div>`;
    card.addEventListener("click", () => selectWorkbenchRun(run.id));
    lc.appendChild(card);
  });
}

async function selectWorkbenchRun(runId) {
  const placeholder = document.getElementById("github-action-placeholder");
  const sel = document.getElementById("github-action-selected-content");
  const aiBox = document.getElementById("action-ai-box");
  if (placeholder) placeholder.style.display = "none";
  if (sel) sel.style.display = "block";
  if (aiBox) aiBox.style.display = "none";
  document.querySelectorAll("#github-actions-runs-container .github-workbench-item-card").forEach(el => el.classList.remove("active"));
  try {
    const res = await fetch(`/api/github/workbench/actions/runs/${runId}?repo_name=${encodeURIComponent(currentWorkbenchRepo)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed");
    currentWorkbenchRun = data;
    const adn = document.getElementById("action-detail-name");
    const adb = document.getElementById("action-detail-branch");
    const adm = document.getElementById("action-detail-meta");
    const adc = document.getElementById("action-detail-conclusion-badge");
    if (adn) adn.textContent = data.name || "Workflow Run";
    if (adb) adb.textContent = data.head_branch || "main";
    if (adm) adm.textContent = `Event: ${data.event||"push"} \u2022 SHA: ${data.head_sha||""} \u2022 ${data.created_at||""}`;
    if (adc) {
      adc.textContent = data.conclusion || data.status || "queued";
      adc.className = `github-badge ${data.conclusion==="success"?"github-badge-success":(data.conclusion==="failure"?"github-badge-danger":"github-badge-warn")}`;
    }
    const analyzeBtn = document.getElementById("btn-action-ai-analyze");
    if (analyzeBtn) analyzeBtn.style.display = (data.conclusion==="failure") ? "inline-flex" : "none";
    const jc = document.getElementById("action-jobs-container");
    if (jc) {
      jc.innerHTML = "";
      const jobs = data.jobs || [];
      if (!jobs.length) { jc.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:8px 0;">No job details available.</div>'; }
      else {
        jobs.forEach(job => {
          const jd = document.createElement("div"); jd.className = "github-item-card"; jd.style.padding = "10px 12px";
          const stepsHtml = (job.steps||[]).map(s => {
            const icon = s.conclusion==="success"?"\u2705":(s.conclusion==="failure"?"\u274C":"\u23F3");
            return `<div style="display:flex;justify-content:space-between;font-size:12px;padding:3px 0;border-bottom:1px solid #f1f5f9;"><span>${icon} ${escapeHtml(s.name)}</span><span style="font-size:11px;color:#94a3b8;">${escapeHtml(s.conclusion||s.status||"")}</span></div>`;
          }).join("");
          jd.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;"><strong>Job: ${escapeHtml(job.name)}</strong><span class="github-badge" style="font-size:10.5px;">${escapeHtml(job.conclusion||job.status||"")}</span></div><div style="padding-left:4px;">${stepsHtml}</div>`;
          jc.appendChild(jd);
        });
      }
    }
  } catch (err) { showSystemToast("Error: " + err.message); }
}

async function runActionAIAnalysis() {
  if (!currentWorkbenchRun || !currentWorkbenchRepo) return;
  const btn = document.getElementById("btn-action-ai-analyze");
  const aiBox = document.getElementById("action-ai-box");
  const be = document.getElementById("action-ai-body");
  const se = document.getElementById("action-ai-suggestions");
  if (btn) { btn.disabled = true; btn.textContent = "Diagnosing..."; }
  try {
    const runId = currentWorkbenchRun.run_id || currentWorkbenchRun.id;
    const res = await fetch(`/api/github/workbench/actions/runs/${runId}/analyze`, {
      method: "POST", headers: {"Content-Type":"application/json"},
      body: JSON.stringify({repo_name: currentWorkbenchRepo})
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Analysis failed");
    if (aiBox) aiBox.style.display = "block";
    if (be) be.innerHTML = formatMarkdown(data.analysis || data.message || "");
    if (se) {
      const fixes = data.fix_suggestions || [];
      se.innerHTML = fixes.length ? `<strong style="display:block;margin-bottom:4px;font-size:12px;">Suggested Fixes:</strong><ul style="margin:0;padding-left:18px;font-size:12px;">${fixes.map(f=>`<li>${escapeHtml(f)}</li>`).join("")}</ul>` : "";
    }
  } catch (err) { showSystemToast("Analysis error: " + err.message); }
  finally { if (btn) { btn.disabled = false; btn.textContent = "\u2728 Analyze Failure"; } }
}

function handleSafeWorkflowRerun() {
  if (!currentWorkbenchRun || !currentWorkbenchRepo) return;
  const runId = currentWorkbenchRun.run_id || currentWorkbenchRun.id;
  openGithubApprovalModal({
    action: "github_rerun_workflow", title: "Approve: Rerun Workflow",
    description: `Rerun workflow '${currentWorkbenchRun.name}' on GitHub Actions.`, risk: "medium",
    previewHtml: `<div style="font-size:12.5px;line-height:1.5;"><p><strong>Repo:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p><p><strong>Run:</strong> ${escapeHtml(currentWorkbenchRun.name||"Workflow")} (ID: <code>${runId}</code>)</p><p><strong>Action:</strong> <span style="font-weight:600;color:#2563eb;">Rerun Workflow</span></p></div>`,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch(`/api/github/workbench/actions/runs/${runId}/rerun`, {
          method: "POST", headers: {"Content-Type":"application/json"},
          body: JSON.stringify({repo_name: currentWorkbenchRepo, approved: true})
        });
        if (!res.ok) { const d = await res.json(); throw new Error(d.detail || "Rerun failed"); }
        showSystemToast("Workflow rerun requested.");
        await loadWorkbenchActions(currentWorkbenchRepo);
      } catch (err) { showSystemToast("Rerun failed: " + err.message); }
    }
  });
}

// ---------- Master Initializer ----------
function initGithubWorkbench() {
  // Subnav buttons
  ["overview","repos","analysis","chat","issues","prs","commits","actions"].forEach(k => {
    document.getElementById(`btn-github-subnav-${k}`)?.addEventListener("click", () => switchGithubSubnav(k));
  });

  // Global repo selector
  document.getElementById("github-global-repo-select")?.addEventListener("change", (e) => {
    currentWorkbenchRepo = e.target.value;
    const chatSel = document.getElementById("github-chat-repo-select");
    if (chatSel && chatSel.value !== currentWorkbenchRepo) {
      chatSel.value = currentWorkbenchRepo;
      if (typeof onChatRepositorySelected === "function") onChatRepositorySelected(currentWorkbenchRepo);
    }
    switchGithubSubnav(currentWorkbenchSubnav || "overview");
  });

  // Overview shortcuts
  document.getElementById("btn-overview-view-all-commits")?.addEventListener("click", () => switchGithubSubnav("commits"));
  document.getElementById("btn-overview-view-all-actions")?.addEventListener("click", () => switchGithubSubnav("actions"));

  // Issues
  document.getElementById("btn-github-issues-refresh")?.addEventListener("click", () => loadWorkbenchIssues(currentWorkbenchRepo));
  document.getElementById("github-issues-state-select")?.addEventListener("change", () => loadWorkbenchIssues(currentWorkbenchRepo));
  document.getElementById("github-issues-search-input")?.addEventListener("input", debounce(() => loadWorkbenchIssues(currentWorkbenchRepo), 350));
  document.getElementById("btn-github-issues-new")?.addEventListener("click", handleCreateNewIssue);
  document.getElementById("btn-issue-ai-investigate")?.addEventListener("click", runIssueAIInvestigation);
  document.getElementById("btn-issue-toggle-state")?.addEventListener("click", handleToggleIssueState);
  document.getElementById("btn-issue-submit-comment")?.addEventListener("click", handleAddIssueComment);
  document.getElementById("btn-create-issue-modal-cancel")?.addEventListener("click", () => document.getElementById("github-create-issue-modal")?.classList.add("hidden"));
  document.getElementById("btn-create-issue-modal-submit")?.addEventListener("click", submitNewIssueFromModal);

  // PRs
  document.getElementById("btn-github-prs-refresh")?.addEventListener("click", () => loadWorkbenchPRs(currentWorkbenchRepo));
  document.getElementById("github-prs-state-select")?.addEventListener("change", () => loadWorkbenchPRs(currentWorkbenchRepo));
  document.getElementById("btn-pr-ai-review")?.addEventListener("click", runPRAICodeReview);
  document.getElementById("btn-pr-submit-comment")?.addEventListener("click", handleAddPRComment);

  // Commits & Branches subtabs
  const cpills = [
    {btn:"btn-commits-tab-history", panel:"panel-commits-history", onShow:() => loadCommitsHistoryTab(currentWorkbenchRepo)},
    {btn:"btn-commits-tab-compare", panel:"panel-commits-compare", onShow:() => {}},
    {btn:"btn-commits-tab-branches", panel:"panel-commits-branches", onShow:() => loadWorkbenchBranchesTab(currentWorkbenchRepo)}
  ];
  cpills.forEach(p => {
    document.getElementById(p.btn)?.addEventListener("click", () => {
      cpills.forEach(o => { document.getElementById(o.btn)?.classList.remove("active"); const el = document.getElementById(o.panel); if (el) el.style.display = "none"; });
      document.getElementById(p.btn)?.classList.add("active");
      const tp = document.getElementById(p.panel); if (tp) tp.style.display = "block";
      p.onShow();
    });
  });
  document.getElementById("btn-github-run-compare")?.addEventListener("click", runWorkbenchCompare);

  // Actions
  document.getElementById("btn-github-actions-refresh")?.addEventListener("click", () => loadWorkbenchActions(currentWorkbenchRepo));
  document.getElementById("github-actions-status-select")?.addEventListener("change", () => loadWorkbenchActions(currentWorkbenchRepo));
  document.getElementById("btn-action-ai-analyze")?.addEventListener("click", runActionAIAnalysis);
  document.getElementById("btn-action-safe-rerun")?.addEventListener("click", handleSafeWorkflowRerun);

  // Approval modal
  document.getElementById("btn-github-modal-cancel")?.addEventListener("click", closeGithubApprovalModal);
  document.getElementById("btn-github-modal-confirm")?.addEventListener("click", () => {
    if (typeof currentPendingApprovalAction === "function") currentPendingApprovalAction();
  });
}
