"""Build per-association example context (case + top candidates + KB) for the pilot universe,
reusing the real defect_mapping pipeline helpers so the examples mirror actual request shapes.
"""
from __future__ import annotations

import json
from pathlib import Path

import sys
sys.path.insert(0, "src")

from complaint_analyzer.workflows.defect_mapping import mapping  # noqa: E402

ROOT = Path(".")
WORKBOOK = ROOT / "data/runs/pilot_nc_examples_2026-10-21/cases_with_summaries.xlsx"
UNIVERSE = json.loads((ROOT / "data/pilot_universe.json").read_text(encoding="utf-8"))
KB_INDEX_FILE = ROOT / "data/kb/pilot_nc_examples/index.jsonl"
KB_ARTICLES_FILE = ROOT / "data/kb/pilot_nc_examples/articles.jsonl"

all_cases = sorted({c for v in UNIVERSE.values() for c in v})
cases = mapping.read_cases(WORKBOOK, case_numbers=all_cases)
issues = mapping.load_corpus([Path("data/jira/nc_defects_4x"), Path("data/jira/rca_all")])
by_key = {i["issue_key"]: i for i in issues}
index = mapping.Similarity([(i["issue_key"], mapping._issue_text(i)) for i in issues])

articles = {}
for line in KB_ARTICLES_FILE.open(encoding="utf-8"):
    o = json.loads(line)
    articles[o["key"]] = o

kb_index: dict[str, list[str]] = {}
if KB_INDEX_FILE.exists():
    for line in KB_INDEX_FILE.open(encoding="utf-8"):
        o = json.loads(line)
        kb_index.setdefault(o["case_number"], []).append(o["key"])


def score_all(case: dict) -> dict[str, float]:
    query = " ".join(case["values"][c] for c in mapping.SUMMARY_COLUMNS)
    vector = index._vector(mapping.Counter(mapping.tokenize(query)))
    scores = {}
    for doc_id, doc_vector in zip(index.ids, index.vectors):
        scores[doc_id] = sum(w * doc_vector.get(t, 0.0) for t, w in vector.items())
    return scores


examples = []
for issue_key, case_numbers in UNIVERSE.items():
    issue = by_key.get(issue_key)
    if issue is None:
        print(f"SKIP {issue_key}: not in corpus")
        continue
    # one example per case in this association (matches a real one-case-to-issue request row)
    for case_number in case_numbers:
        if case_number not in cases:
            print(f"SKIP {issue_key}/{case_number}: case not fetched")
            continue
        case = cases[case_number]
        scores = score_all(case)
        keep, reason = mapping.version_match(case["version"], issue)
        ranked = sorted(
            (k for k in scores if k != issue_key),
            key=lambda k: (-scores[k], k),
        )
        distractors = ranked[:5]
        candidates = [
            {
                "issue": issue,
                "score": round(scores.get(issue_key, 0.0), 4),
                "version_reason": reason,
            }
        ]
        for key in distractors:
            d_issue = by_key[key]
            d_keep, d_reason = mapping.version_match(case["version"], d_issue)
            candidates.append(
                {
                    "issue": d_issue,
                    "score": round(scores[key], 4),
                    "version_reason": d_reason if d_keep else f"{d_reason} (would be excluded)",
                }
            )
        candidates.sort(key=lambda c: (-c["score"], c["issue"]["issue_key"]))
        kb_keys = [k for k in kb_index.get(case_number, []) if k in articles]
        case_text = mapping.render_case(case, kb_keys)
        candidate_text = "\n".join(mapping.render_issue(c) for c in candidates)
        article_text = "\n".join(mapping.render_article(articles[k]) for k in kb_keys)
        examples.append(
            {
                "issue_key": issue_key,
                "issue_type": "rca" if issue["project"] == "RCA" else "defect",
                "case_number": case_number,
                "case_text": case_text,
                "candidate_text": candidate_text,
                "article_text": article_text,
                "candidate_keys": [c["issue"]["issue_key"] for c in candidates],
                "kb_keys": kb_keys,
            }
        )

print("built", len(examples), "positive examples from", len(UNIVERSE), "associations")
Path("data/pilot_tmp/examples_context.json").write_text(
    json.dumps(examples, indent=2, ensure_ascii=False), encoding="utf-8"
)
