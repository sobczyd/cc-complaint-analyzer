---
name: jama-nursecall-context
description: "Use the jama-local MCP tools to pull technical terms, acronyms and definitions from the Nurse Call - Parent Repository (Jama project 28, CWS) design-document components, and update the Nurse Call glossary used by the case-clustering prompts. Use when asked to refresh or extend the Nurse Call glossary or to look up what a Nurse Call term or acronym means in Jama."
argument-hint: "[term or topic to research]"
user-invocable: true
disable-model-invocation: false
---

# Jama Nurse Call Context

Collect vocabulary context from Jama; this is read-only research (never create or edit Jama items).
Jama is used for many other tasks; this skill covers only definitions, acronyms and technical terms.

## Where the terms live

Project `28` (CWS, "Nurse Call - Parent Repository"). Start from these components:

| Component | Item ID |
|---|---|
| Design Documents (`CWS-CMP-122`) | `1056741` |
| Software Design Documents (`CWS-CMP-320`) | `1164651` |

Children are Sets/Folders such as "Software Design Documents" (`1164657`), "Design Specs" (`1138186`)
and "Hardware Technical Designs" (`1056745`), then one folder per design document (`NPD#####`).
Definitions usually sit in items named "Definitions", "Definitions or Acronyms", "Definitions and
Acronyms", "Glossary of Terms" or "Terms and Abbreviations" (Text or Design Spec items).

## Procedure

1. `jama-local-search_jama_entities` with `project_id: "28"` and `parent_id` to walk down from a component
   (page with `limit: 100`/`offset`), or `contains` with `"name:Definitions"`-style Lucene terms to find
   definition items directly. Narrow by `item_type_ids` (`33` Text, `65` Design Spec).
2. `jama-local-get_jama_entity_details` with `entity_id` for each candidate. Descriptions are
   returned only when they are 2000 characters or fewer; longer ones are reported as omitted. For those,
   record the item key (for example `CWS-DES-3302`) as "not readable via MCP" and ask the user to paste it
   rather than guessing the content.
3. Extract `term - expansion/definition` pairs, noting the source item key. Do not infer an expansion that
   Jama does not state; mark inferred ones "(unconfirmed)".
4. Update `src\complaint_analyzer\prompts\case_cluster\glossary.md` (add or correct entries, keep the
   "Clustering rules" section). Because the glossary is part of the prompt, bump the prompt versions with
   the `prompt-author` skill after changing it (`case_cluster` and `case_cluster_merge`).

## Known definition items

Readable: `CWS-TXT-1670` (generic vs formal product names), `CWS-DES-8299` (NPS, ADT), `CWS-TXT-903`
(PAL, patient and bed weight), `CWS-DES-3912` (OTS, DUT, DTS, UCTS). Not readable in full via MCP (over
2000 characters): `CWS-DES-3302`, `CWS-DES-8237`, `CWS-DES-7934`, `CWS-DES-3597`, `CWS-TXT-1535`,
`CWS-TXT-2180`.
