# Changes since last publish — 2026-11-01 (session 2)

## Investigation Expiry Overhaul
- Removed fixed 15-minute case expiry timer from `caseStore.ts`
- Server case lifetime extended from 15 min → 24 hours (matches evidence retention)
- When server copy becomes unavailable, device-local saved findings are automatically displayed
- Follow-ups answered from saved device findings (no Gemini call)
- Backend: capacity.py, retention.py, repository.py updated (backward-compatible migration)
- Frontend: caseStore.ts, ask.tsx, InvestigationView.tsx — all "15-minute" and "submit again" messages removed

## Patrol History Unified Activity Log
- New: `activityLog.ts`, `activityRecorder.ts`, `patrolActivity.ts`
- Rewritten: `patrol/history.tsx` — filters, grouping, expandable detail, accurate attribution
- Hooks into health coordinator and posture monitor to capture device security changes
- Export includes unified activity log; deletion never touches linked Threat Cases

## Threats Screen Detail Fix
- `patrol.tsx` ThreatCard now uses `eventBrief()` for rich two-line summaries (matches Home screen)

## Tab Layout Fix
- `patrol/[id].tsx` tab bar styles aligned with InvestigationView (was stacking vertically)

### Files changed
- backend: `services/higgins/capacity.py`, `services/higgins/retention.py`, `services/higgins/repository.py`
- frontend: `src/investigation/caseStore.ts`, `app/(tabs)/ask.tsx`, `src/components/InvestigationView.tsx`
- frontend: `src/store/activityLog.ts` (new), `src/store/activityRecorder.ts` (new), `src/domain/patrolActivity.ts` (new)
- frontend: `app/patrol/history.tsx`, `src/protection/healthStore.ts`, `src/store/ApolloContext.tsx`, `src/utils/exportPatrol.ts`
- frontend: `app/(tabs)/patrol.tsx`, `app/patrol/[id].tsx`
