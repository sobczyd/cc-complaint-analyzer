"""Merge drafted expected answers with rendered context and build pilot-examples.txt, selecting a
diverse, data-rich default set of 5 RCA + 5 defect examples plus 2 real 'none' examples.
"""
from __future__ import annotations

import json
from pathlib import Path

context = {}
for batch_file in sorted(Path("data/pilot_tmp").glob("batch_*.json")):
    for e in json.loads(batch_file.read_text(encoding="utf-8")):
        context[e["example_id"]] = e
drafted = json.loads(Path("data/pilot_tmp/drafted_all.json").read_text(encoding="utf-8"))

assert set(context) == set(drafted), (set(context) ^ set(drafted))


def richness(eid: str) -> tuple:
    ctx = context[eid]
    draft = drafted[eid]
    match = draft["matches"][0]
    has_kb = bool(ctx["kb_keys"]) and bool(ctx["article_text"])
    version_known = "issue_version_unknown" not in match["version_justification"] and "case_version_unknown" not in match["version_justification"]
    confidence_rank = {"high": 2, "medium": 1, "low": 0}[match["confidence"]]
    case_text_len = len(ctx["case_text"])
    return (confidence_rank, has_kb, version_known, case_text_len)


rca_ids = sorted([eid for eid, e in context.items() if e["issue_type"] == "rca"], key=richness, reverse=True)
defect_ids = sorted([eid for eid, e in context.items() if e["issue_type"] == "defect"], key=richness, reverse=True)


def pick_diverse(ids: list[str], n: int) -> list[str]:
    chosen: list[str] = []
    seen_issues: set[str] = set()
    for eid in ids:
        issue_key = context[eid]["issue_key"]
        if issue_key in seen_issues:
            continue
        chosen.append(eid)
        seen_issues.add(issue_key)
        if len(chosen) == n:
            break
    return chosen


default_rca = pick_diverse(rca_ids, 5)
default_defect = pick_diverse(defect_ids, 5)
print("default RCA examples:", default_rca)
print("default defect examples:", default_defect)

# -- render one example block --------------------------------------------------------------

def render_example(eid: str, *, is_default: bool, none_entry: dict | None = None) -> str:
    if none_entry is not None:
        header = (
            f"--- Example {eid} (match_type: none"
            + (", default" if is_default else "")
            + ") ---"
        )
        body = none_entry["case_text"]
        candidates = none_entry["candidate_text"]
        articles = none_entry["article_text"]
        expected = {
            "case_number": none_entry["case_number"],
            "match_type": "none",
            "rationale": none_entry["rationale"],
            "matches": [],
        }
    else:
        ctx = context[eid]
        draft = drafted[eid]
        header = (
            f"--- Example {eid} (true match: {ctx['issue_key']}, {ctx['issue_type']}"
            + (", default" if is_default else "")
            + ") ---"
        )
        body = ctx["case_text"]
        candidates = ctx["candidate_text"]
        articles = ctx["article_text"]
        expected = {
            "case_number": draft["case_number"],
            "match_type": draft["match_type"],
            "rationale": draft["rationale"],
            "matches": draft["matches"],
        }
    parts = [header, body]
    if articles:
        parts.append(articles)
    parts.append(candidates)
    parts.append("Expected answer for this complaint:")
    parts.append(json.dumps(expected, indent=2, ensure_ascii=False))
    return "\n".join(parts)


default_ids = set(default_rca) | set(default_defect)
blocks = []
for eid in rca_ids:
    blocks.append(render_example(eid, is_default=eid in default_ids))
for eid in defect_ids:
    blocks.append(render_example(eid, is_default=eid in default_ids))

none_blocks = []
for none_entry in json.loads(Path("data/pilot_tmp/none_examples.json").read_text(encoding="utf-8")):
    none_blocks.append(render_example(none_entry["example_id"], is_default=True, none_entry=none_entry))

header = f"""# Pilot in-context examples for the defect_mapping prompt (working data)
#
# Universe: 56 RCA/defect associations drawn from the user-supplied pilot JQL pair (30 RCA + 29
# defect issues, minus 3 defects not yet fetched: NC-6187, NC-5964, NC-5866), expanded to 78
# case-level examples (one issue can cover several cases) plus 2 real 'none' examples pulled from
# an existing defect-mapping run. See jql.json in this folder for the exact JQL strings.
#
# {len(rca_ids)} RCA examples, {len(defect_ids)} defect examples, {len(none_blocks)} none examples.
# Examples marked "(default)" are the data-richest, most diverse pick: {len(default_rca)} RCA +
# {len(default_defect)} defect + {len(none_blocks)} none, selected by highest drafted confidence,
# presence of supporting KB text, a known software version, and no two examples sharing an issue
# key.
"""

out = header + "\n\n" + "\n\n".join(none_blocks + blocks) + "\n"
Path("data/pilot_tmp/pilot-examples.txt").write_text(out, encoding="utf-8")
print("wrote", len(out), "chars,", len(blocks) + len(none_blocks), "total example blocks")
