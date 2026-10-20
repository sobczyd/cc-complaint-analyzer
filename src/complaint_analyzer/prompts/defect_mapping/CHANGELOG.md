# defect_mapping changelog

<!-- Generated from manifest.yaml by `python -m complaint_analyzer.prompts defect_mapping --changelog`. Do not edit by hand. -->

Maps a batch of complaints from one cluster sub-topic to existing Jira defects (NC) and root cause analyses (RCA), using the case summaries, their KB article text and a version-filtered candidate list. The Nurse Call glossary is injected via {{GLOSSARY}} and the historical issue-to-case associations via {{EXAMPLES}} from known_mappings.csv.

- Created: 2026-10-19
- Last updated: 2026-10-19
- Versions: 1

## v1 — 2026-10-19

**Summary:** Batch defect and RCA mapping with glossary, KB article context and historical examples.

- File: `v1.txt`
- Author: Copilot
- Result model: `MappingResult`

**Changes:**

- Initial version.
- Glossary shared with case_cluster; examples from 388 historical NC and RCA associations.
- Returns ranked matches per complaint with rationale, version justification and cited KB articles.

**Prompt:**

> Review each cluster of complaints by sub-topic (optionally batched) and decide which existing defects or RCAs, if fixed, would likely have addressed the complaint. Filter candidates by reported software version or a later fix version, supply the case summary and the KB article text for traceability, and include past defect-to-case associations as in-context examples.

**Validation:** status `skipped`

_Not yet run against complaints._
