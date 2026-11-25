f = open('app/ui/app.js', 'r', encoding='utf-8')
c = f.read()
f.close()

checks = [
    ('initGithubWorkbench', 'function initGithubWorkbench'),
    ('updateWorkbenchGlobalRepoSelect', 'function updateWorkbenchGlobalRepoSelect'),
    ('openGithubApprovalModal', 'function openGithubApprovalModal'),
    ('loadWorkbenchOverview', 'function loadWorkbenchOverview'),
    ('loadWorkbenchIssues', 'function loadWorkbenchIssues'),
    ('renderWorkbenchIssuesList', 'function renderWorkbenchIssuesList'),
    ('runIssueAIInvestigation', 'function runIssueAIInvestigation'),
    ('handleToggleIssueState', 'function handleToggleIssueState'),
    ('submitNewIssueFromModal', 'function submitNewIssueFromModal'),
    ('loadWorkbenchPRs', 'function loadWorkbenchPRs'),
    ('runPRAICodeReview', 'function runPRAICodeReview'),
    ('handleAddPRComment', 'function handleAddPRComment'),
    ('loadWorkbenchCommits', 'function loadWorkbenchCommits'),
    ('runWorkbenchCompare', 'function runWorkbenchCompare'),
    ('loadWorkbenchBranchesTab', 'function loadWorkbenchBranchesTab'),
    ('loadWorkbenchActions', 'function loadWorkbenchActions'),
    ('runActionAIAnalysis', 'function runActionAIAnalysis'),
    ('handleSafeWorkflowRerun', 'function handleSafeWorkflowRerun'),
    ('debounce', 'function debounce'),
    ('8-tab switchGithubSubnav', 'subnavKeys = ['),
    ('initGithubWorkbench hook', 'initGithubWorkbench'),
    ('currentWorkbenchRepo var', 'currentWorkbenchRepo = ""'),
    ('approval modal globals', 'currentPendingApprovalAction = null'),
]
all_ok = True
for name, pattern in checks:
    found = pattern in c
    print('  %s: %s' % ('OK' if found else 'MISSING', name))
    if not found:
        all_ok = False

print()
print('ALL CHECKS PASSED' if all_ok else 'SOME CHECKS FAILED')
print('Total lines: %d' % len(c.splitlines()))
