# cluster_resolve changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.prompts cluster_resolve --changelog`. Do not edit by hand. -->

Resolves the sub-clusters of a later time period (B) onto the baseline taxonomy of an earlier period (A) so the two periods can be compared like for like. Each period B sub-cluster is matched to a baseline sub-cluster or flagged as new with a proposed label. Uses the same glossary as case_cluster.

- Created: 2026-10-20
- Last updated: 2026-10-20
- Versions: 1

## v1 — 2026-10-20

**Summary:** Maps each period B sub-cluster to a baseline (period A) sub-cluster or flags it as new.

- File: `v1.txt`
- Author: Copilot (prompt-author)
- Result model: `ResolveResult`

**Changes:**

- Initial version.

**Prompt:**

> Add a skill that compares two time frames (for example September and October 2026). Clusters from the two periods will have slightly different names, so add a resolve step that maps the clusters of the second period onto the first period as a baseline, flagging groups that are new. Work at sub-cluster level and roll up to clusters; batch the later period's sub-clusters.

**Validation:** status `skipped`

_Not yet run against clusters._
