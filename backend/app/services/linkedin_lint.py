"""Deterministic LinkedIn pre-publish checks (no AI, instant, free).

Implements the regex audit shipped with the linkedin-humanizer skill
(app/linkedin_skills/skills/humanizer/references/audit-ai-tells.md and
sub-skills/post-audit.md, MIT, Sergey Bulaev). DeepSeek applies the same rules
by judgement; this module enforces the measurable ones exactly, so a blocker is
never missed and every draft carries hard numbers (length, fold, em dashes,
per-paragraph AI-tell density).
"""
from __future__ import annotations

import re
from typing import Any

MAX_CHARS = 3000
FOLD = 210

_VERB_STEMS = ("leverag", "utiliz", "facilitat", "streamlin", "delv", "navigat",
               "unlock", "harness", "foster", "cultivat", "elevat", "empower")
DENSITY_PATTERNS = {
    "AI verb": rf"(?i)\b(?:{'|'.join(_VERB_STEMS)})(?:e|es|ed|ing|s)?\b",
    "AI vocabulary": r"(?i)\b(significant(ly)?|crucial(ly)?|notably|particularly|comprehensive|insights?|robust|landscape|nuanced|multifaceted|holistic|seamless|ecosystem)\b",
    "filler adverb": r"(?i)\b(fundamentally|essentially|ultimately|arguably|certainly|definitely|undoubtedly)\b",
    "-ing opener": r"(?m)^[\s>*\-]*[A-Z][a-z]+ing\b[^.\n]{0,60},",
    "nominalisation": r"(?i)\bthe \w+(?:tion|sion|ment|ance|ence|ization|isation) of\b",
    "2026 LinkedIn cliche": r"(?i)\b(quietly|compound(s|ing)?|(a|the) signal|the work|built different|load-bearing|doing the heavy lifting)\b",
    "'X matters.' line": r"(?im)^\w+ matters\.$",
    "2024 AI word": r"(?i)\b(delve|delving|tapestry|realm|intricate|journey|paradigm)\b",
}
SINGLE_HIT = {
    "en dash between clauses": (r"\s–\s", "Replace with a comma."),
    "double dash": (r"(?<!-)--(?!-)", "Replace with a comma or rewrite."),
    "reveal bridge": (r"(?im)^(the (result|outcome|answer|lesson|catch|kicker|truth)\?|(here'?s|here is) (what|how|why|the thing)\b|stop \w+[^.\n]{0,40}[.,] ?start \b|plot twist:)",
                      "State the payoff directly - reveal bridges cost ~5% reach."),
    "negative parallelism": (r"(?i)(not just \w+, it'?s \w+|\b(isn'?t|not) (about )?[^,.\n]{1,40}, it'?s (about )?\b)",
                             "Say what it IS; drop the 'not X, it's Y' frame."),
    "staccato stack": (r"(?m)^(\w+\. ){2,}\w+\.$", "Merge the fragments into one sentence with a clause doing work."),
    "one-word paragraph": (r"(?m)^\w+\.$", "Fold it into the neighbouring line."),
    "'No X. No Y. Just Z.'": (r"(?i)\bno \w+\. no \w+\. (just|only) \w+", "Rewrite as one plain sentence."),
    "'All the X. None of the Y.'": (r"(?i)\ball (of )?the \w+\. none of the \w+", "Rewrite as one plain sentence."),
    "pseudo-Socratic Q&A": (r"(?i)\b(why|how)\? (because|simple)\b", "Just state the reason."),
    "sincerity announcement": (r"(?im)^[\s>*\-]*(let me be (honest|real|direct|clear)|i'?ll be (honest|real|direct)|honestly\?|honest (caveat|version|answer)|the honest (version|answer|truth) is|to be (direct|honest|transparent)|real talk|full transparency|can i be (honest|vulnerable)|not gonna lie|ngl|unpopular opinion)\b",
                               "Delete the frame; state the fact flat."),
    "cliche phrase": (r"(?i)(game[- ]changer|deep dive|needle[- ]moving|move the needle|at the end of the day|when it comes to|in the age of ai|paradigm shift|the hard truth is|the uncomfortable reality is)",
                      "Replace with a concrete, specific phrase."),
    "engagement bait": (r"(?i)(comment (yes|below|\"?\w+\"?) (if|and i'?ll)|drop an? (\S+ )?(emoji|🙌|👇)|like if you agree|repost if)",
                        "Ask a specific open question tied to the post's point."),
    "announcement opener": (r"(?i)^\s*(i'?m|we'?re) (so )?(excited|thrilled|honou?red|proud|delighted) to (share|announce)",
                            "Open with the concrete moment that prompted the post."),
}
OPENER_BLOCK = r"(?i)^[\s>*\-]*[\"'“]?(in today'?s|have you ever|most people don'?t realize|here'?s a hard truth|(here'?s|here is) (what|how|why))"
CLOSER_BLOCK = r"(?i)(what do you think\??|what are your thoughts\??|what'?s your (take|thoughts?)\??|thoughts\?|agree or disagree\?|let me know in the comments|tag someone|let that sink in\.?)\s*$"
LINK = r"(?i)(https?://\S+|www\.\S+|\b[\w-]+\.(com|io|ai|co|in|net|org|app|dev)(/\S*)?\b)"
HASHTAG = r"(?<![\w#])#[A-Za-z]\w*"
AI_EMOJI = {"💡": 2.57, "🚀": 3.28, "✨": 3.11, "♻️": 2.93, "♻": 2.93, "🎯": 2.07, "📈": 1.89,
            "🔑": 1.74, "💪": 1.45, "🔥": 1.31}
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐✅]")
NUMBER = r"\b\d[\d,.]*\s?(%|k|x|m|hrs?|hours?|days?|weeks?|months?|years?|minutes?|mins?|clients?|users?|people|leads?|calls?|₹|\$)?"


