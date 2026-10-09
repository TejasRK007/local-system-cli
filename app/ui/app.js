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
  scrollToBottom();
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

function formatMarkdown(text) {
  if (!text) return "";

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

  // 3. Inline Code: `code`
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // 4. Bold: **text**
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  // 5. Bullet Lists: - item or * item
  html = html.replace(/^\s*[-*]\s+(.+)$/gm, "<li>$1</li>");
  html = html.replace(/(<li>(?:(?!<ul)[^<]|<(?!\/ul>))*<\/li>)/gs, "<ul>$1</ul>");

  // 6. Line breaks
  html = html.replace(/\n\n+/g, "<br><br>");
  html = html.replace(/\n/g, "<br>");

  // 7. Restore Tables & Code Blocks
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
}

function initLlmToggle() {
  const checkbox = document.getElementById("llm-toggle-checkbox");
  const wrap = document.getElementById("header-llm-toggle-wrap");
  const btnGear = document.getElementById("btn-open-llm-modal");
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
      document.getElementById("header-inbox-tools")?.classList.remove("hidden");
      fetchEmailInbox();
    } else {
      document.getElementById("header-chat-tools")?.classList.remove("hidden");
      document.getElementById("header-inbox-search-wrap")?.classList.add("hidden");
      document.getElementById("header-inbox-tools")?.classList.add("hidden");
    }
  }

  navBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const tabId = btn.getAttribute("data-tab");
      switchTab(tabId);
    });
  });

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

