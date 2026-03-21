# Fix Issues — Expert Engineers Working in Parallel

**PURPOSE:** Invoke expert engineers to fix issues from the review, working in parallel on independent groups. Engineers THINK before coding — they identify root causes and fix clusters of related issues together, not one-by-one patches.

---

## THE PROMPT

Copy-paste this into a new Claude Code session:

```
Read these files in this order:
1. docs/context/SESSION-CONTEXT.md
2. docs/reviews/BUILD-WITH-EXPERTS.md
3. docs/reviews/ISSUES.md
4. CLAUDE.md

Now act as the engineering team described in BUILD-WITH-EXPERTS.md.

PHASE 1 — THINK (before writing ANY code):

Group the issues from ISSUES.md by ROOT CAUSE, not by panel.
Many issues are symptoms of the same underlying problem.
For example:
- "validate_trade never called" + "risk limits bypassed" = same root cause
- "no persistence" + "state lost on restart" = same root cause
- "no input validation" + "malformed data crashes" = same root cause

For each root cause group:
1. Identify the SINGLE fix that solves ALL issues in the group
2. List which files need to change
3. Identify dependencies between groups (which must be fixed first)

PHASE 2 — PLAN:

Create a fix plan with parallel lanes:
- Lane A: Issues that touch engine/src/risk/ (Risk Engineer)
- Lane B: Issues that touch engine/src/execution/ (Systems Engineer)
- Lane C: Issues that touch engine/src/learning/ (AI/ML Engineer)
- Lane D: Issues that touch engine/src/agent/ (multiple engineers)
- Lane E: Issues that touch engine/src/data/ (Data Engineer)
- Lane F: Issues that touch engine/src/api/ or security (Security Engineer)
- Lane G: Issues that touch engine/tests/ or architecture (Code Architect)

Lanes that don't share files can run in parallel.
Lanes that share files must be sequenced.

PHASE 3 — BUILD:

For each lane, invoke the appropriate expert engineers from BUILD-WITH-EXPERTS.md.
Use the Agent tool to run independent lanes in parallel.
Each agent should:
1. Read the relevant files
2. Fix all issues in its lane
3. Run tests after fixing
4. Report what was fixed

PHASE 4 — VERIFY:

After all lanes complete:
1. Run full test suite
2. Check for regressions
3. Update ISSUES.md with new statuses
4. Commit with clear message

IMPORTANT RULES:
- Think in ROOT CAUSES, not individual issues. 10 issues might have 3 root causes.
- Fix the root cause, not the symptom. One good fix > 10 patches.
- If an issue is actually a non-issue or already fixed, mark it as such with evidence.
- Some "issues" from the review may conflict with each other — use engineering judgment.
- Run tests after EVERY group of changes, not just at the end.
- The 177 issues likely collapse to ~30-50 actual fixes after dedup and root-cause analysis.
```

---

## NOTES

- The 177 issues from the 10-panel review have significant overlap
- Many issues are the same problem reported by different panels
- Root-cause grouping should reduce 177 → ~30-50 actual fixes
- The THINK phase is critical — without it, you get 177 patches instead of 30 solutions
- Engineers should also flag issues that are WRONG or already handled
