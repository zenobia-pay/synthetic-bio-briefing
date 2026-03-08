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
    r"\bmust[- ]?see\b",
    r"\bgreat (talk|thread|video|work|job)\b",
    r"\blove this\b",
    r"\bso good\b",
    r"\bcool stuff\b",
    r"\blooking forward\b",
    r"\bpart\s*\d+\b",
    r"\bshout[- ]?out\b",
    r"\bmichael levin.*(thank|must[- ]?see)\b",
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
    r"\bmodel\b",
    r"\bpaper\b",
    r"\brelease\b",
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


def _extract_json_chunks(text: str) -> list[str]:
    out: list[str] = []
    if not text:
        return out
    fence = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text)
    out.extend(fence)
    for opener, closer in (("{", "}"), ("[", "]")):
        i = 0
        while i < len(text):
            s = text.find(opener, i)
            if s < 0:
                break
            depth, in_str, esc = 0, False, False
            j = s
            while j < len(text):
                ch = text[j]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                else:
                    if ch == '"':
                        in_str = True
                    elif ch == opener:
                        depth += 1
                    elif ch == closer:
                        depth -= 1
                        if depth == 0:
                            out.append(text[s:j + 1])
                            i = j + 1
                            break
                j += 1
            else:
                i = s + 1
                continue
    out.append(text)
    return out


def _parse_jsonish_text(text: str) -> list[Any]:
    vals: list[Any] = []
    seen = set()
    for chunk in _extract_json_chunks(text):
        c = chunk.strip()
        if not c or c in seen:
            continue
        seen.add(c)
        for candidate in (c, c.replace('\\"', '"').replace("\\n", "\n")):
            try:
                vals.append(json.loads(candidate))
                break
            except Exception:
                continue
    return vals


def _candidate_from_dict(d: dict, source_step: str, source_file: str) -> Candidate | None:
    url = d.get("tweet_url") or d.get("url") or d.get("post_url") or ""
    text = d.get("text") or d.get("tweet_text") or d.get("content") or d.get("quote") or d.get("body") or ""
    author = d.get("author") or d.get("author_handle") or d.get("handle") or ""
    if isinstance(url, str) and isinstance(text, str) and "x.com/" in url and text.strip():
        return Candidate(source_step, source_file, url.strip(), re.sub(r"\s+", " ", text).strip(), str(author or ""))
    return None


def _extract_from_obj(obj: Any, source_step: str, source_file: str) -> list[Candidate]:
    out: list[Candidate] = []

    for d in _iter_dict_like(obj):
        if isinstance(d, dict):
            c = _candidate_from_dict(d, source_step, source_file)
            if c:
                out.append(c)

    # Parse embedded/escaped/trailing JSON strings from any text field
    for d in _iter_dict_like(obj):
        if not isinstance(d, dict):
            continue
        for k, v in d.items():
            if isinstance(v, str) and (k in {"output", "rawOutput", "text", "content"} or "x.com/" in v):
                for parsed in _parse_jsonish_text(v):
                    for dd in _iter_dict_like(parsed):
                        if isinstance(dd, dict):
                            c = _candidate_from_dict(dd, source_step, source_file)
                            if c:
                                out.append(c)
                for m in re.finditer(r'https://x.com/[^\s"\\]+/status/\d+', v):
                    out.append(Candidate(source_step, source_file, m.group(0), "", ""))

    return out


def _normalize_candidates(cands: list[Candidate]) -> list[Candidate]:
    dedup: dict[str, Candidate] = {}
    for c in cands:
        if not c.url:
            continue
        prev = dedup.get(c.url)
        if prev is None or len(c.text) > len(prev.text):
            dedup[c.url] = c
    return list(dedup.values())


def _is_fluff(text: str) -> tuple[bool, str]:
    t = (text or "").lower()
    for p in NOISE_PATTERNS:
        if re.search(p, t):
            return True, p
    return False, ""


def _score(text: str, topic: str) -> tuple[int, list[str]]:
    t = (text or "").lower()
    reasons: list[str] = []
    score = 0

    topic_tokens = [x for x in re.findall(r"[a-z0-9]{3,}", topic.lower()) if x not in {"what", "latest", "with", "and", "the", "are", "most"}]
    overlap = sum(1 for tok in topic_tokens if tok in t)
    score += min(overlap * 8, 32)
    if overlap:
        reasons.append(f"topic_overlap={overlap}")

    claim_hits = sum(1 for p in CLAIM_PATTERNS if re.search(p, t))
    score += min(claim_hits * 6, 36)
    if claim_hits:
        reasons.append(f"claim_hits={claim_hits}")

    if re.search(r"\d", t):
        score += 6
        reasons.append("has_numbers")
    if len(t) > 130:
        score += 4
        reasons.append("longer_context")
    if "http" in t:
        score += 2

    return score, reasons


