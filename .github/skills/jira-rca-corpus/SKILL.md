---
name: jira-rca-corpus
description: "Build or refresh the reusable corpus of Nurse Call Jira defects (NC, Defect_CC) and root cause analyses (RCA), plus the Confluence KB articles that complaint qualifications cite, and summarize each issue's comment thread so the saved corpus carries a comment summary. Use before defect mapping, or when asked to refresh the defect / RCA / KB data."
argument-hint: "[--kind defect|rca] [--out-dir data\\jira\\<name>] [--kb-for <run-id>]"
user-invocable: true
disable-model-invocation: false
---

# Jira and KB Corpus

Builds the inputs the `defect-mapping` skill needs. Python plans and normalizes; this agent makes the
Atlassian MCP calls, because Python cannot. Everything is stored like the case data so it is reused
across runs. Resolve paths from the repository root and use `.\.venv\Scripts\python.exe`.

Read `C:\Users\sobczyd\.copilot\nursecall-AGENTS.md` first.

## Atlassian site

cloudId `07904935-dccc-4700-ac5d-7443322e0ce2` (`baxter-international.atlassian.net`). Confirm with
`com-atlassian-atlassian-mcp-server-getAccessibleAtlassianResourc`. The `hill-rom.atlassian.net` site
is **not** accessible; KB links pointing there are recorded as `site_not_accessible`, never guessed.

## Jira corpus

1. `... defect_mapping jira-plan --out-dir data\jira\<name> --kind defect|rca` writes `manifest.json`
   with the JQL and the field ids to request.
   - defects: `project = NC AND issuetype = "Defect_CC" AND created >= "2022-01-01" ORDER BY key ASC`
   - RCAs: `project = RCA AND issuetype = "Root Cause Analysis" ORDER BY key ASC`
   - A version filter cannot be expressed in JQL for these fields (`fixVersion ~ "4."` matches nothing);
     fetch the set above and filter by `versions_reported` / `versions_fix` afterwards.
2. Page through `com-atlassian-atlassian-mcp-server-searchJiraIssuesUsingJql` with `maxResults: 50`,
   the manifest's `fields`, and the previous page's `nextPageToken`. **Never read the issue text.** The
   runtime offloads each large result to a temp file; `Copy-Item` that file to
   `data\jira\<name>\raw\page_NN.json`. Read back only `nextPageToken` and `isLast` with a small script.
3. `... defect_mapping jira-normalize --dir data\jira\<name>` writes `issues.jsonl` and `issues.xlsx`
   and reports `issue_count`, `with_comments`, `with_case_numbers` and `with_comment_summary`.

Search results carry a comment *count*, not comment bodies. To add bodies, fetch per issue with
`getJiraIssue` (`fields: ["comment"]`) or `listJiraIssueComments` and save each result into `raw\`;
re-run `jira-normalize`.

## Comment summaries

1. `... defect_mapping jira-comment-dataset --dir data\jira\<name> --out data\jira\<name>\comments.xlsx`
   writes one row per issue that has comments, with an `Issue Context` column.
2. Summarize it with the `copilot-batch-run` skill using the `defect_comment_summary` prompt, id field
   `issue_key`, context field `Issue Context`.
3. `... defect_mapping jira-normalize --dir data\jira\<name> --summaries <run>\results.jsonl` writes the
   `comment_summary` back into `issues.jsonl` / `issues.xlsx`, so it is saved with the corpus.

## KB corpus

1. `... defect_mapping kb-plan --out-dir data\kb\<name> --workbook data\runs\<run-id>\cases_with_summaries.xlsx
   [--assignments <clusters>\case_assignments.jsonl]` lists the unique articles cited through
   `HRCSVC21_URL__c` on the *Complaint Qualifications* sheet, plus the case-to-article index.
2. For each article in `manifest.json`, call `com-atlassian-atlassian-mcp-server-getConfluenceContent`
   with `content_id` set to the tiny-link key, `content_format: "markdown"`, `detail: "full"`, and save
   the result to `data\kb\<name>\pages\<key>.json` (copy the offloaded temp file when there is one).
3. `... defect_mapping kb-normalize --dir data\kb\<name>` writes `articles.jsonl` and reports which keys
   are still missing.

## Rules

- Read-only: never create, edit or transition a Jira issue or Confluence page.
- Never paste issue, comment or article text into chat; report counts and keys only.
- Report the org, the issue and article counts, and anything that could not be fetched.
