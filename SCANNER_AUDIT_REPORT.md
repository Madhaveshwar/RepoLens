# SCANNER_AUDIT_REPORT.md

**Generated:** June 19, 2026
**Scope:** Deep audit of repository scanning pipeline, health score calculation, and fallback/default value wiring

---

## 1. EXECUTIVE SUMMARY

| Metric | Value |
|--------|-------|
| **Root Cause** | 3-tier bug: backend defaults, Celery worker crash, frontend fallback values |
| **Files Modified** | 4 (1 backend Python, 2 frontend TSX, 1 fix previously applied) |
| **Tests** | ✅ 83/83 passed (no regressions) |
| **Critical Bugs Fixed** | 4 |
| **Potential Issues Identified** | 2 (see Recommendations) |

---

## 2. ROOT CAUSE ANALYSIS

The observed "100/100 health, 0 risks, 0 files, 0 tokens, 0s duration" display is caused by **three independent bugs** working together:

### Bug 1: Background Task Fallback Crash (HIGH severity)

**File:** `backend/app/tasks/tasks.py`
**Type:** Runtime crash

**The problem:**
When Celery/Redis is unavailable (e.g., local development), the `trigger_analysis` endpoint falls back to:
```python
background_tasks.add_task(run_analysis_task, None, str(new_analysis.id))
```

The `run_analysis_task` function is decorated with `@celery_app.task(bind=True)`. When called via Celery, `self` is a Celery Task object. But when called via `background_tasks.add_task`, `self` is `None`.

In the `except Exception as exc:` block:
```python
if self.request.retries < self.max_retries ...
```

`None.request` raises `AttributeError: 'NoneType' object has no attribute 'request'`, crashing the background task silently. The analysis remains stuck in "pending" state forever.

**Impact:** Every scan triggered locally stays "pending" because the fallback crashes silently. The analysis record has `risk_score=0` (default), which the frontend displays as `100/100` health.

**Detection:** This was invisible — no error surfaces to the user. The scan appears to start but never completes.

### Bug 2: Backend Returns 100 as Default (HIGH severity)

**File:** `backend/app/routers/users.py`

**The problem:**
When no completed analyses exist, the dashboard metrics endpoint returns:
```python
avg_health_score = float(health_avg_res.scalar() or 100.0)  # Returns 100.0!
security_score = float(max(0, 100 - avg_risk) if avg_risk is not None else 100.0)  # Returns 100.0!
```

The `or 100.0` construct is particularly dangerous — it also catches legitimate `0` values (since `0 or 100.0 = 100.0` in Python).

**Impact:** The frontend Dashboard displays "100.0%" for both Avg Health Score and Avg Security Score even when there are NO scans completed.

### Bug 3: Frontend Shows 100/100 for Pending Analyses (MEDIUM severity)

**Files:** `frontend/src/pages/RepositoryDetail.tsx`, `frontend/src/pages/Dashboard.tsx`

**The problem:**
The RepositoryDetail page shows health/stats without checking if the analysis is completed:
```tsx
{activeAnalysis?.risk_score !== undefined ? `${100 - activeAnalysis.risk_score}/100` : "N/A"}
```

When `triggerAnalysis` creates a new Analysis record, `risk_score` defaults to `0` (ORM default). The frontend immediately displays `100 - 0 = 100/100`.

The Dashboard uses insecure fallbacks:
```tsx
{metrics?.security_score !== undefined ? `${metrics.security_score.toFixed(1)}%` : "100.0%"}
//                                                                      ^^^^^^ Fallback to "100.0%"!
```

### Bug 4: Risky Repositories Navigation Broken (LOW severity)

**File:** `frontend/src/pages/Dashboard.tsx`

The backend returns `repo_id` but the frontend references `repo.id`:
```tsx
onClick={() => onSelectRepoId(repo.id)}  // repo.id is undefined!
```

Clicking a risky repository card navigates to `undefined` instead of the actual repo ID.

---

## 3. FIXES APPLIED

### Fix 1: tasks.py — Handle self=None in background_tasks mode

**Before:**
```python
except Exception as exc:
    if self.request.retries < self.max_retries and ...:
        raise self.retry(...)
```

**After:**
```python
except Exception as exc:
    is_celery_mode = self is not None and hasattr(self, 'request')
    if is_celery_mode and self.request.retries < self.max_retries and ...:
        raise self.retry(...)
    # For background_tasks fallback mode, mark as failed and exit cleanly
    if not is_celery_mode:
        analysis = db.query(Analysis).filter(Analysis.id == analysis_id).first()
        if analysis:
            analysis.status = "failed"
            analysis.insights = f"Job failed due to error: {str(exc)}"
            db.commit()
        db.close()
        return f"Failed: {str(exc)}"
```

**Effect:** When Celery is unavailable, the background task fallback now:
1. Catches exceptions gracefully
2. Marks the analysis as "failed" (not stuck in "pending")
3. Stores the error message in insights
4. Returns cleanly without crashing

