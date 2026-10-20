# defect_comment_summary changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.prompts defect_comment_summary --changelog`. Do not edit by hand. -->

Condenses the comment thread of one Jira defect or RCA into a technical summary, key points, the root cause and the fix or workaround, so the issue can be matched against complaints later.

- Created: 2026-10-19
- Last updated: 2026-10-19
- Versions: 1

## v1 — 2026-10-19

**Summary:** Per-issue comment thread summary with key points, root cause and fix or workaround.

- File: `v1.txt`
- Author: Copilot
- Result model: `CommentSummary`

**Changes:**

- Initial version.

**Prompt:**

> First summarize the defect comments and then add that comment summary to the defect, so the mapping prompt can use it. Keep the technical substance needed to decide whether the issue explains a customer complaint.

**Validation:** status `skipped`

_Not yet run against issues._
