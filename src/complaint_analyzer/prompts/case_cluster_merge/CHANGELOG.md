# case_cluster_merge changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.prompts case_cluster_merge --changelog`. Do not edit by hand. -->

Consolidates the cluster and sub-cluster labels from several batch clusterings into one final taxonomy and a mapping from every batch sub-cluster to a final cluster and sub-cluster. Uses the same glossary as case_cluster.

- Created: 2026-10-19
- Last updated: 2026-10-19
- Versions: 1

## v1 — 2026-10-19

**Summary:** Final merge prompt producing a final taxonomy and batch-to-final mapping.

- File: `v1.txt`
- Author: Copilot
- Result model: `MergeResult`

**Changes:**

- Initial version.

**Prompt:**

> After batches are clustered independently, run a final aggregation that takes all labels and sub-topics generated so far and melts them into a reasonable common final label and sub-topic map, avoiding duplicates and merging highly related topics from different batches.

**Validation:** status `skipped`

_Not yet run against cases._