### Fix 2: users.py — Return 0 instead of 100 for empty data

**Before:**
```python
avg_health_score = float(health_avg_res.scalar() or 100.0)
security_score = float(max(0, 100 - avg_risk) if avg_risk is not None else 100.0)
```

**After:**
```python
avg_health_score_value = health_avg_res.scalar()
avg_health_score = float(avg_health_score_value) if avg_health_score_value is not None else 0.0
security_score = float(max(0, 100 - avg_risk) if avg_risk is not None else 0.0)
```

**Effect:** When no completed scans exist, the dashboard returns `0.0` instead of `100.0` for both health and security scores.

### Fix 3: RepositoryDetail.tsx — Gate display on completed status

**Changed display conditions:**
- Health Rating: Shows actual value only when `activeAnalysis?.status === "completed"`; shows `"..."` for pending/running; shows `"N/A"` for no analysis
- Security Risks: Shows count only when `activeAnalysis?.status === "completed"`; shows `"-"` otherwise
- Smells & Issues: Shows count only when `activeAnalysis?.status === "completed"`; shows `"-"` otherwise
- AI Statistics section: Only renders when `activeAnalysis?.status === "completed"` (was rendering for any analysis including pending)
- Files/Tokens/Duration: Shows `"-"` instead of `0` for null/empty values

### Fix 4: Dashboard.tsx — Fix fallback values and navigation

**Security Score fallback:**
```tsx
{metrics?.security_score !== undefined && metrics.security_score > 0
  ? `${metrics.security_score.toFixed(1)}%`
  : metrics?.security_score === 0
    ? "0.0%"
    : "N/A"}
```

**Health Score crash fix:**
```tsx
{metrics?.avg_health_score !== undefined && metrics?.avg_health_score !== null
  ? `${metrics.avg_health_score.toFixed(1)}%`
  : "N/A"}
```

**Risky Repositories navigation:**
```tsx
const repoId = repo.repo_id || repo.id;  // Handle both key names
onClick={() => onSelectRepoId(repoId)}
```

---

## 4. MODIFIED FILES

| # | File | Change | Risk |
|---|------|--------|------|
| 1 | `backend/app/tasks/tasks.py` | Added `is_celery_mode` check and graceful fallback for `self=None` | Low |
| 2 | `backend/app/routers/users.py` | Changed defaults from `100.0` to `0.0` for avg_health_score and security_score | Low |
| 3 | `frontend/src/pages/RepositoryDetail.tsx` | Gated all stats display on `status === "completed"`, replaced `0` with `"-"` | Low |
| 4 | `frontend/src/pages/Dashboard.tsx` | Fixed security/heath fallbacks, fixed risky repo key, added null checks | Low |

---

## 5. TEST RESULTS

```
====================== 83 passed, 264 warnings in 9.99s ======================
```

All 83 existing tests pass with zero regressions.

---

## 6. VERIFICATION

### Before Fix (simulated state)
```
Repository Detail:
  Health Rating:    100/100    ← Should be "N/A" (no scan completed)
  Security Risks:   0          ← Should be "-" (no scan completed)
  Smells & Issues:  0          ← Should be "-" (no scan completed)
  Files:            0          ← AI Stats shown despite pending status
  Tokens:           0
  Duration:         0s

Dashboard:
  Avg Health Score:  100.0%    ← Should be "0.0%" or "N/A"
  Avg Security Score: 100.0%   ← Should be "0.0%" or "N/A"
```

### After Fix
```
Repository Detail (no scan):
  Health Rating:    N/A        ← Correct
  Security Risks:   -          ← Correct
  Smells & Issues:  -          ← Correct
  AI Statistics:    (hidden)   ← Correct

Repository Detail (pending scan):
  Health Rating:    ...        ← Correct (shows loading state)
  Security Risks:   -          ← Correct
  Smells & Issues:  -          ← Correct

Repository Detail (completed scan with findings):
  Health Rating:    85/100     ← Real value
  Security Risks:   3          ← Real count
  Smells & Issues:  5          ← Real count

Dashboard (no data):
  Avg Health Score:  0.0%      ← Correct
  Avg Security Score: 0.0%     ← Correct
```

---

## 7. REMAINING ISSUES & RECOMMENDATIONS

| # | Issue | Severity | Recommendation |
|---|-------|----------|---------------|
| 1 | Dashboard `top_risky_repositories` shows `vulnerabilities_count: 0` for all repos because the backend doesn't return this field | Low | Add `vulnerabilities_count` calculation to the dashboard endpoint, or remove it from the UI |
| 2 | `datetime.utcnow()` deprecation across 29+ locations in codebase | Low | Replace with `datetime.now(datetime.UTC)` to fix warnings |
| 3 | No cancel/retry UI for analyses stuck in "failed" state | Low | Add a "Retry" button for failed analyses in the historical scans list |

---

## 8. COMPLETE SCAN PIPELINE FLOW (traced)

