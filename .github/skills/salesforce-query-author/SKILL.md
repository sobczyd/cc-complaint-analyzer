---
name: salesforce-query-author
description: "Write or revise a Salesforce SOQL query from a natural-language description using the salesforce-local MCP tools, validate it against the org, and save it as the next versioned file (vN.txt) in src\\complaint_analyzer\\queries\\<query_set>\\ with a manifest.yaml entry (prompt, summary, changes, dates, validation) and a regenerated CHANGELOG.md. Use when asked to create, extend, or rev a Salesforce/SOQL query."
argument-hint: "description of the data you need [--set <query_set>] [--org <username-or-alias>]"
user-invocable: true
disable-model-invocation: false
---

# Salesforce Query Author

Turn a user's description into a validated SOQL query and store it as an
immutable, tracked version of a query set. The pattern follows
`src\complaint_analyzer\queries\cq_crm_codes_nurse_call_no_comments\`.

## Query set layout

```
src\complaint_analyzer\queries\<query_set>\
    v1.txt, v2.txt, ...   # one SOQL query per version; never edited once written
    manifest.yaml         # source of truth for each version's history
    CHANGELOG.md          # generated from manifest.yaml; never edit by hand
```

- `<query_set>` is lower snake_case and names what the query returns, for example
  `cq_crm_codes_nurse_call_no_comments`.
- Only `vN.txt` files go in the folder. `load_queries()` loads every `*.txt`, so don't
  add scratch, draft or LIMIT-ed copies.
- Helper CLI (run from the repo root with `.\.venv\Scripts\python.exe`):
  - `-m complaint_analyzer.queries <set> --next-version` prints the next version (`v1` for a new set).
  - `-m complaint_analyzer.queries <set>` validates the manifest against the files.
  - `-m complaint_analyzer.queries <set> --changelog` validates the set and regenerates `CHANGELOG.md`.

## Run-scoped mode (ad-hoc queries)

When the request is a one-off filtered fetch (used by the `salesforce-fetch` agent), do not
create a query set, version, manifest or changelog. Follow steps 1, 2, 4, 5 and 6 below, then
hand the final SOQL to `python -m complaint_analyzer.workflows.custom_fetch init`, which saves
it as `query.soql` in a new run folder. To reuse the columns of a saved set, run
`python -m complaint_analyzer.workflows.salesforce_export fields --query-set <set>`, then
append the user's WHERE/ORDER BY. Child subquery filters in the template are kept unless the
append the user's WHERE/ORDER BY. Child subquery filters in the template are kept unless the
user asks otherwise; say so in the report. Without the salesforce-local MCP tools, verify
fields with `sf sobject describe --sobject Case --json` and let `custom_fetch init` validate
the query (a failed export leaves no run folder).

## Procedure

1. **Gather context.**
   - If the request involves Nurse Call (CareComm, RTLS, alert routing, and so on),
     read `C:\Users\sobczyd\.copilot\nursecall-AGENTS.md` first.
   - Decide whether this is a new query set or a new version of an existing one. List
     `src\complaint_analyzer\queries\` and read the existing sets' `manifest.yaml` files.
   - If you're revising a set, read its latest `vN.txt` and manifest entry. That version
     is the `base_version`.
   - If it's unclear whether the user wants a new set or a revision, ask with `ask_user`.
2. **Resolve the org.** Call `salesforce-local-get_username` with `directory` set to the
   repo root. Use `defaultTargetOrg: true` unless the user named an org. Never guess a
   username.
3. **Pick the version.** Run `--next-version` for the set and use its output (for example
   `v3`) as the new file name. Never overwrite or edit an existing `vN.txt`. Every change,
   however small, is a new version.
4. **Discover and verify fields.** Use `salesforce-local-run_soql_query` with
   `useToolingApi: true`:
   - List fields:
     `SELECT QualifiedApiName, Label, DataType FROM FieldDefinition WHERE EntityDefinition.QualifiedApiName = 'Case'`
   - Find custom objects:
     `SELECT QualifiedApiName, Label FROM EntityDefinition WHERE QualifiedApiName LIKE '%Complaint%'`
   - Child relationship names (for example `Problem_Codes__r`) come from the parent's
     relationships. Confirm them by running a small subquery.

   Use only fields that exist. Match the description to fields by label. If a field is
   ambiguous, ask the user.
5. **Draft the SOQL.**
   - Follow the existing style: one clause per line, related fields grouped together,
     subqueries indented, filters in `WHERE`, explicit `ORDER BY`.
   - Don't select comment fields (CaseComment, `Comments`, and fields with `Comment` in
     the name) unless the user explicitly asks for them. Comments can hold PHI and are
     excluded by convention.
   - Use relative date literals (`LAST_N_DAYS:30`) rather than hard-coded dates unless
     the user asks for a fixed range.
   - Don't include a `LIMIT` in the saved query unless the user asks for one.
6. **Validate live.** Run the query with `salesforce-local-run_soql_query` and append
   ` LIMIT 5` only to the validation run, not to the saved file.
   - On error, fix the query and retry. If it still fails after reasonable attempts,
     ask the user whether to save it with `validation.status: failed`.
   - Record the org, the UTC timestamp, the status and the returned row count. Never
     copy returned record data into the manifest, changelog or chat summary. Mention
     only counts and field-level issues.
7. **Write the query.** Create `src\complaint_analyzer\queries\<query_set>\<vN>.txt` with
   the final SOQL and a trailing newline.
8. **Update `manifest.yaml`.**
   - For a new set, create the file with the top-level keys. For an existing set, append
     the new version to `versions` (oldest first) and set `updated` to today.
   - Quote all dates (`"YYYY-MM-DD"`).
   - `prompt` is the user's request verbatim, including follow-up clarifications that
     shaped the query.
   - `summary` is one line.
   - `changes` lists concrete differences from `base_version`, naming the objects and
     fields that were added, removed or changed. For a new set, start with
     `Initial version.`

   ```yaml
   query_set: <query_set>                 # must equal the folder name
   description: >-
     What the set returns and why (stable across versions; update only if the purpose changes).
   created: "YYYY-MM-DD"                  # date v1 was written
   updated: "YYYY-MM-DD"                  # date of the newest version
   versions:
     - version: vN                        # sequential: v1, v2, ...
       file: vN.txt
       created: "YYYY-MM-DD"
       author: <git user.name or "Copilot (salesforce-query-author)">
       base_version: vN-1                 # null for v1
       prompt: >-
         <user's request, verbatim>
       summary: <one line>
       changes:
         - <specific change>
       objects: [Case, Account, Problem_Codes__r]   # objects/relationships queried
       validation:
         org: <username or alias from step 2>
         validated_at: "YYYY-MM-DDTHH:MM:SSZ"
         status: passed                   # passed | failed | skipped
         row_count: 5                     # rows returned by the LIMIT 5 run
         notes: <optional; errors, caveats, or why validation was skipped>
   ```

9. **Regenerate and check.**
   - Run `.\.venv\Scripts\python.exe -m complaint_analyzer.queries <query_set> --changelog`
     and fix any manifest error it reports.
   - Run `.\.venv\Scripts\python.exe -m pytest tests\test_queries.py`.
10. **Report.** Give the user:
    - the set and version
    - the file path
    - a short summary of the changes
    - the validation status and row count

    Don't commit unless asked.

## Rules

- Never overwrite, rename or delete an existing version file or manifest entry. History
  is append-only.
- `manifest.yaml` is the source of truth. `CHANGELOG.md` is always generated from it.
- Never put credentials, org IDs beyond the username or alias, or returned record data
  in any file.
- Keep each query set focused on one purpose. If the purpose changes substantially,
  start a new set instead of reving an unrelated one.