function scrollToBottom() {
  const viewport = document.getElementById("chat-viewport");
  if (viewport) {
    viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
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

  const lanHost = data.network_url || (data.lan_ip ? `${window.location.protocol}//${data.lan_ip}${window.location.port ? ':' + window.location.port : ''}` : window.location.origin);
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
    const timeFormatted = r.checked_in_at ? r.checked_in_at.split(" ")[1] || r.checked_in_at : "Just now";
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

  btnConfirmStart?.addEventListener("click", async () => {
    const course = document.getElementById("modal-att-course")?.value.trim() || "Course Attendance";
    const section = document.getElementById("modal-att-section")?.value.trim() || "Section A";
    const interval = parseInt(document.getElementById("modal-att-interval")?.value || "15", 10);

    try {
      const res = await fetch("/api/attendance/session/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          course_name: course,
          section: section,
          rotation_interval_seconds: interval
        })
      });
      const data = await res.json();
      if (data.success) {
        closeModal();
        await fetchActiveAttendanceSession();
        showAttendanceToast(`Live attendance started for ${course}`, "success");
      } else {
        alert(data.error || "Could not start session.");
      }
    } catch (err) {
      alert("Failed to start attendance session: " + err.message);
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

function cleanSnippet(text) {
  if (!text) return "";
  return text
    .replace(/\[image:[^\]]*\]/gi, "")
    .replace(/https?:\/\/\S+/gi, "")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
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

  // Sync Mail Buttons (Toolbar and Top Nav)
  document.getElementById("btn-table-sync")?.addEventListener("click", () => {
    syncEmailAccount();
  });
  document.getElementById("btn-sync-emails")?.addEventListener("click", () => {
    syncEmailAccount();
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
  const accountPill = document.getElementById("inbox-account-pill");
  const linkModal = document.getElementById("link-email-modal");
  const cancelLinkBtn = document.getElementById("btn-cancel-link-account");
  const cancelDemoBtn = document.getElementById("btn-cancel-demo-account");
  const closeIconBtn = document.getElementById("btn-close-link-modal");
  const unlinkBtn = document.getElementById("btn-unlink-account");

  const openLinkModal = () => {
    linkModal?.classList.remove("hidden");
    const emailInput = document.getElementById("link-imap-email");
    const hostInput = document.getElementById("link-imap-host");
    const smtpInput = document.getElementById("link-smtp-host");

    if (activeConnectedEmail) {
      if (emailInput) emailInput.value = activeConnectedEmail;
      if (activeConnectedEmail.includes("@gmail.com")) {
        if (hostInput && !hostInput.value) hostInput.value = "imap.gmail.com";
        if (smtpInput && !smtpInput.value) smtpInput.value = "smtp.gmail.com";
      }
      // If already connected, default to IMAP tab and display Disconnect button
      const tabImap = document.getElementById("tab-account-imap");
      tabImap?.click();
      if (unlinkBtn) unlinkBtn.style.display = "inline-flex";
    } else {
      if (unlinkBtn) unlinkBtn.style.display = "none";
    }
  };

  const closeLinkModal = () => {
    linkModal?.classList.add("hidden");
  };

  openModalBtn?.addEventListener("click", openLinkModal);
  accountPill?.addEventListener("click", openLinkModal);
  cancelLinkBtn?.addEventListener("click", closeLinkModal);
  cancelDemoBtn?.addEventListener("click", closeLinkModal);
  closeIconBtn?.addEventListener("click", closeLinkModal);

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
  const tabDemo = document.getElementById("tab-account-demo");
  const tabImap = document.getElementById("tab-account-imap");
  const paneDemo = document.getElementById("pane-account-demo");
  const paneImap = document.getElementById("pane-account-imap");

  tabDemo?.addEventListener("click", () => {
    tabDemo.classList.add("active");
    tabImap?.classList.remove("active");
    paneDemo?.classList.remove("hidden");
    paneImap?.classList.add("hidden");
  });

  tabImap?.addEventListener("click", () => {
    tabImap.classList.add("active");
    tabDemo?.classList.remove("active");
    paneImap?.classList.remove("hidden");
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
  if (!statusLabel) return;
  try {
    const res = await fetch("/api/email/account");
    const data = await res.json();
    if (data.success) {
      activeConnectedEmail = data.email || "";
      const isImap = data.account_type === "imap";
      statusLabel.textContent = `Connected: ${data.email} (${isImap ? "IMAP" : "Sandbox"})`;

      // If an account is linked, remove/hide the Link Account button option
      if (linkAccountBtn) {
        if (isImap && activeConnectedEmail) {
          linkAccountBtn.style.display = "none";
        } else {
          linkAccountBtn.style.display = "inline-flex";
        }
      }
    }
  } catch (e) {
    statusLabel.textContent = "Offline Sandbox";
    if (linkAccountBtn) linkAccountBtn.style.display = "inline-flex";
  }
}

async function syncEmailInbox() {
  const syncBtn = document.getElementById("btn-sync-emails");
  const label = syncBtn?.querySelector("span");
  if (syncBtn) syncBtn.classList.add("spinning");
  if (label) label.textContent = "Syncing...";
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
    if (syncBtn) syncBtn.classList.remove("spinning");
    if (label) label.textContent = "Sync Mail";
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

    const badgeAll = document.getElementById("tab-badge-all");
    const badgeUnread = document.getElementById("tab-badge-unread");
    const badgeUrgent = document.getElementById("tab-badge-urgent");
    if (badgeAll) badgeAll.textContent = totalCount;
    if (badgeUnread) badgeUnread.textContent = unreadCount;
    if (badgeUrgent) badgeUrgent.textContent = urgentCount;

    fetchNotifications();

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

      let badgeHtml = "";
      if (msg.priority === "high" || msg.category === "urgent") {
        badgeHtml = `<span class="row-badge row-badge-urgent">Urgent</span>`;
      } else if ((msg.subject || "").toLowerCase().includes("security") || (msg.subject || "").toLowerCase().includes("password")) {
        badgeHtml = `<span class="row-badge row-badge-security">Security</span>`;
      }

      const threadBadgeHtml = msg.threadCount && msg.threadCount > 1
        ? `<span class="row-thread-count">${msg.threadCount}</span>`
        : "";

      row.innerHTML = `
        <div class="row-check-cell">
          <input type="checkbox" class="row-checkbox">
        </div>
        <div class="row-star-cell" title="Star message">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
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
      row.querySelector(".row-star-cell")?.addEventListener("click", (e) => {
        e.stopPropagation();
        e.currentTarget.classList.toggle("starred");
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

    // Body with clean link & image parsing
    const bodyContainer = document.getElementById("detail-body-text");
    if (bodyContainer) {
      bodyContainer.innerHTML = formatEmailBody(msg.body);
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
  } catch (e) {
    console.error("Failed to load message:", e);
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