def em_dash_excess(text: str) -> int:
    words = len(text.split())
    cap = max(1, min(2, round(words / 100)))
    return max(0, text.count("—") - cap)


def fragment_count(text: str) -> int:
    return sum(1 for s in re.split(r"(?<=[.!?])\s+", text) if 0 < len(s.split()) < 4)


def paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text or "") if p.strip()]


def paragraph_density(p: str) -> dict[str, int]:
    hits = {name: len(re.findall(pat, p)) for name, pat in DENSITY_PATTERNS.items()}
    return {k: v for k, v in hits.items() if v}


def emoji_score(text: str) -> dict[str, Any]:
    found = {e: text.count(e) for e in AI_EMOJI if e in text}
    if "♻️" in found:
        found.pop("♻", None)
    score = sum(AI_EMOJI[e] * n * 10 for e, n in found.items())
    if len(found) >= 3:
        score += 20
    if any(n >= 2 for n in found.values()):
        score += 15
    score = min(100, round(score))
    verdict = "n/a" if not EMOJI.search(text) else "clean" if score <= 20 else "borderline" if score <= 50 else "AI-likely"
    return {"score": score, "verdict": verdict, "flagged": sorted(found)}


def _issue(rule: str, fix: str, quote: str = "") -> dict[str, str]:
    return {"rule": rule, "quote": quote[:200], "fix": fix}


LENGTHS = {"short": (300, 600), "medium": (900, 1300), "long": (1500, 1900)}


