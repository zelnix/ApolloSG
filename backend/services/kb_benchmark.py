"""Apollo KB retrieval benchmark: how well the existing lexical search (knowledge.search) finds the right record.

Measured before any semantic or vector retrieval is considered. Deterministic and repeatable: the corpus is built
from content shipped with Apollo (Learn with Higgins catalogue and starter articles, and the established scam
patterns) into its own collection with the same text index as the KB, and the same search code runs against it.
`run(live=True)` measures the live KB instead (informational: its contents change week to week).

Metrics, over the cases where a relevant record must be found:
  top1 — the first result is relevant;  top3 — a relevant record is in the first three;  miss — none in three.
Over every case that returned something: irrelevant — nothing returned was relevant (off-topic cases count when
anything at all comes back). Each miss is explained: no_text_candidates (the text index never offered a relevant
record), coverage_rule (offered, but the term-coverage rule rejected it) or outranked (accepted, ranked below three).
Diagnostic `candidates`: the same metrics for the text index's own ranking before the coverage rule, which shows
how much of a miss is the index (vocabulary) and how much is the acceptance rule.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.db import db
from services import learning
from services.higgins import knowledge
from services.higgins.tc_hawkeye import patterns

CASES_FILE = Path(__file__).resolve().parents[1] / "content" / "kb_benchmark_cases.json"
# Questions written after the main set and never used to tune the search rule: they show whether a change carries over.
HOLDOUT_FILE = Path(__file__).resolve().parents[1] / "content" / "kb_benchmark_holdout.json"
CORPUS = "kb_benchmark_corpus"


def cases(*, holdout: bool = False) -> list[dict]:
    return json.loads((HOLDOUT_FILE if holdout else CASES_FILE).read_text())["cases"]


def corpus_records() -> list[dict]:
    """Every shipped KB record, as the KB stores it (kind, key, title, body)."""
    out = []
    articles = learning._content("learning_seed_articles.json").get("articles", [])
    articles += [learning.expand_catalogue_article(a) for a in learning._content("learning_catalogue_au.json").get("articles", [])]
    for article in articles:
        out.append({"kind": "learn_article", "key": article["slug"], "title": article["title"], "body": knowledge._article_text(article)})
    for p in patterns.PATTERNS:
        if p.get("channel"):
            continue   # a phone-call pattern is a matching rule for call checks, never a library answer
        out.append({"kind": "scam_pattern", "key": p["key"], "title": f"Scam pattern: {p['name']}", "body": p["body"]})
    return out


async def build_corpus(name: str = CORPUS):
    collection = db[name]
    await collection.drop()
    knowledge.forget_weights()
    await collection.create_index([("title", "text"), ("question", "text"), ("body", "text")],
                                  weights={"title": 6, "question": 8, "body": 1}, name="kb_text", default_language="english")
    await collection.insert_many([{**r, "kb_id": f"{r['kind']}:{r['key']}", "question": "", "status": "current", "hits": 0} for r in corpus_records()])
    return collection


def _label(row: dict) -> str:
    return f"{row['kind']}:{row['key']}"


async def _candidates(collection, query: str) -> list[dict]:
    """The text index's own ranking (what knowledge.search starts from), before the acceptance rule."""
    if not knowledge.concepts(query, query=True):
        return []
    return await collection.find({"$text": {"$search": knowledge.search_words(query)}},
                                 {"_id": 0, "kind": 1, "key": 1, "title": 1, "body": 1, "status": 1, "score": {"$meta": "textScore"}}
                                 ).sort([("score", {"$meta": "textScore"}), ("kb_id", 1)]).limit(25).to_list(25)


async def _diagnose(collection, query: str, expected: set[str]) -> str:
    rows = await _candidates(collection, query)
    offered = [r for r in rows if _label(r) in expected]
    if not offered:
        return "no_text_candidates"
    weights = await knowledge._weights(collection)
    if not any(knowledge._accepts(r, knowledge.concepts(query, query=True), weights) > 0 for r in offered):
        return "coverage_rule"
    return "outranked"


async def run(*, live: bool = False, holdout: bool = False, collection_name: str = CORPUS) -> dict:
    collection = db.higgins_knowledge if live else await build_corpus(collection_name)
    results = []
    for case in cases(holdout=holdout):
        found = await knowledge.search(case["query"], limit=3, collection=collection)
        labels = [_label(r) for r in found]
        expected = set(case["expected"])
        relevant = [label in expected for label in labels]
        raw = [_label(r) for r in (await _candidates(collection, case["query"]))[:3]]
        row = {"id": case["id"], "area": case["area"], "query": case["query"], "mustFind": case["must_find"], "returned": labels,
               "top1": bool(relevant[:1] and relevant[0]), "top3": any(relevant), "irrelevant": bool(labels) and not any(relevant),
               "candidates": raw, "candidateTop1": bool(raw[:1] and raw[0] in expected), "candidateTop3": any(x in expected for x in raw),
               "candidateIrrelevant": bool(raw) and not any(x in expected for x in raw)}
        if case["must_find"] and not row["top3"]:
            row["why"] = await _diagnose(collection, case["query"], expected)
        results.append(row)
    must = [r for r in results if r["mustFind"]]
    returned = [r for r in results if r["returned"]]
    rate = lambda n, d: round(n / d, 3) if d else 0.0  # noqa: E731
    why: dict[str, int] = {}
    for r in must:
        if "why" in r:
            why[r["why"]] = why.get(r["why"], 0) + 1
    return {"corpus": "live_kb" if live else "shipped", "set": "holdout" if holdout else "main", "cases": len(results), "mustFind": len(must),
            "top1": rate(sum(r["top1"] for r in must), len(must)), "top3": rate(sum(r["top3"] for r in must), len(must)),
            "miss": rate(sum(not r["top3"] for r in must), len(must)), "irrelevant": rate(sum(r["irrelevant"] for r in returned), len(returned)),
            "offTopicReturned": sum(1 for r in results if not r["mustFind"] and r["returned"]), "missReasons": why,
            "candidates": {"top1": rate(sum(r["candidateTop1"] for r in must), len(must)), "top3": rate(sum(r["candidateTop3"] for r in must), len(must)),
                           "irrelevant": rate(sum(r["candidateIrrelevant"] for r in results if r["candidates"]), sum(1 for r in results if r["candidates"])),
                           "offTopicReturned": sum(1 for r in results if not r["mustFind"] and r["candidates"])},
            "misses": [{k: r[k] for k in ("id", "query", "returned", "why")} for r in must if not r["top3"]], "results": results}