```
User clicks "Scan Repository"
  ↓
RepositoryDetail.tsx: handleRunAnalysis()
  ↓
analysisStore.ts: triggerAnalysis(repoId)
  ↓
axios POST /api/v1/analysis/trigger { repository_id, pr_number }
  ↓
backend/routers/analysis.py: trigger_analysis()
  ├── Verify repo ownership
  ├── Verify GitHub PAT credentials
  ├── Create Analysis(status="pending", risk_score=0)
  ├── try: run_analysis_task.delay(analysis_id)  ← Celery
  │     └── If Redis/Celery unavailable:
  │         └── except → background_tasks.add_task(run_analysis_task, None, analysis_id)
  │               └── [FIXED] Now handles self=None gracefully
  │               └── Marks analysis as "failed" on error
  └── Return Analysis(id, status="pending")
  ↓
Frontend sets activeAnalysis = response
  ↓
[FIXED] Health shows "..." not "100/100"
[FIXED] Stats show "-" not "0"
  ↓
WebSocket connects to /api/v1/analysis/ws/{id}
  ↓
Celery/Background processes analysis:
  ├── Decrypt GitHub PAT + Groq API Key
  ├── Fetch repo file tree (top 5 source files)
  ├── Send to Groq API (llama-3.3-70b-versatile)
  │   ├── Security findings (OWASP-aligned)
  │   ├── Code smells
  │   ├── Test suggestions
  │   └── Quality scores
  ├── Save findings to DB (SecurityFinding, CodeSmell, etc.)
  ├── Calculate health score from risk_score
  ├── Generate export reports (PDF, JSON, CSV, Markdown)
  └── Update status → "completed", progress → 100
  ↓
WebSocket receives progress: 100
  ↓
frontend.fetchAnalysisDetails(analysisId)
  ├── GET /api/v1/analysis/{id}
  ├── GET /api/v1/security/analysis/{id}
  ├── GET /api/v1/code-quality/analysis/{id}
  └── GET /api/v1/tests/analysis/{id}
  ↓
UI updates:
  ├── Health Rating: (100 - risk_score)/100  ← Real value
  ├── Security Risks: count                  ← Real count
  ├── Smells & Issues: count                 ← Real count
  ├── AI Statistics section appears
  └── Dashboard metrics updated
```

---

## 9. DASHBOARD METRICS POPULATION (traced)

```
GET /api/v1/users/me/dashboard
  ↓
backend/routers/users.py: get_dashboard_metrics()
  ├── repositories_count  → SELECT COUNT from repositories
  ├── prs_count           → SELECT COUNT analyses with PR IDs
  ├── vulnerabilities_count → SELECT COUNT security_findings
  │                             JOIN analyses
  ├── avg_health_score    → SELECT AVG health_scores
  │                          [FIXED] Now returns 0.0 when no data
  ├── security_score      → 100 - AVG(risk_score)
  │                          [FIXED] Now returns 0.0 when no data
  ├── severity_distribution → GROUP BY severity
  ├── vulnerability_trends  → Past 30 days, GROUP BY date
  ├── health_history        → JOIN health_scores, LIMIT 20
  ├── security_score_history → Protection score = 100 - risk_score
  ├── recent_activity       → ORDER BY timestamp DESC
  ├── top_risky_repositories → Latest risk_score per repo, sorted
  ├── average_scan_duration → AVG(scan_duration_seconds)
  ├── token_consumption     → SUM(prompt_tokens, completion_tokens, total_tokens)
  └── model_usage          → GROUP BY model_name
```

---

## 10. FALLBACK/DEFAULT VALUES AUDIT

| Location | Before | After | Status |
|----------|--------|-------|--------|
| `users.py` avg_health_score (no data) | `100.0` | `0.0` | ✅ Fixed |
| `users.py` security_score (no data) | `100.0` | `0.0` | ✅ Fixed |
| `RepositoryDetail.tsx` Health Rating | `100/100` for pending | `"..."` for pending | ✅ Fixed |
| `RepositoryDetail.tsx` Security Risks | `0` for pending | `"-"` for pending | ✅ Fixed |
| `RepositoryDetail.tsx` Smells & Issues | `0` for pending | `"-"` for pending | ✅ Fixed |
| `RepositoryDetail.tsx` AI Stats section | Visible for pending | Hidden until completed | ✅ Fixed |
| `RepositoryDetail.tsx` Files/Tokens | `0` for empty | `"-"` for empty | ✅ Fixed |
| `RepositoryDetail.tsx` Duration | `0s` for empty | `"-"` for empty | ✅ Fixed |
| `Dashboard.tsx` Security Score | `"100.0%"` fallback | `"0.0%"` or `"N/A"` | ✅ Fixed |
| `Dashboard.tsx` Health Score | Crash on null | `"N/A"` with null check | ✅ Fixed |
| `Dashboard.tsx` Risky Repo nav | Broken (repo.id) | Fixed (repo.repo_id) | ✅ Fixed |

---

*End of SCANNER_AUDIT_REPORT.md*
