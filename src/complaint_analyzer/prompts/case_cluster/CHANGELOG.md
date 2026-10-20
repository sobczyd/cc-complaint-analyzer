# case_cluster changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.prompts case_cluster --changelog`. Do not edit by hand. -->

Groups a batch of summarized Nurse Call cases into clusters of similar meaning and intent, with labelled sub-clusters that cite CaseNumbers. A Nurse Call glossary is injected via {{GLOSSARY}} from glossary.md.

- Created: 2026-10-19
- Last updated: 2026-10-19
- Versions: 1

## v1 — 2026-10-19

**Summary:** Batch clustering prompt with glossary context, JSON clusters and sub-clusters.

- File: `v1.txt`
- Author: Copilot
- Result model: `BatchClusterResult`

**Changes:**

- Initial version.
- Glossary built from nursecall-AGENTS.md, Jama CWS Design Documents (CWS-CMP-122, CWS-CMP-320) and the summaries.

**Prompt:**

> Cluster batches of 100 case summaries (case_summary.summary, reported_issue, product, actions_taken, resolution, status, key_points, rendered as "{Column name}: {Column contents}") by meaning and intent. Provide a glossary of Nurse Call terms as standing context. Return a label and rationale per cluster and short-label sub-clusters with cited case numbers.

**Validation:** status `skipped`

_Not yet run against cases._