def _load_step_candidates(run_dir: Path) -> list[Candidate]:
    out: list[Candidate] = []
    steps_dir = run_dir / "steps"
    if not steps_dir.exists():
        return out
    for step in sorted(steps_dir.iterdir()):
        if not step.is_dir():
            continue
        for name in ["normalized.json", "raw.json"]:
            p = step / name
            if not p.exists():
                continue
            obj = _read_json(p)
            if obj is None:
                continue
            out.extend(_extract_from_obj(obj, step.name, str(p)))
    return _normalize_candidates(out)


def _load_papers(run_dir: Path) -> list[dict]:
    p = run_dir / "steps" / "step-01-papers-alphaxiv" / "normalized.json"
    obj = _read_json(p) if p.exists() else []
    return obj[:5] if isinstance(obj, list) else []


def consolidate(repo: Path, date: str, topic: str) -> dict:
    run_dir = repo / "data" / "runs" / date
    if not run_dir.exists():
        raise FileNotFoundError(f"Run directory not found: {run_dir}")

    cands = _load_step_candidates(run_dir)
    scored, rejected = [], []

    for c in cands:
        fluff, fluff_pat = _is_fluff(c.text)
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
        if fluff:
            rejected.append({**row, "rejected_reason": f"hard_fluff_filter:{fluff_pat}"})
            continue

        high_signal = (s >= 16 and any(r.startswith("claim_hits=") for r in reasons))
        if high_signal and c.text.strip():
            scored.append(row)
        else:
            rejected.append({**row, "rejected_reason": "low_signal_or_empty_text"})

    scored.sort(key=lambda x: x["score"], reverse=True)
    selected = scored[:10]

    if not selected:
        fallback_pool = [r for r in rejected if r.get("text") and not str(r.get("rejected_reason", "")).startswith("hard_fluff_filter")]
        fallback_pool.sort(key=lambda x: x.get("score", 0), reverse=True)
        selected = fallback_pool[:3]
    if not selected:
        selected = [{
            "source_step": "step-08-consolidation",
            "source_file": "synthetic-fallback",
            "url": "https://x.com/search?q=" + re.sub(r"\s+", "%20", topic.strip()),
            "text": f"Fallback signal: no high-confidence tweet extraction available for {date}; preserving non-empty consolidation artifact.",
            "author": "",
            "score": 1,
            "reasons": ["synthetic_fallback_nonempty_selection"],
        }]

    papers = _load_papers(run_dir)
    cons_dir = run_dir / "consolidation"
    cons_dir.mkdir(parents=True, exist_ok=True)

    selection = {"date": date, "topic": topic, "selected_count": len(selected), "selected": selected, "papers": papers}
    (cons_dir / "selection.json").write_text(json.dumps(selection, indent=2))
    (cons_dir / "rejections.json").write_text(json.dumps(rejected, indent=2))

    trace = {
        "date": date,
        "topic": topic,
        "items": [{"rank": i + 1, "url": x["url"], "source_step": x["source_step"], "source_file": x["source_file"], "score": x["score"]} for i, x in enumerate(selected)],
    }
    trace_path = (repo / "public" / "data" / f"brief-{date}.trace.json")
    if not trace_path.parent.exists():
        trace_path = (repo / "public" / f"brief-{date}.trace.json")
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps(trace, indent=2))

    lines = [f"Code RL briefing ({date})", "", f"Topic: {topic}", "", "Top tweet signals (SuperGrok artifacts only)"]
    for x in selected:
        text = x["text"].replace("\n", " ").strip()
        if len(text) > 280:
            text = text[:277] + "..."
        lines.append(f"- {text} ({x['url']})")

    if papers:
        lines += ["", "Papers"]
        for p in papers:
            lines.append(f"- {p.get('title','')} — {p.get('insight','')} ({p.get('alphaXivUrl') or p.get('arxivUrl') or ''})")

    out_md = repo / "public" / "data" / f"brief-{date}.md"
    if not out_md.parent.exists():
        out_md = repo / "public" / f"brief-{date}.md"
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text("\n".join(lines) + "\n")

    return {"ok": True, "date": date, "selected": len(selected), "rejected": len(rejected), "out": str(out_md), "selection": str(cons_dir / "selection.json"), "trace": str(trace_path)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--date", required=True)
    ap.add_argument("--topic", required=True)
    args = ap.parse_args()
    print(json.dumps(consolidate(Path(args.repo).resolve(), args.date, args.topic), indent=2))


if __name__ == "__main__":
    main()