def lint(text: str, *, goal: str = "", length: str = "") -> dict[str, Any]:
    """Blockers / warnings / numbers for one post, per the post-audit checklist."""
    t = (text or "").strip()
    blockers: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    chars = len(t)
    words = len(t.split())
    lines = [ln for ln in t.split("\n") if ln.strip()]
    first_line = lines[0].strip() if lines else ""
    paras = paragraphs(t)

    # ---- blockers (post-audit.md 1-7)
    if em_dash_excess(t):
        blockers.append(_issue("em dash density", "Keep at most ~1 em dash per 100 words; swap the excess for a comma, colon or parentheses (never a period).",
                               f"{t.count(chr(0x2014))} em dashes in {words} words"))
    link = re.search(LINK, t)
    if link:
        blockers.append(_issue("external link in body", "Move the link to the first comment (links in the body cut reach 40-60%).", link.group(0)))
    if chars > MAX_CHARS:
        blockers.append(_issue("over LinkedIn's limit", f"Cut to under {MAX_CHARS} characters.", f"{chars} characters"))
    m = re.search(OPENER_BLOCK, first_line)
    if m:
        blockers.append(_issue("dead opener", "Open with a complete, specific hook - a fact, number or moment.", first_line))
    last = lines[-1].strip() if lines else ""
    m = re.search(CLOSER_BLOCK, last)
    if m:
        blockers.append(_issue("generic close", "End with a specific question tied to the post's point, or land it cleanly.", last))
    for name in ("reveal bridge", "negative parallelism", "sincerity announcement", "engagement bait", "announcement opener"):
        pat, fix = SINGLE_HIT[name]
        m = re.search(pat, t)
        if m and not (name == "engagement bait" and goal == "leads"):
            (blockers if name in ("reveal bridge", "negative parallelism") else warnings).append(_issue(name, fix, m.group(0)))
    density = []
    for i, p in enumerate(paras, 1):
        hits = paragraph_density(p)
        n = sum(hits.values())
        density.append({"paragraph": i, "markers": n, "found": sorted(hits)})
        if n >= 3:
            blockers.append(_issue("AI-tell dense paragraph", "Rewrite this paragraph in plain words (3+ AI markers).", p[:120]))
        elif n == 2:
            warnings.append(_issue("2 AI markers in one paragraph", "Replace the weaker of: " + ", ".join(sorted(hits)), p[:120]))

    # ---- warnings (post-audit.md 8-23)
    if len(first_line) > FOLD:
        warnings.append(_issue("hook runs past the fold", f"Make line 1 a complete hook under {FOLD} characters.", first_line[:120]))
    lo, hi = LENGTHS.get(length, (900, 1900))
    if chars and not lo * 0.9 <= chars <= hi * 1.1:
        target = f"{lo:,}-{hi:,}" if length in LENGTHS else "900-1,300 (or 1,500-1,900 long-form)"
        warnings.append(_issue("length off target", f"Aim for {target} characters.", f"{chars} characters"))
    if not re.search(NUMBER, t):
        warnings.append(_issue("no specific number", "Add one odd-precision number with a named referent (from your real results)."))
    hashtags = re.findall(HASHTAG, t)
    if len(hashtags) > 2:
        warnings.append(_issue("too many hashtags", "Use 0-2 hashtags at the end.", " ".join(hashtags)))
    if len(paras) > 1 and "\n\n" not in t[: len(first_line) + 3]:
        warnings.append(_issue("no blank line after the hook", "Leave an empty line after line 1."))
    if len(paras) == 1 and chars > 400:
        warnings.append(_issue("wall of text", "One idea per line, blank lines between ideas."))
    frags = fragment_count(t)
    if frags > 2:
        warnings.append(_issue("too many fragments", "Keep at most 2 standalone fragments; merge the rest.", f"{frags} fragments"))
    for name in ("staccato stack", "one-word paragraph", "'No X. No Y. Just Z.'", "'All the X. None of the Y.'",
                 "pseudo-Socratic Q&A", "cliche phrase", "en dash between clauses", "double dash"):
        pat, fix = SINGLE_HIT[name]
        m = re.search(pat, t)
        if m:
            warnings.append(_issue(name, fix, m.group(0)))
    emoji = emoji_score(t)
    if emoji["verdict"] in ("borderline", "AI-likely"):
        warnings.append(_issue("AI-pattern emoji", "Remove " + " ".join(emoji["flagged"]) + " or swap for a concrete one."))
    if re.search(r"\?\s*$", first_line) and len(first_line) < 120:
        warnings.append(_issue("question as line 1", "Rhetorical-question hooks underperform in 2026; open with a statement."))

    return {
        "verdict": "fail" if blockers else ("warn" if warnings else "pass"),
        "chars": chars, "words": words, "hook": first_line[:FOLD], "hook_chars": len(first_line),
        "hashtags": len(hashtags), "em_dashes": t.count("—"), "fragments": frags,
        "emoji": emoji, "density": density, "blockers": blockers, "warnings": warnings,
    }


_NUM = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?![\w])")


def _norm_num(n: str) -> str:
    return n.replace(",", "").rstrip("0").rstrip(".") if "." in n else n.replace(",", "")


def unverified_numbers(text: str, source: str) -> list[str]:
    """Numbers in the post that appear nowhere in the user's data / brief.

    Invented figures are the worst failure a ghostwriter can ship. Years,
    single digits and numbers inside the user's data are allowed.
    """
    known = {_norm_num(m) for m in _NUM.findall(source or "")}
    out = []
    for m in _NUM.findall(text or ""):
        n = _norm_num(m)
        if n in known or m in out:
            continue
        try:
            val = float(n)
        except ValueError:
            continue
        if val < 10 or (1900 <= val <= 2100 and "." not in n):
            continue
        out.append(m)
    return out
