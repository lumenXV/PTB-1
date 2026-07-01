# Contributing

PTB-1 values disciplined engineering over speed.

## Core Rules

- Keep the project simple.
- Every commit must leave the project runnable.
- Do not add dependencies without explaining why.
- Do not add features outside the current milestone.
- Keep one responsibility per module.
- Never fabricate test results.
- Never remove working functionality unless requested.
- Prefer readable code over clever code.

## Workflow

Before writing code:

1. Explain the design.
2. Wait for approval if architecture changes.
3. Implement.
4. Verify.
5. Commit.
6. Ensure the project still runs.

## Pull Request Checklist

Every pull request must include:

- What changed.
- Why it changed.
- Files modified.
- Architecture impact.
- Dependencies added, if any.
- How to run.
- Verification steps.

## Dependency Policy

Do not add dependencies by default.

A dependency is acceptable only when it clearly improves PTB-1's ability to discover or validate trading strategies and the reason is documented.

## Current Verification Command

```powershell
python -m ptb1 --data sample_prices.csv
```
