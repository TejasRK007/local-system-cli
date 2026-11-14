"""Apply the Workbench JS interactivity patch to app/ui/app.js."""
import os, re

APPJS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "app", "ui", "app.js")
with open(APPJS, "r", encoding="utf-8") as f:
    content = f.read()

# Normalize to LF for patching, we'll convert back at end
orig_has_crlf = "\r\n" in content
content_lf = content.replace("\r\n", "\n")
print(f"File loaded: {len(content_lf.splitlines())} lines, CRLF: {orig_has_crlf}")

# ---- PATCH 1: Add updateWorkbenchGlobalRepoSelect() call to loadGithubConnectedRepos ----
old1 = (
    "      githubTrackedRepos = data.repos;\n"
    "      filterAndRenderConnectedRepos();\n"
    "    }\n"
    "  } catch (e) {\n"
    '    console.error("Error loading connected repos:", e);\n'
    "  }\n"
    "}"
)
new1 = (
    "      githubTrackedRepos = data.repos;\n"
    "      filterAndRenderConnectedRepos();\n"
    "      if (typeof updateWorkbenchGlobalRepoSelect === 'function') updateWorkbenchGlobalRepoSelect();\n"
    "    }\n"
    "  } catch (e) {\n"
    '    console.error("Error loading connected repos:", e);\n'
    "  }\n"
    "}"
)
assert old1 in content_lf, f"PATCH 1 not found. Nearby:\n{content_lf[content_lf.find('loadGithubConnectedRepos'):content_lf.find('loadGithubConnectedRepos')+400]}"
content_lf = content_lf.replace(old1, new1, 1)
print("PATCH 1 OK: updateWorkbenchGlobalRepoSelect hook added")

# ---- PATCH 2: Add initGithubWorkbench() call in initGithubDashboard ----
old2 = "  // Initialize Repository Chat Controls\n  initGithubChat();"
new2 = "  // Initialize Repository Chat Controls\n  initGithubChat();\n\n  // Initialize Developer Workbench Controls (Prompt 4)\n  if (typeof initGithubWorkbench === 'function') initGithubWorkbench();"
assert old2 in content_lf, "PATCH 2: initGithubChat pattern not found"
content_lf = content_lf.replace(old2, new2, 1)
print("PATCH 2 OK: initGithubWorkbench hook added")

# ---- PATCH 3: Replace switchGithubSubnav with full 8-tab version ----
# Find it by regex since exact text may vary slightly
match = re.search(r'function switchGithubSubnav\(target\) \{.*?\n\}', content_lf, re.DOTALL)
assert match, "PATCH 3: switchGithubSubnav function not found"
old3 = match.group(0)
new3 = r"""let currentWorkbenchRepo = "";
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
}"""
content_lf = content_lf.replace(old3, new3, 1)
print("PATCH 3 OK: switchGithubSubnav replaced with 8-tab version")

# ---- PATCH 4: Append entire workbench interactivity block ----
WORKBENCH_JS = r"""
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
"""

content_lf = content_lf + "\n" + WORKBENCH_JS
print(f"PATCH 4 OK: {len(WORKBENCH_JS.splitlines())} lines of workbench code appended")

# Write back (preserve original CRLF if file had it)
out = content_lf.replace("\n", "\r\n") if orig_has_crlf else content_lf
with open(APPJS, "w", encoding="utf-8") as f:
    f.write(out)

print(f"SUCCESS: app/ui/app.js updated ({len(out.splitlines())} total lines)")
