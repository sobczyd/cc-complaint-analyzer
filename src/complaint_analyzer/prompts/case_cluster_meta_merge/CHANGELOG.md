# case_cluster_meta_merge changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.prompts case_cluster_meta_merge --changelog`. Do not edit by hand. -->

Combines the intermediate taxonomies produced by group merges (case_cluster_merge) into one higher-level taxonomy, for runs with too many batches for a single merge. Maps every intermediate sub-cluster to a final cluster and sub-cluster. Uses the same glossary as case_cluster.

- Created: 2026-10-19
- Last updated: 2026-10-19
- Versions: 1

## v1 — 2026-10-19

**Summary:** Meta-merge prompt that unifies group-merge taxonomies into one final taxonomy.

- File: `v1.txt`
- Author: Copilot (prompt-author)
- Result model: `MergeResult`

**Changes:**

- Initial version.

**Prompt:**

> When a whole month of complaints (about 2000) is clustered, the aggregation has to run several times. Add a meta-like aggregation of clusters/sub-clusters that combines the results of the different aggregations, since a single prompt cannot aggregate thousands of cases.

**Validation:** status `skipped`

_Not yet run against cases._
