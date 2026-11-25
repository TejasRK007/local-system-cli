# Script to patch app/ui/app.js with GitHub Developer Workbench features
import os

with open("app/ui/app.js", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Update loadGithubConnectedRepos to also call updateWorkbenchGlobalRepoSelect()
old_load_repos = """async function loadGithubConnectedRepos() {
  try {
    const res = await fetch("/api/github/repos/connected");
    const data = await res.json();
    if (data.success && Array.isArray(data.repos)) {
      githubTrackedRepos = data.repos;
      filterAndRenderConnectedRepos();
    }
  } catch (e) {
    console.error("Error loading connected repos:", e);
  }
}"""

new_load_repos = """async function loadGithubConnectedRepos() {
  try {
    const res = await fetch("/api/github/repos/connected");
    const data = await res.json();
    if (data.success && Array.isArray(data.repos)) {
      githubTrackedRepos = data.repos;
      filterAndRenderConnectedRepos();
      updateWorkbenchGlobalRepoSelect();
    }
  } catch (e) {
    console.error("Error loading connected repos:", e);
  }
}"""

assert old_load_repos in content, "old_load_repos not found"
content = content.replace(old_load_repos, new_load_repos, 1)

# 2. In initGithubDashboard(), add initGithubWorkbench()
old_init_call = """  // Initialize Repository Chat Controls
  initGithubChat();"""

new_init_call = """  // Initialize Repository Chat Controls
  initGithubChat();

  // Initialize Developer Workbench Controls
  initGithubWorkbench();"""

assert old_init_call in content, "old_init_call not found"
content = content.replace(old_init_call, new_init_call, 1)

# 3. Replace old switchGithubSubnav with full 8-tab implementation
old_switch = """function switchGithubSubnav(target) {
  const btnRepos = document.getElementById("btn-github-subnav-repos");
  const btnChat = document.getElementById("btn-github-subnav-chat");
  const viewRepos = document.getElementById("github-repos-main-view");
  const viewChat = document.getElementById("github-chat-container");

  if (target === "chat") {
    btnRepos?.classList.remove("active");
    btnChat?.classList.add("active");
    if (viewRepos) viewRepos.style.display = "none";
    if (viewChat) viewChat.style.display = "block";
    loadAnalyzedReposForChat();
  } else {
    btnChat?.classList.remove("active");
    btnRepos?.classList.add("active");
    if (viewChat) viewChat.style.display = "none";
    if (viewRepos) viewRepos.style.display = "block";
  }
}"""

new_switch = """let currentWorkbenchRepo = "";
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
    const btn = document.getElementById(`btn-github-subnav-${k}`);
    if (k === target) {
      btn?.classList.add("active");
    } else {
      btn?.classList.remove("active");
    }

    const panel = document.getElementById(viewMap[k]);
    if (panel) {
      if (k === target) {
        panel.style.display = "block";
      } else {
        panel.style.display = "none";
      }
    }
  });

  currentWorkbenchSubnav = target;

  if (target === "overview") {
    loadWorkbenchOverview(currentWorkbenchRepo);
  } else if (target === "repos") {
    filterAndRenderConnectedRepos();
  } else if (target === "analysis") {
    if (currentWorkbenchRepo && (!currentAnalysisData || currentAnalysisRepoName !== currentWorkbenchRepo)) {
      const match = githubTrackedRepos.find(r => r.full_name === currentWorkbenchRepo);
      if (match) {
        openRepositoryAnalysis(match.id, match.full_name, false);
      }
    }
  } else if (target === "chat") {
    loadAnalyzedReposForChat(currentWorkbenchRepo);
  } else if (target === "issues") {
    loadWorkbenchIssues(currentWorkbenchRepo);
  } else if (target === "prs") {
    loadWorkbenchPRs(currentWorkbenchRepo);
  } else if (target === "commits") {
    loadWorkbenchCommits(currentWorkbenchRepo);
  } else if (target === "actions") {
    loadWorkbenchActions(currentWorkbenchRepo);
  }
}"""

assert old_switch in content, "old_switch not found"
content = content.replace(old_switch, new_switch, 1)

# 4. Workbench helper functions and initialization
workbench_code = r'''
// ============================================================================
// Developer Workbench & Safe Automation (Milestone 9 - Prompt 4)
// ============================================================================

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
    select.value = prevValue;
    currentWorkbenchRepo = prevValue;
  } else if (githubTrackedRepos.length > 0) {
    select.value = githubTrackedRepos[0].full_name;
    currentWorkbenchRepo = githubTrackedRepos[0].full_name;
  } else {
    select.value = "";
    currentWorkbenchRepo = "";
  }
}

// ----------------------------------------------------------------------------
// Safety Approval Modal Helper
// ----------------------------------------------------------------------------
function openGithubApprovalModal({ action, title, description, risk, previewHtml, onConfirm }) {
  const modal = document.getElementById("github-approval-modal");
  const titleEl = document.getElementById("github-modal-title");
  const descEl = document.getElementById("github-modal-desc");
  const riskBadge = document.getElementById("github-modal-risk-badge");
  const previewCard = document.getElementById("github-modal-preview");

  if (!modal) return;
  if (titleEl) titleEl.textContent = title || "Approve GitHub Action";
  if (descEl) descEl.textContent = description || "Review the action preview below before executing this write operation.";
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

// ----------------------------------------------------------------------------
// 1. Overview Panel
// ----------------------------------------------------------------------------
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
    if (!res.ok) throw new Error(data.detail || "Failed to load overview");

    const repo = data.repository || {};
    const repoNameEl = document.getElementById("overview-repo-name");
    const repoDescEl = document.getElementById("overview-repo-desc");
    const branchBadge = document.getElementById("overview-branch-badge");
    const visBadge = document.getElementById("overview-visibility-badge");
    const ghLink = document.getElementById("overview-github-link");

    if (repoNameEl) repoNameEl.textContent = repo.full_name || repoName;
    if (repoDescEl) repoDescEl.textContent = repo.description || "No description provided.";
    if (branchBadge) branchBadge.textContent = `Default: ${repo.default_branch || "main"}`;
    if (visBadge) {
      visBadge.textContent = repo.private ? "Private" : "Public";
      visBadge.className = `github-badge ${repo.private ? "private" : "public"}`;
    }
    if (ghLink) ghLink.href = repo.html_url || `https://github.com/${repoName}`;

    // Metrics
    document.getElementById("overview-stat-issues").textContent = data.open_issues_count ?? 0;
    document.getElementById("overview-stat-prs").textContent = data.open_prs_count ?? 0;
    document.getElementById("overview-stat-branches").textContent = data.branch_count ?? 0;
    const failuresEl = document.getElementById("overview-stat-failures");
    if (failuresEl) {
      failuresEl.textContent = data.workflow_failures_count ?? 0;
      failuresEl.style.color = (data.workflow_failures_count > 0) ? "#ef4444" : "#10b981";
    }

    // Recent Commits Feed
    const commitsContainer = document.getElementById("overview-recent-commits-list");
    if (commitsContainer) {
      commitsContainer.innerHTML = "";
      const recentCommits = data.recent_commits || [];
      if (recentCommits.length === 0) {
        commitsContainer.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:8px 0;">No recent commits recorded.</div>';
      } else {
        recentCommits.slice(0, 5).forEach(c => {
          const item = document.createElement("div");
          item.className = "github-item-card";
          item.style.padding = "8px 12px";
          item.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-family:monospace; font-weight:600; font-size:12px; color:#2563eb;">${escapeHtml((c.sha || "").slice(0, 7))}</span>
              <span style="font-size:11px; color:#94a3b8;">${escapeHtml(c.date || "")}</span>
            </div>
            <div style="font-size:12.5px; font-weight:500; margin-top:2px; color:#1e293b;">${escapeHtml(c.message || "")}</div>
            <div style="font-size:11px; color:#64748b; margin-top:2px;">by ${escapeHtml(c.author || "Unknown")}</div>
          `;
          commitsContainer.appendChild(item);
        });
      }
    }

    // Recent Actions Feed
    const actionsContainer = document.getElementById("overview-recent-actions-list");
    if (actionsContainer) {
      actionsContainer.innerHTML = "";
      const recentRuns = data.recent_workflow_runs || [];
      if (recentRuns.length === 0) {
        actionsContainer.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:8px 0;">No workflow runs found.</div>';
      } else {
        recentRuns.slice(0, 5).forEach(r => {
          const item = document.createElement("div");
          item.className = "github-item-card";
          item.style.padding = "8px 12px";
          const isSuccess = r.conclusion === "success";
          const isFailure = r.conclusion === "failure";
          const badgeClass = isSuccess ? "github-badge-success" : (isFailure ? "github-badge-danger" : "github-badge-warn");
          item.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center;">
              <span style="font-weight:600; font-size:12.5px; color:#1e293b;">${escapeHtml(r.name || "Workflow")}</span>
              <span class="github-badge ${badgeClass}" style="font-size:10.5px;">${escapeHtml(r.conclusion || r.status || "queued")}</span>
            </div>
            <div style="font-size:11.5px; color:#64748b; margin-top:2px;">
              <span>Branch: <code>${escapeHtml(r.branch || "main")}</code></span> •
              <span>Commit: <code>${escapeHtml((r.commit_sha || "").slice(0, 7))}</code></span>
            </div>
          `;
          actionsContainer.appendChild(item);
        });
      }
    }
  } catch (err) {
    console.error("Overview error:", err);
  }
}

// ----------------------------------------------------------------------------
// 2. Issues Panel
// ----------------------------------------------------------------------------
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
  const listContainer = document.getElementById("github-issues-list-container");
  const stateSelect = document.getElementById("github-issues-state-select");
  const searchInput = document.getElementById("github-issues-search-input");

  const state = stateSelect?.value || "open";
  const query = searchInput?.value || "";

  if (loader) loader.style.display = "flex";
  if (listContainer) listContainer.innerHTML = "";

  try {
    const res = await fetch(`/api/github/workbench/issues?repo_name=${encodeURIComponent(repoName)}&state=${encodeURIComponent(state)}&q=${encodeURIComponent(query)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load issues");

    loadedWorkbenchIssues = data.issues || [];
    renderWorkbenchIssuesList();
  } catch (err) {
    if (listContainer) {
      listContainer.innerHTML = `<div style="color:#ef4444; font-size:12px; padding:12px;">Error loading issues: ${escapeHtml(err.message)}</div>`;
    }
  } finally {
    if (loader) loader.style.display = "none";
  }
}

function renderWorkbenchIssuesList() {
  const listContainer = document.getElementById("github-issues-list-container");
  if (!listContainer) return;
  listContainer.innerHTML = "";

  if (loadedWorkbenchIssues.length === 0) {
    listContainer.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:24px 12px; text-align:center;">No issues found matching criteria.</div>';
    return;
  }

  loadedWorkbenchIssues.forEach(issue => {
    const card = document.createElement("div");
    card.className = "github-workbench-item-card";
    if (currentWorkbenchIssue && currentWorkbenchIssue.number === issue.number) {
      card.classList.add("active");
    }

    const labelsHtml = (issue.labels || []).map(l =>
      `<span class="github-badge" style="background:#e0f2fe; color:#0369a1; font-size:10px; padding:1px 6px;">${escapeHtml(l)}</span>`
    ).join(" ");

    const isOpen = issue.state === "open";
    const stateBadge = `<span class="github-badge ${isOpen ? "github-badge-success" : "github-badge-danger"}" style="font-size:10px;">${isOpen ? "Open" : "Closed"}</span>`;

    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
        <span style="font-weight:600; font-size:13px; color:#1e293b;">#${issue.number} ${escapeHtml(issue.title)}</span>
        ${stateBadge}
      </div>
      <div style="margin: 6px 0 4px; display:flex; flex-wrap:wrap; gap:4px;">${labelsHtml}</div>
      <div class="github-meta-sub" style="font-size:11px;">
        <span>By ${escapeHtml(issue.author || "Unknown")}</span> •
        <span>💬 ${issue.comments_count || 0}</span> •
        <span>${escapeHtml(issue.updated_at || "")}</span>
      </div>
    `;

    card.addEventListener("click", () => {
      selectWorkbenchIssue(issue.number);
    });

    listContainer.appendChild(card);
  });
}

async function selectWorkbenchIssue(issueNumber) {
  const placeholder = document.getElementById("github-issue-placeholder");
  const selectedContent = document.getElementById("github-issue-selected-content");
  const aiBox = document.getElementById("issue-ai-box");

  if (placeholder) placeholder.style.display = "none";
  if (selectedContent) selectedContent.style.display = "block";
  if (aiBox) aiBox.style.display = "none";

  // Highlight in list
  document.querySelectorAll("#github-issues-list-container .github-workbench-item-card").forEach(el => {
    el.classList.remove("active");
  });

  try {
    const res = await fetch(`/api/github/workbench/issues/${issueNumber}?repo_name=${encodeURIComponent(currentWorkbenchRepo)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load issue details");

    const issue = data.issue || {};
    currentWorkbenchIssue = issue;

    // Header & Meta
    const titleEl = document.getElementById("issue-detail-title");
    const metaEl = document.getElementById("issue-detail-meta");
    const badgeEl = document.getElementById("issue-detail-state-badge");
    const toggleBtn = document.getElementById("btn-issue-toggle-state");

    if (titleEl) titleEl.textContent = `#${issue.number} ${issue.title}`;
    if (metaEl) metaEl.textContent = `Opened by ${issue.author || "Unknown"} on ${issue.created_at || "recently"}`;
    if (badgeEl) {
      const isOpen = issue.state === "open";
      badgeEl.textContent = isOpen ? "Open" : "Closed";
      badgeEl.className = `github-badge ${isOpen ? "github-badge-success" : "github-badge-danger"}`;
    }

    if (toggleBtn) {
      toggleBtn.textContent = issue.state === "open" ? "Close Issue" : "Reopen Issue";
      toggleBtn.className = issue.state === "open" ? "pill-btn pill-btn-outline danger" : "pill-btn pill-btn-primary";
    }

    // Body
    const bodyEl = document.getElementById("issue-detail-body");
    if (bodyEl) {
      bodyEl.innerHTML = issue.body ? formatMarkdown(issue.body) : '<span style="color:#94a3b8; font-style:italic;">No description provided.</span>';
    }

    // Comments Feed
    const commentsCounter = document.getElementById("issue-comments-counter");
    const commentsFeed = document.getElementById("issue-comments-feed");
    const comments = issue.comments || [];
    if (commentsCounter) commentsCounter.textContent = comments.length;
    if (commentsFeed) {
      commentsFeed.innerHTML = "";
      if (comments.length === 0) {
        commentsFeed.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:8px 0;">No comments on this issue yet.</div>';
      } else {
        comments.forEach(c => {
          const item = document.createElement("div");
          item.className = "github-comment-item";
          item.innerHTML = `
            <div class="github-comment-header">
              <strong>${escapeHtml(c.author || "User")}</strong> commented on ${escapeHtml(c.created_at || "")}
            </div>
            <div class="github-comment-body">
              ${formatMarkdown(c.body || "")}
            </div>
          `;
          commentsFeed.appendChild(item);
        });
      }
    }
  } catch (err) {
    showSystemToast("Error loading issue: " + err.message);
  }
}

async function runIssueAIInvestigation() {
  if (!currentWorkbenchIssue || !currentWorkbenchRepo) return;

  const btn = document.getElementById("btn-issue-ai-investigate");
  const aiBox = document.getElementById("issue-ai-box");
  const summaryEl = document.getElementById("issue-ai-summary");
  const stepsEl = document.getElementById("issue-ai-steps");
  const dupEl = document.getElementById("issue-ai-duplicates");

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Analyzing...";
  }

  try {
    const res = await fetch(`/api/github/workbench/issues/${currentWorkbenchIssue.number}/summarize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_name: currentWorkbenchRepo })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "AI Investigation failed");

    if (aiBox) aiBox.style.display = "block";
    if (summaryEl) summaryEl.innerHTML = formatMarkdown(data.summary || "");

    if (stepsEl) {
      const steps = data.suggested_steps || [];
      if (steps.length > 0) {
        stepsEl.innerHTML = `
          <strong style="display:block; margin-bottom:4px; font-size:12px; color:#1e293b;">Suggested Investigation Steps:</strong>
          <ul style="margin:0; padding-left:18px; font-size:12px; color:#334155;">
            ${steps.map(s => `<li>${escapeHtml(s)}</li>`).join("")}
          </ul>
        `;
      } else {
        stepsEl.innerHTML = "";
      }
    }

    if (dupEl) {
      const dups = data.possible_duplicates || [];
      if (dups.length > 0) {
        dupEl.innerHTML = `
          <div class="github-alert-notice" style="margin-top:8px;">
            🔍 <strong>Possible Duplicates (Suggestions, verify before linking):</strong>
            <ul style="margin:4px 0 0; padding-left:18px;">
              ${dups.map(d => `<li>#${d.number} ${escapeHtml(d.title)} (Status: ${escapeHtml(d.state)})</li>`).join("")}
            </ul>
          </div>
        `;
      } else {
        dupEl.innerHTML = "";
      }
    }
  } catch (err) {
    showSystemToast("AI analysis error: " + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "✨ AI Investigation";
    }
  }
}

function handleToggleIssueState() {
  if (!currentWorkbenchIssue || !currentWorkbenchRepo) return;

  const nextState = currentWorkbenchIssue.state === "open" ? "closed" : "open";
  const actionLabel = nextState === "closed" ? "Close Issue" : "Reopen Issue";

  const previewHtml = `
    <div style="font-size:12.5px; line-height:1.5;">
      <p style="margin:0 0 6px;"><strong>Target Repository:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p>
      <p style="margin:0 0 6px;"><strong>Issue:</strong> #${currentWorkbenchIssue.number} — ${escapeHtml(currentWorkbenchIssue.title)}</p>
      <p style="margin:0 0 6px;"><strong>Action:</strong> <span style="font-weight:600; color:${nextState === 'closed' ? '#dc2626' : '#16a34a'};">${actionLabel}</span></p>
      <div style="margin-top:10px; padding:8px 10px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; font-size:11.5px; color:#64748b;">
        🔒 This write action will be authenticated via GitHub and logged in the local audit trail.
      </div>
    </div>
  `;

  openGithubApprovalModal({
    action: "github_update_issue",
    title: `Approve: ${actionLabel}`,
    description: `Please review and explicitly approve updating issue #${currentWorkbenchIssue.number}.`,
    risk: "medium",
    previewHtml,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch(`/api/github/workbench/issues/${currentWorkbenchIssue.number}/update`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            repo_name: currentWorkbenchRepo,
            state: nextState,
            approved: true
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to update issue");

        showSystemToast(`Issue #${currentWorkbenchIssue.number} marked as ${nextState}.`);
        await loadWorkbenchIssues(currentWorkbenchRepo);
        await selectWorkbenchIssue(currentWorkbenchIssue.number);
      } catch (err) {
        showSystemToast("Update failed: " + err.message);
      }
    }
  });
}

function handleAddIssueComment() {
  if (!currentWorkbenchIssue || !currentWorkbenchRepo) return;
  const textarea = document.getElementById("issue-comment-textarea");
  const body = (textarea?.value || "").trim();

  if (!body) {
    showSystemToast("Please enter a comment message.");
    return;
  }

  const previewHtml = `
    <div style="font-size:12.5px; line-height:1.5;">
      <p style="margin:0 0 6px;"><strong>Target Repository:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p>
      <p style="margin:0 0 6px;"><strong>Issue:</strong> #${currentWorkbenchIssue.number} — ${escapeHtml(currentWorkbenchIssue.title)}</p>
      <p style="margin:0 0 4px;"><strong>Comment Body Preview:</strong></p>
      <div style="max-height:120px; overflow-y:auto; padding:8px 10px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; font-size:12px; white-space:pre-wrap;">${escapeHtml(body)}</div>
      <div style="margin-top:10px; font-size:11.5px; color:#64748b;">
        🔒 This write action requires confirmation and will be logged in the audit trail.
      </div>
    </div>
  `;

  openGithubApprovalModal({
    action: "github_add_issue_comment",
    title: "Approve: Post Issue Comment",
    description: `Review the comment to be posted on issue #${currentWorkbenchIssue.number}.`,
    risk: "medium",
    previewHtml,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch(`/api/github/workbench/issues/${currentWorkbenchIssue.number}/comment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            repo_name: currentWorkbenchRepo,
            body,
            approved: true
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to post comment");

        if (textarea) textarea.value = "";
        showSystemToast("Comment posted successfully.");
        await selectWorkbenchIssue(currentWorkbenchIssue.number);
      } catch (err) {
        showSystemToast("Post comment failed: " + err.message);
      }
    }
  });
}

function handleCreateNewIssue() {
  if (!currentWorkbenchRepo) {
    showSystemToast("Please select a repository first.");
    return;
  }
  const modal = document.getElementById("github-create-issue-modal");
  if (modal) modal.classList.remove("hidden");
}

function submitNewIssueFromModal() {
  const title = (document.getElementById("modal-issue-title-input")?.value || "").trim();
  const body = (document.getElementById("modal-issue-body-textarea")?.value || "").trim();
  const labelsRaw = (document.getElementById("modal-issue-labels-input")?.value || "").trim();
  const labels = labelsRaw ? labelsRaw.split(",").map(l => l.trim()).filter(Boolean) : [];

  if (!title) {
    showSystemToast("Please provide an issue title.");
    return;
  }

  // Close draft modal
  document.getElementById("github-create-issue-modal")?.classList.add("hidden");

  const previewHtml = `
    <div style="font-size:12.5px; line-height:1.5;">
      <p style="margin:0 0 6px;"><strong>Target Repository:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p>
      <p style="margin:0 0 6px;"><strong>Title:</strong> ${escapeHtml(title)}</p>
      <p style="margin:0 0 4px;"><strong>Labels:</strong> ${labels.length ? labels.map(l => `<code>${escapeHtml(l)}</code>`).join(" ") : "None"}</p>
      <p style="margin:6px 0 4px;"><strong>Description Preview:</strong></p>
      <div style="max-height:140px; overflow-y:auto; padding:8px 10px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; font-size:12px; white-space:pre-wrap;">${escapeHtml(body || "No description")}</div>
    </div>
  `;

  openGithubApprovalModal({
    action: "github_create_issue",
    title: "Approve: Create New Issue",
    description: `Review the new issue draft before creating it on ${currentWorkbenchRepo}.`,
    risk: "medium",
    previewHtml,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch("/api/github/workbench/issues/create", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            repo_name: currentWorkbenchRepo,
            title,
            body,
            labels,
            approved: true
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to create issue");

        // Clear inputs
        document.getElementById("modal-issue-title-input").value = "";
        document.getElementById("modal-issue-body-textarea").value = "";
        document.getElementById("modal-issue-labels-input").value = "";

        showSystemToast(`Created issue #${data.issue?.number || ""} successfully!`);
        await loadWorkbenchIssues(currentWorkbenchRepo);
        if (data.issue?.number) {
          await selectWorkbenchIssue(data.issue.number);
        }
      } catch (err) {
        showSystemToast("Create issue failed: " + err.message);
      }
    }
  });
}

// ----------------------------------------------------------------------------
// 3. Pull Requests Panel
// ----------------------------------------------------------------------------
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
  const listContainer = document.getElementById("github-prs-list-container");
  const stateSelect = document.getElementById("github-prs-state-select");
  const state = stateSelect?.value || "open";

  if (loader) loader.style.display = "flex";
  if (listContainer) listContainer.innerHTML = "";

  try {
    const res = await fetch(`/api/github/workbench/prs?repo_name=${encodeURIComponent(repoName)}&state=${encodeURIComponent(state)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load PRs");

    loadedWorkbenchPRs = data.pull_requests || [];
    renderWorkbenchPRsList();
  } catch (err) {
    if (listContainer) {
      listContainer.innerHTML = `<div style="color:#ef4444; font-size:12px; padding:12px;">Error loading pull requests: ${escapeHtml(err.message)}</div>`;
    }
  } finally {
    if (loader) loader.style.display = "none";
  }
}

function renderWorkbenchPRsList() {
  const listContainer = document.getElementById("github-prs-list-container");
  if (!listContainer) return;
  listContainer.innerHTML = "";

  if (loadedWorkbenchPRs.length === 0) {
    listContainer.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:24px 12px; text-align:center;">No pull requests found.</div>';
    return;
  }

  loadedWorkbenchPRs.forEach(pr => {
    const card = document.createElement("div");
    card.className = "github-workbench-item-card";
    if (currentWorkbenchPR && currentWorkbenchPR.number === pr.number) {
      card.classList.add("active");
    }

    const isOpen = pr.state === "open";
    const stateBadge = `<span class="github-badge ${isOpen ? "github-badge-success" : "github-badge-danger"}" style="font-size:10px;">${isOpen ? "Open" : "Closed"}</span>`;
    const draftChip = pr.draft ? `<span class="github-badge" style="background:#f1f5f9; color:#475569; font-size:9.5px;">Draft</span>` : "";

    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
        <span style="font-weight:600; font-size:13px; color:#1e293b;">#${pr.number} ${escapeHtml(pr.title)}</span>
        <div style="display:flex; gap:4px; align-items:center;">${draftChip}${stateBadge}</div>
      </div>
      <div style="font-size:11px; font-family:monospace; color:#475569; margin:4px 0;">
        ${escapeHtml(pr.head || "branch")} &rarr; ${escapeHtml(pr.base || "main")}
      </div>
      <div class="github-meta-sub" style="font-size:11px;">
        <span>By ${escapeHtml(pr.author || "Unknown")}</span> •
        <span>${escapeHtml(pr.updated_at || "")}</span>
      </div>
    `;

    card.addEventListener("click", () => {
      selectWorkbenchPR(pr.number);
    });

    listContainer.appendChild(card);
  });
}

async function selectWorkbenchPR(prNumber) {
  const placeholder = document.getElementById("github-pr-placeholder");
  const selectedContent = document.getElementById("github-pr-selected-content");
  const aiBox = document.getElementById("pr-ai-box");

  if (placeholder) placeholder.style.display = "none";
  if (selectedContent) selectedContent.style.display = "block";
  if (aiBox) aiBox.style.display = "none";

  document.querySelectorAll("#github-prs-list-container .github-workbench-item-card").forEach(el => {
    el.classList.remove("active");
  });

  try {
    const [prRes, diffRes] = await Promise.all([
      fetch(`/api/github/workbench/prs/${prNumber}?repo_name=${encodeURIComponent(currentWorkbenchRepo)}`),
      fetch(`/api/github/workbench/prs/${prNumber}/diff?repo_name=${encodeURIComponent(currentWorkbenchRepo)}`)
    ]);

    const prData = await prRes.json();
    const diffData = await diffRes.json();

    if (!prRes.ok) throw new Error(prData.detail || "Failed to load PR details");

    const pr = prData.pull_request || {};
    currentWorkbenchPR = pr;

    // Header & Meta
    document.getElementById("pr-detail-title").textContent = `#${pr.number} ${pr.title}`;
    document.getElementById("pr-detail-branches").textContent = `${pr.head || "branch"} → ${pr.base || "main"}`;
    document.getElementById("pr-detail-meta").textContent = `By ${pr.author || "Unknown"} • +${pr.additions || 0} / -${pr.deletions || 0} • ${pr.changed_files || 0} changed files`;

    const badgeEl = document.getElementById("pr-detail-state-badge");
    if (badgeEl) {
      const isOpen = pr.state === "open";
      badgeEl.textContent = isOpen ? "Open" : "Closed";
      badgeEl.className = `github-badge ${isOpen ? "github-badge-success" : "github-badge-danger"}`;
    }

    // Changed files & Unified Diff
    const files = diffData.files || [];
    document.getElementById("pr-files-counter").textContent = files.length;

    const filesList = document.getElementById("pr-files-list");
    if (filesList) {
      filesList.innerHTML = "";
      files.forEach(f => {
        const item = document.createElement("div");
        item.className = "github-item-card";
        item.style.padding = "6px 10px";
        item.innerHTML = `
          <div style="display:flex; justify-content:space-between; font-size:12px;">
            <span style="font-family:monospace; font-weight:600;">${escapeHtml(f.filename)}</span>
            <span style="font-size:11px; color:#64748b;">+${f.additions} / -${f.deletions} (${f.status})</span>
          </div>
        `;
        filesList.appendChild(item);
      });
    }

    // Colorize Diff Text
    const diffViewer = document.getElementById("pr-diff-viewer");
    if (diffViewer) {
      const rawDiff = diffData.diff || "";
      if (!rawDiff) {
        diffViewer.textContent = "No diff available for this pull request.";
      } else {
        const lines = rawDiff.split("\n");
        const formattedLines = lines.slice(0, 1500).map(line => {
          const esc = escapeHtml(line);
          if (line.startsWith("+++") || line.startsWith("---")) {
            return `<div style="color:#64748b; font-weight:600;">${esc}</div>`;
          } else if (line.startsWith("+")) {
            return `<div class="github-diff-add">${esc}</div>`;
          } else if (line.startsWith("-")) {
            return `<div class="github-diff-del">${esc}</div>`;
          } else if (line.startsWith("@@")) {
            return `<div class="github-diff-chunk-header">${esc}</div>`;
          } else if (line.startsWith("diff --git")) {
            return `<div style="color:#2563eb; font-weight:700; margin-top:8px;">${esc}</div>`;
          }
          return `<div>${esc}</div>`;
        }).join("");
        diffViewer.innerHTML = formattedLines;
      }
    }
  } catch (err) {
    showSystemToast("Error loading PR: " + err.message);
  }
}

async function runPRAICodeReview() {
  if (!currentWorkbenchPR || !currentWorkbenchRepo) return;

  const btn = document.getElementById("btn-pr-ai-review");
  const aiBox = document.getElementById("pr-ai-box");
  const summaryEl = document.getElementById("pr-ai-summary");
  const obsEl = document.getElementById("pr-ai-observations");

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Reviewing code changes...";
  }

  try {
    const res = await fetch(`/api/github/workbench/prs/${currentWorkbenchPR.number}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_name: currentWorkbenchRepo })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "AI review failed");

    if (aiBox) aiBox.style.display = "block";
    if (summaryEl) summaryEl.innerHTML = formatMarkdown(data.summary || "");

    if (obsEl) {
      obsEl.innerHTML = "";
      const findings = data.findings || [];
      if (findings.length === 0) {
        obsEl.innerHTML = '<div style="color:#10b981; font-size:12px; padding:6px 0;">✅ No critical issues or security flags identified in changed diffs.</div>';
      } else {
        findings.forEach(f => {
          const item = document.createElement("div");
          item.className = "github-observation-item";
          const cat = f.category || "General";
          const sev = f.severity || "medium";
          const sevClass = sev === "high" ? "github-badge-danger" : (sev === "medium" ? "github-badge-warn" : "github-badge-success");

          item.innerHTML = `
            <div class="github-observation-header">
              <div style="display:flex; align-items:center; gap:6px;">
                <span class="github-badge ${sevClass}" style="font-size:10px;">${escapeHtml(sev.toUpperCase())}</span>
                <span style="font-weight:600; font-size:12.5px;">${escapeHtml(cat)}</span>
              </div>
              <span style="font-size:11px; font-family:monospace; color:#475569;">${escapeHtml(f.file_path || "")} ${f.line_range ? `(${f.line_range})` : ""}</span>
            </div>
            <div class="github-observation-desc" style="margin-top:4px;">
              ${escapeHtml(f.description || "")}
            </div>
            ${f.suggestion ? `<div style="font-size:11.5px; color:#047857; margin-top:4px;">💡 <strong>Suggestion:</strong> ${escapeHtml(f.suggestion)}</div>` : ""}
          `;
          obsEl.appendChild(item);
        });
      }
    }
  } catch (err) {
    showSystemToast("AI review error: " + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "✨ AI Review";
    }
  }
}

function handleAddPRComment() {
  if (!currentWorkbenchPR || !currentWorkbenchRepo) return;
  const textarea = document.getElementById("pr-comment-textarea");
  const body = (textarea?.value || "").trim();

  if (!body) {
    showSystemToast("Please enter a review comment.");
    return;
  }

  const previewHtml = `
    <div style="font-size:12.5px; line-height:1.5;">
      <p style="margin:0 0 6px;"><strong>Target Repository:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p>
      <p style="margin:0 0 6px;"><strong>Pull Request:</strong> #${currentWorkbenchPR.number} — ${escapeHtml(currentWorkbenchPR.title)}</p>
      <p style="margin:0 0 4px;"><strong>Review Comment Body:</strong></p>
      <div style="max-height:120px; overflow-y:auto; padding:8px 10px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; font-size:12px; white-space:pre-wrap;">${escapeHtml(body)}</div>
      <div style="margin-top:10px; font-size:11.5px; color:#64748b;">
        🔒 This action requires confirmation. Automated merges and automated approvals are permanently disabled.
      </div>
    </div>
  `;

  openGithubApprovalModal({
    action: "github_create_pr_comment",
    title: "Approve: Post PR Review Comment",
    description: `Review your comment before posting on PR #${currentWorkbenchPR.number}.`,
    risk: "medium",
    previewHtml,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch(`/api/github/workbench/prs/${currentWorkbenchPR.number}/comment`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            repo_name: currentWorkbenchRepo,
            body,
            approved: true
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Failed to post PR comment");

        if (textarea) textarea.value = "";
        showSystemToast("PR comment posted successfully.");
      } catch (err) {
        showSystemToast("Post PR comment failed: " + err.message);
      }
    }
  });
}

// ----------------------------------------------------------------------------
// 4. Commits & Branches Panel
// ----------------------------------------------------------------------------
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
  const listEl = document.getElementById("github-commits-list");
  if (!listEl) return;
  listEl.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:12px;">Loading commits...</div>';

  try {
    const res = await fetch(`/api/github/workbench/commits?repo_name=${encodeURIComponent(repoName)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load commits");

    listEl.innerHTML = "";
    const commits = data.commits || [];
    if (commits.length === 0) {
      listEl.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:12px;">No commits found.</div>';
      return;
    }

    commits.forEach(c => {
      const item = document.createElement("div");
      item.className = "github-item-card";
      item.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-family:monospace; font-weight:700; font-size:12.5px; color:#2563eb;">${escapeHtml((c.sha || "").slice(0, 7))}</span>
          <span style="font-size:11px; color:#94a3b8;">${escapeHtml(c.date || "")}</span>
        </div>
        <div style="font-weight:600; font-size:13px; margin:4px 0 2px; color:#1e293b;">${escapeHtml(c.message || "")}</div>
        <div class="github-meta-sub" style="font-size:11px;">
          <span>Author: ${escapeHtml(c.author || "Unknown")}</span> •
          <span>Files: ${c.files_changed_count ?? 0} changed (+${c.additions ?? 0} / -${c.deletions ?? 0})</span>
        </div>
      `;
      listEl.appendChild(item);
    });
  } catch (err) {
    listEl.innerHTML = `<div style="color:#ef4444; font-size:12px; padding:12px;">Error: ${escapeHtml(err.message)}</div>`;
  }
}

async function runWorkbenchCompare() {
  if (!currentWorkbenchRepo) return;
  const base = (document.getElementById("github-compare-base-input")?.value || "").trim();
  const head = (document.getElementById("github-compare-head-input")?.value || "").trim();

  if (!base || !head) {
    showSystemToast("Please enter both base and head refs to compare.");
    return;
  }

  const resultsBox = document.getElementById("github-compare-results");
  const badgeRow = document.getElementById("github-compare-badge-row");
  const filesList = document.getElementById("github-compare-files-list");

  if (resultsBox) resultsBox.style.display = "block";
  if (badgeRow) badgeRow.innerHTML = '<div style="color:#94a3b8; font-size:12px;">Comparing refs...</div>';
  if (filesList) filesList.innerHTML = "";

  try {
    const res = await fetch(`/api/github/workbench/compare?repo_name=${encodeURIComponent(currentWorkbenchRepo)}&base=${encodeURIComponent(base)}&head=${encodeURIComponent(head)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Compare failed");

    if (badgeRow) {
      badgeRow.innerHTML = `
        <div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
          <span class="github-badge" style="background:#e0e7ff; color:#3730a3; font-weight:600;">Status: ${escapeHtml(data.status || "diverged")}</span>
          <span class="github-badge github-badge-success">Ahead by: ${data.ahead_by ?? 0}</span>
          <span class="github-badge github-badge-danger">Behind by: ${data.behind_by ?? 0}</span>
          <span class="github-badge" style="background:#f1f5f9; color:#475569;">${data.total_commits ?? 0} commits</span>
        </div>
      `;
    }

    if (filesList) {
      filesList.innerHTML = "";
      const files = data.files || [];
      if (files.length === 0) {
        filesList.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:8px 0;">No changed files in this comparison range.</div>';
      } else {
        files.forEach(f => {
          const item = document.createElement("div");
          item.className = "github-item-card";
          item.style.padding = "6px 10px";
          item.innerHTML = `
            <div style="display:flex; justify-content:space-between; font-size:12px;">
              <span style="font-family:monospace; font-weight:600;">${escapeHtml(f.filename)}</span>
              <span style="font-size:11px; color:#64748b;">+${f.additions} / -${f.deletions} (${f.status})</span>
            </div>
          `;
          filesList.appendChild(item);
        });
      }
    }
  } catch (err) {
    if (badgeRow) badgeRow.innerHTML = `<div style="color:#ef4444; font-size:12px;">Compare error: ${escapeHtml(err.message)}</div>`;
  }
}

async function loadWorkbenchBranchesTab(repoName) {
  const listEl = document.getElementById("github-branches-list");
  if (!listEl) return;
  listEl.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:12px;">Loading branches...</div>';

  try {
    const res = await fetch(`/api/github/workbench/branches?repo_name=${encodeURIComponent(repoName)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load branches");

    listEl.innerHTML = "";
    const branches = data.branches || [];
    if (branches.length === 0) {
      listEl.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:12px;">No branches returned.</div>';
      return;
    }

    branches.forEach(b => {
      const item = document.createElement("div");
      item.className = "github-item-card";
      const isProtected = b.protected;
      const isDefault = b.is_default;
      item.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <div style="display:flex; align-items:center; gap:8px;">
            <span style="font-family:monospace; font-weight:700; font-size:13px; color:#1e293b;">${escapeHtml(b.name)}</span>
            ${isDefault ? '<span class="github-badge github-badge-success" style="font-size:10px;">Default</span>' : ''}
            ${isProtected ? '<span class="github-badge github-badge-warn" style="font-size:10px;">Protected</span>' : ''}
          </div>
          <span style="font-family:monospace; font-size:11.5px; color:#64748b;">SHA: ${(b.commit_sha || "").slice(0, 7)}</span>
        </div>
      `;
      listEl.appendChild(item);
    });
  } catch (err) {
    listEl.innerHTML = `<div style="color:#ef4444; font-size:12px; padding:12px;">Error: ${escapeHtml(err.message)}</div>`;
  }
}

// ----------------------------------------------------------------------------
// 5. GitHub Actions Panel
// ----------------------------------------------------------------------------
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
  const listContainer = document.getElementById("github-actions-runs-container");
  const statusSelect = document.getElementById("github-actions-status-select");
  const status = statusSelect?.value || "";

  if (loader) loader.style.display = "flex";
  if (listContainer) listContainer.innerHTML = "";

  try {
    const res = await fetch(`/api/github/workbench/actions/runs?repo_name=${encodeURIComponent(repoName)}&status=${encodeURIComponent(status)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load workflow runs");

    loadedWorkbenchRuns = data.workflow_runs || [];
    renderWorkbenchActionsList();
  } catch (err) {
    if (listContainer) {
      listContainer.innerHTML = `<div style="color:#ef4444; font-size:12px; padding:12px;">Error loading actions: ${escapeHtml(err.message)}</div>`;
    }
  } finally {
    if (loader) loader.style.display = "none";
  }
}

function renderWorkbenchActionsList() {
  const listContainer = document.getElementById("github-actions-runs-container");
  if (!listContainer) return;
  listContainer.innerHTML = "";

  if (loadedWorkbenchRuns.length === 0) {
    listContainer.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:24px 12px; text-align:center;">No workflow runs found.</div>';
    return;
  }

  loadedWorkbenchRuns.forEach(run => {
    const card = document.createElement("div");
    card.className = "github-workbench-item-card";
    if (currentWorkbenchRun && currentWorkbenchRun.id === run.id) {
      card.classList.add("active");
    }

    const isSuccess = run.conclusion === "success";
    const isFailure = run.conclusion === "failure";
    const badgeClass = isSuccess ? "github-badge-success" : (isFailure ? "github-badge-danger" : "github-badge-warn");

    card.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
        <span style="font-weight:600; font-size:13px; color:#1e293b;">${escapeHtml(run.name || "Workflow")}</span>
        <span class="github-badge ${badgeClass}" style="font-size:10px;">${escapeHtml(run.conclusion || run.status || "queued")}</span>
      </div>
      <div style="font-size:11px; font-family:monospace; color:#475569; margin:4px 0;">
        Branch: ${escapeHtml(run.branch || "main")} • SHA: ${(run.commit_sha || "").slice(0, 7)}
      </div>
      <div class="github-meta-sub" style="font-size:11px;">
        <span>Trigger: ${escapeHtml(run.event || "push")}</span> •
        <span>${escapeHtml(run.created_at || "")}</span>
      </div>
    `;

    card.addEventListener("click", () => {
      selectWorkbenchRun(run.id);
    });

    listContainer.appendChild(card);
  });
}

async function selectWorkbenchRun(runId) {
  const placeholder = document.getElementById("github-action-placeholder");
  const selectedContent = document.getElementById("github-action-selected-content");
  const aiBox = document.getElementById("action-ai-box");

  if (placeholder) placeholder.style.display = "none";
  if (selectedContent) selectedContent.style.display = "block";
  if (aiBox) aiBox.style.display = "none";

  document.querySelectorAll("#github-actions-runs-container .github-workbench-item-card").forEach(el => {
    el.classList.remove("active");
  });

  try {
    const res = await fetch(`/api/github/workbench/actions/runs/${runId}?repo_name=${encodeURIComponent(currentWorkbenchRepo)}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failed to load run details");

    const run = data.workflow_run || {};
    currentWorkbenchRun = run;

    document.getElementById("action-detail-name").textContent = run.name || "Workflow Run";
    document.getElementById("action-detail-branch").textContent = run.branch || "main";
    document.getElementById("action-detail-meta").textContent = `Event: ${run.event || "push"} • Commit: ${(run.commit_sha || "").slice(0, 7)} • Started: ${run.created_at || ""}`;

    const badgeEl = document.getElementById("action-detail-conclusion-badge");
    if (badgeEl) {
      const isSuccess = run.conclusion === "success";
      const isFailure = run.conclusion === "failure";
      badgeEl.textContent = run.conclusion || run.status || "queued";
      badgeEl.className = `github-badge ${isSuccess ? "github-badge-success" : (isFailure ? "github-badge-danger" : "github-badge-warn")}`;
    }

    // Toggle Analyze button if failed
    const analyzeBtn = document.getElementById("btn-action-ai-analyze");
    if (analyzeBtn) {
      analyzeBtn.style.display = (run.conclusion === "failure") ? "inline-flex" : "none";
    }

    // Render Jobs & Steps
    const jobsContainer = document.getElementById("action-jobs-container");
    if (jobsContainer) {
      jobsContainer.innerHTML = "";
      const jobs = data.jobs || [];
      if (jobs.length === 0) {
        jobsContainer.innerHTML = '<div style="color:#94a3b8; font-size:12px; padding:8px 0;">No job details available.</div>';
      } else {
        jobs.forEach(job => {
          const jobCard = document.createElement("div");
          jobCard.className = "github-item-card";
          jobCard.style.padding = "10px 12px";

          const stepsHtml = (job.steps || []).map(s => {
            const isStepSuccess = s.conclusion === "success";
            const isStepFail = s.conclusion === "failure";
            const icon = isStepSuccess ? "✅" : (isStepFail ? "❌" : "⏳");
            return `
              <div style="display:flex; justify-content:space-between; font-size:12px; padding:3px 0; border-bottom:1px solid #f1f5f9;">
                <span>${icon} ${escapeHtml(s.name)}</span>
                <span style="font-size:11px; color:#94a3b8;">${escapeHtml(s.conclusion || s.status || "")}</span>
              </div>
            `;
          }).join("");

          jobCard.innerHTML = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
              <strong>Job: ${escapeHtml(job.name)}</strong>
              <span class="github-badge" style="font-size:10.5px;">${escapeHtml(job.conclusion || job.status || "")}</span>
            </div>
            <div style="padding-left:4px;">${stepsHtml}</div>
            ${job.error_logs_preview ? `
              <div style="margin-top:8px; padding:8px; background:#fef2f2; border:1px solid #fecaca; border-radius:4px; font-family:monospace; font-size:11px; color:#991b1b; white-space:pre-wrap;">
                ${escapeHtml(job.error_logs_preview)}
              </div>
            ` : ""}
          `;
          jobsContainer.appendChild(jobCard);
        });
      }
    }
  } catch (err) {
    showSystemToast("Error loading workflow details: " + err.message);
  }
}

async function runActionAIAnalysis() {
  if (!currentWorkbenchRun || !currentWorkbenchRepo) return;

  const btn = document.getElementById("btn-action-ai-analyze");
  const aiBox = document.getElementById("action-ai-box");
  const bodyEl = document.getElementById("action-ai-body");
  const suggEl = document.getElementById("action-ai-suggestions");

  if (btn) {
    btn.disabled = true;
    btn.textContent = "Diagnosing failure...";
  }

  try {
    const res = await fetch(`/api/github/workbench/actions/runs/${currentWorkbenchRun.id}/analyze`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ repo_name: currentWorkbenchRepo })
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Failure diagnosis failed");

    if (aiBox) aiBox.style.display = "block";
    if (bodyEl) bodyEl.innerHTML = formatMarkdown(data.diagnosis || "");

    if (suggEl) {
      const fixes = data.suggested_fixes || [];
      if (fixes.length > 0) {
        suggEl.innerHTML = `
          <strong style="display:block; margin-bottom:4px; font-size:12px; color:#1e293b;">Suggested Fixes & Next Steps:</strong>
          <ul style="margin:0; padding-left:18px; font-size:12px; color:#334155;">
            ${fixes.map(f => `<li>${escapeHtml(f)}</li>`).join("")}
          </ul>
        `;
      } else {
        suggEl.innerHTML = "";
      }
    }
  } catch (err) {
    showSystemToast("Analysis error: " + err.message);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "✨ Analyze Failure";
    }
  }
}

function handleSafeWorkflowRerun() {
  if (!currentWorkbenchRun || !currentWorkbenchRepo) return;

  const previewHtml = `
    <div style="font-size:12.5px; line-height:1.5;">
      <p style="margin:0 0 6px;"><strong>Target Repository:</strong> <code>${escapeHtml(currentWorkbenchRepo)}</code></p>
      <p style="margin:0 0 6px;"><strong>Workflow Run:</strong> ${escapeHtml(currentWorkbenchRun.name || "Workflow")} (ID: <code>${currentWorkbenchRun.id}</code>)</p>
      <p style="margin:0 0 6px;"><strong>Action:</strong> <span style="font-weight:600; color:#2563eb;">Rerun Workflow</span></p>
      <div style="margin-top:10px; padding:8px 10px; background:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; font-size:11.5px; color:#64748b;">
        🔒 This action requires explicit authorization and will trigger GitHub Actions remotely.
      </div>
    </div>
  `;

  openGithubApprovalModal({
    action: "github_rerun_workflow",
    title: "Approve: Rerun Workflow",
    description: `Confirm rerunning workflow '${currentWorkbenchRun.name}' on GitHub Actions.`,
    risk: "medium",
    previewHtml,
    onConfirm: async () => {
      closeGithubApprovalModal();
      try {
        const res = await fetch(`/api/github/workbench/actions/runs/${currentWorkbenchRun.id}/rerun`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            repo_name: currentWorkbenchRepo,
            approved: true
          })
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Rerun failed");

        showSystemToast("Workflow rerun requested successfully.");
        await loadWorkbenchActions(currentWorkbenchRepo);
      } catch (err) {
        showSystemToast("Rerun failed: " + err.message);
      }
    }
  });
}

// ----------------------------------------------------------------------------
// Master Workbench Initializer
// ----------------------------------------------------------------------------
function initGithubWorkbench() {
  // 1. Subnav buttons
  const subnavKeys = ["overview", "repos", "analysis", "chat", "issues", "prs", "commits", "actions"];
  subnavKeys.forEach(k => {
    document.getElementById(`btn-github-subnav-${k}`)?.addEventListener("click", () => {
      switchGithubSubnav(k);
    });
  });

  // 2. Global Repository Selector
  document.getElementById("github-global-repo-select")?.addEventListener("change", (e) => {
    currentWorkbenchRepo = e.target.value;
    const chatSelect = document.getElementById("github-chat-repo-select");
    if (chatSelect && chatSelect.value !== currentWorkbenchRepo) {
      chatSelect.value = currentWorkbenchRepo;
      if (typeof onChatRepositorySelected === "function") {
        onChatRepositorySelected(currentWorkbenchRepo);
      }
    }
    switchGithubSubnav(currentWorkbenchSubnav || "overview");
  });

  // 3. Overview Shortcuts
  document.getElementById("btn-overview-view-all-commits")?.addEventListener("click", () => {
    switchGithubSubnav("commits");
  });
  document.getElementById("btn-overview-view-all-actions")?.addEventListener("click", () => {
    switchGithubSubnav("actions");
  });

  // 4. Issues Listeners
  document.getElementById("btn-github-issues-refresh")?.addEventListener("click", () => {
    loadWorkbenchIssues(currentWorkbenchRepo);
  });
  document.getElementById("github-issues-state-select")?.addEventListener("change", () => {
    loadWorkbenchIssues(currentWorkbenchRepo);
  });
  document.getElementById("github-issues-search-input")?.addEventListener("input", debounce(() => {
    loadWorkbenchIssues(currentWorkbenchRepo);
  }, 350));
  document.getElementById("btn-github-issues-new")?.addEventListener("click", handleCreateNewIssue);
  document.getElementById("btn-issue-ai-investigate")?.addEventListener("click", runIssueAIInvestigation);
  document.getElementById("btn-issue-toggle-state")?.addEventListener("click", handleToggleIssueState);
  document.getElementById("btn-issue-submit-comment")?.addEventListener("click", handleAddIssueComment);

  // Issue Draft Modal
  document.getElementById("btn-create-issue-modal-cancel")?.addEventListener("click", () => {
    document.getElementById("github-create-issue-modal")?.classList.add("hidden");
  });
  document.getElementById("btn-create-issue-modal-submit")?.addEventListener("click", submitNewIssueFromModal);

  // 5. PRs Listeners
  document.getElementById("btn-github-prs-refresh")?.addEventListener("click", () => {
    loadWorkbenchPRs(currentWorkbenchRepo);
  });
  document.getElementById("github-prs-state-select")?.addEventListener("change", () => {
    loadWorkbenchPRs(currentWorkbenchRepo);
  });
  document.getElementById("btn-pr-ai-review")?.addEventListener("click", runPRAICodeReview);
  document.getElementById("btn-pr-submit-comment")?.addEventListener("click", handleAddPRComment);

  // 6. Commits & Branches Subtabs
  const commitPills = [
    { btn: "btn-commits-tab-history", panel: "panel-commits-history", onShow: () => loadCommitsHistoryTab(currentWorkbenchRepo) },
    { btn: "btn-commits-tab-compare", panel: "panel-commits-compare", onShow: () => {} },
    { btn: "btn-commits-tab-branches", panel: "panel-commits-branches", onShow: () => loadWorkbenchBranchesTab(currentWorkbenchRepo) }
  ];

  commitPills.forEach(p => {
    document.getElementById(p.btn)?.addEventListener("click", () => {
      commitPills.forEach(other => {
        document.getElementById(other.btn)?.classList.remove("active");
        const el = document.getElementById(other.panel);
        if (el) el.style.display = "none";
      });
      document.getElementById(p.btn)?.classList.add("active");
      const targetPanel = document.getElementById(p.panel);
      if (targetPanel) targetPanel.style.display = "block";
      p.onShow();
    });
  });

  document.getElementById("btn-github-run-compare")?.addEventListener("click", runWorkbenchCompare);

  // 7. Actions Listeners
  document.getElementById("btn-github-actions-refresh")?.addEventListener("click", () => {
    loadWorkbenchActions(currentWorkbenchRepo);
  });
  document.getElementById("github-actions-status-select")?.addEventListener("change", () => {
    loadWorkbenchActions(currentWorkbenchRepo);
  });
  document.getElementById("btn-action-ai-analyze")?.addEventListener("click", runActionAIAnalysis);
  document.getElementById("btn-action-safe-rerun")?.addEventListener("click", handleSafeWorkflowRerun);

  // 8. Approval Modal Buttons
  document.getElementById("btn-github-modal-cancel")?.addEventListener("click", closeGithubApprovalModal);
  document.getElementById("btn-github-modal-confirm")?.addEventListener("click", () => {
    if (typeof currentPendingApprovalAction === "function") {
      currentPendingApprovalAction();
    }
  });
}
'''

content += "\n" + workbench_code

with open("app/ui/app.js", "w", encoding="utf-8") as f:
    f.write(content)

print("Successfully patched app/ui/app.js!")
