# root_cause_analysis changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.prompts root_cause_analysis --changelog`. Do not edit by hand. -->

Root cause analysis of a single service record (registry name "rca"): reported symptom, restoring action, root cause category and confidence, with cited evidence.

- Created: 2026-10-15
- Last updated: 2026-10-16
- Versions: 2

## v2 — 2026-10-15

**Summary:** Instructs the model to analyze each record independently.

- File: `v2.txt`
- Based on: v1
- Author: Sobczynski
- Result model: `RcaResult`

**Changes:**

- Added an instruction to review each record on its own and not combine records or infer patterns across the batch.

**Prompt:**

> Backfilled from git history (commit ca5b0a9); the original authoring request was not recorded.

**Validation:** status `skipped`

_Predates manifest tracking; no recorded validation run._

## v1 — 2026-10-15

**Summary:** Initial single-record root cause analysis prompt with JSON-only output.

- File: `v1.txt`
- Author: Sobczynski
- Result model: `RcaResult`

**Changes:**

- Initial version.

**Prompt:**

> Backfilled from git history (commit ca5b0a9, "Add resumable Copilot harness batch orchestration"); the original authoring request was not recorded.

**Validation:** status `skipped`

_Predates manifest tracking; no recorded validation run._
