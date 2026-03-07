#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NOISE_PATTERNS = [
    r"\bthank you\b",
    r"\bthanks\b",
    r"\blooking forward\b",
    r"\bmust see\b",
    r"\bgreat talk\b",
    r"\bpart 2\b",
]

CLAIM_PATTERNS = [
    r"\bbenchmark\b",
    r"\bswe[- ]?bench\b",
    r"\brl\b",
    r"\benvironment\b",
    r"\bverifi",
    r"\breward\b",
    r"\btraining\b",
    r"\beval\b",
    r"\bdata\b",
    r"\bresult\b",
]


@dataclass
class Candidate:
    source_step: str
    source_file: str
    url: str
    text: str
    author: str = ""


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _iter_dict_like(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _iter_dict_like(v)
    elif isinstance(obj, list):
        for x in obj:
            yield from _iter_dict_like(x)


def _extract_from_obj(obj: Any, source_step: str, source_file: str) -> list[Candidate]:
    out: list[Candidate] = []

    # generic dict/list crawl for tweet-like objects
    for d in _iter_dict_like(obj):
        if not isinstance(d, dict):
            continue
        url = d.get("tweet_url") or d.get("url") or d.get("post_url") or ""
        text = d.get("text") or d.get("tweet_text") or d.get("content") or d.get("quote") or ""
        author = d.get("author") or d.get("author_handle") or d.get("handle") or ""

        if isinstance(url, str) and isinstance(text, str) and "x.com/" in url and text.strip():
            out.append(Candidate(source_step, source_file, url.strip(), text.strip(), str(author or "")))

    # parse escaped/truncated raw output text for tweet_url + text
    if isinstance(obj, dict):
        raw_output = obj.get("rawOutput") or obj.get("output")
        if isinstance(raw_output, str) and raw_output:
            for m in re.finditer(r'"tweet_url"\s*:\s*"(https://x.com/[^"]+)"[\s\S]{0,400}?"text"\s*:\s*"([\s\S]{20,350}?)"', raw_output):
                url = m.group(1)
                text = bytes(m.group(2), "utf-8").decode("unicode_escape", errors="ignore")
                out.append(Candidate(source_step, source_file, url, text.strip()))

            # fallback: URLs without paired text
            for url in re.findall(r'https://x.com/[^\s"\\]+/status/\d+', raw_output):
                out.append(Candidate(source_step, source_file, url, ""))

    return out


def _normalize_candidates(cands: list[Candidate]) -> list[Candidate]:
    dedup = {}
    for c in cands:
        key = c.url
        if not key:
            continue
        txt = re.sub(r"\s+", " ", c.text or "").strip()
        # keep richer text version if duplicate URL
        prev = dedup.get(key)
        if prev is None or len(txt) > len(prev.text):
            dedup[key] = Candidate(c.source_step, c.source_file, c.url, txt, c.author)
    return list(dedup.values())


def _score(text: str, topic: str) -> tuple[int, list[str]]:
    t = (text or "").lower()
    reasons: list[str] = []
    score = 0

    # relevance
    topic_tokens = [x for x in re.findall(r"[a-z0-9]{3,}", topic.lower()) if x not in {"what", "latest", "with", "and", "the"}]
    overlap = sum(1 for tok in topic_tokens if tok in t)
    score += min(overlap * 8, 32)
    if overlap:
        reasons.append(f"topic_overlap={overlap}")

    # specificity/claim density
    claim_hits = sum(1 for p in CLAIM_PATTERNS if re.search(p, t))
    score += min(claim_hits * 5, 25)
    if claim_hits:
        reasons.append(f"claim_hits={claim_hits}")

    if re.search(r"\d", t):
        score += 6
        reasons.append("has_numbers")
    if len(t) > 140:
        score += 5
        reasons.append("longer_context")

    # hard noise penalties
    for p in NOISE_PATTERNS:
        if re.search(p, t):
            score -= 60
            reasons.append(f"noise:{p}")

    return score, reasons


def _load_step_candidates(run_dir: Path) -> list[Candidate]:
    out: list[Candidate] = []
    steps_dir = run_dir / "steps"
    if not steps_dir.exists():
        return out

    for step in sorted(steps_dir.iterdir()):
        if not step.is_dir():
            continue
        source_step = step.name
        for name in ["normalized.json", "raw.json"]:
            p = step / name
            if not p.exists():
                continue
            obj = _read_json(p)
            if obj is None:
                continue
            out.extend(_extract_from_obj(obj, source_step, str(p)))

    return _normalize_candidates(out)


def _load_papers(run_dir: Path) -> list[dict]:
    p = run_dir / "steps" / "step-01-papers-alphaxiv" / "normalized.json"
    obj = _read_json(p) if p.exists() else []
    if isinstance(obj, list):
        return obj[:5]
    return []


def consolidate(repo: Path, date: str, topic: str) -> dict:
    run_dir = repo / "data" / "runs" / date
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    cands = _load_step_candidates(run_dir)
    scored = []
    rejected = []

    for c in cands:
        s, reasons = _score(c.text, topic)
        row = {
            "source_step": c.source_step,
            "source_file": c.source_file,
            "url": c.url,
            "text": c.text,
            "author": c.author,
            "score": s,
            "reasons": reasons,
        }
        if s >= 10 and c.text.strip():
            scored.append(row)
        else:
            rejected.append({**row, "rejected_reason": "low_score_or_empty_text"})

    scored.sort(key=lambda x: x["score"], reverse=True)
    selected = scored[:10]
    papers = _load_papers(run_dir)

    cons_dir = run_dir / "consolidation"
    cons_dir.mkdir(parents=True, exist_ok=True)

    selection = {
        "date": date,
        "topic": topic,
        "selected_count": len(selected),
        "selected": selected,
        "papers": papers,
    }
    (cons_dir / "selection.json").write_text(json.dumps(selection, indent=2))
    (cons_dir / "rejections.json").write_text(json.dumps(rejected, indent=2))

    trace = {
        "date": date,
        "topic": topic,
        "items": [
            {
                "rank": i + 1,
                "url": x["url"],
                "source_step": x["source_step"],
                "source_file": x["source_file"],
                "score": x["score"],
            }
            for i, x in enumerate(selected)
        ],
    }
    trace_path = (repo / "public" / "data" / f"brief-{date}.trace.json")
    if not trace_path.parent.exists():
        trace_path = (repo / "public" / f"brief-{date}.trace.json")
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps(trace, indent=2))

    lines = [
        f"Code RL briefing ({date})",
        "",
        f"Topic: {topic}",
        "",
        "Top tweet signals (SuperGrok artifacts only)",
    ]
    for x in selected:
        text = x["text"].replace("\n", " ").strip()
        if len(text) > 280:
            text = text[:277] + "..."
        lines.append(f"- {text} ({x['url']})")

    if papers:
        lines += ["", "Papers"]
        for p in papers:
            title = p.get("title", "")
            url = p.get("alphaXivUrl") or p.get("arxivUrl") or ""
            insight = p.get("insight", "")
            lines.append(f"- {title} — {insight} ({url})")

    final_md = "\n".join(lines) + "\n"
    out_md = repo / "public" / "data" / f"brief-{date}.md"
    if not out_md.parent.exists():
        out_md = repo / "public" / f"brief-{date}.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(final_md)

    return {
        "ok": True,
        "date": date,
        "selected": len(selected),
        "rejected": len(rejected),
        "out": str(out_md),
        "selection": str(cons_dir / "selection.json"),
        "trace": str(trace_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--date", required=True)
    ap.add_argument("--topic", required=True)
    args = ap.parse_args()

    res = consolidate(Path(args.repo).resolve(), args.date, args.topic)
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
