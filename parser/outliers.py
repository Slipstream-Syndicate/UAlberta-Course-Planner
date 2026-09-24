"""
Outlier report -- the parser telling you what it did not understand.

THE PROBLEM THIS SOLVES
-----------------------
CMPUT and MATH were validated partly by reading them. At Faculty-of-Science
scale that stops being possible, and the existing checks only cover *known*
failure modes: `verify_all.py` proves the data is self-consistent,
`audit_coverage.py` proves each tree matches its text. Neither can tell you
about a construction nobody has thought of yet -- and MATH proved those exist,
with two real bugs surviving a fully green golden test set.

So this asks the inverse question: across every course, what did the parser
meet that it has no rule for? It cannot fix anything, and deliberately does
not fail a build. It ranks unknowns by how many courses they affect, so the
next hour of parser work goes to the shape that breaks forty courses rather
than the one that breaks one.

Findings are grouped, never listed per-course, because the point is to see the
*shape* of what is missing.

    python parser/outliers.py
    python parser/outliers.py --limit 25    # more examples per finding
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import (  # noqa: E402
    SUBJECT_CODES,
    UNKNOWN_CODE_RE,
    COURSE_CODE_RE,
    normalize_spelled_subjects,
)

DATA = Path(__file__).resolve().parent.parent / "data"

# Vocabulary the grammar already understands. A frequent word NOT in here is
# the interesting signal: it is how a new connective or qualifier announces
# itself ("either" and "both" would have shown up here before MATH was added).
KNOWN_GRAMMAR_WORDS = {
    # structure
    "and", "or", "one", "of", "any", "all", "both", "either", "at", "least",
    "a", "an", "the", "in", "for", "to", "with", "from", "on", "by", "as",
    # requirement nouns
    "prerequisite", "prerequisites", "corequisite", "corequisites",
    "course", "courses", "class", "classes", "level", "credit", "units",
    # qualifiers the parser already treats as informational
    "consent", "permission", "department", "instructor", "instructors",
    "equivalent", "equivalents", "knowledge", "standing", "year", "years",
    "minimum", "grade", "note", "notes", "see", "above", "below",
    "recommended", "required", "restricted", "students", "student",
    "program", "honors", "honours", "none", "no", "not", "is", "are", "be",
    "may", "must", "can", "will", "taken", "obtained", "same", "other",
    "additional", "determined", "defined", "differ", "section", "sections",
    "outline", "term", "first", "second", "third", "fourth",
}

WORD_RE = re.compile(r"[A-Za-z][A-Za-z'-]+")
LONG_TEXT_CHARS = 220


def load(name):
    p = DATA / name
    if not p.exists():
        sys.exit("Missing {} -- run the scraper and parser first.".format(p))
    return json.loads(p.read_text(encoding="utf-8"))


def requirement_text(course):
    """Everything the parser was asked to interpret, for one course."""
    return " ".join(
        t for t in (
            course.get("prerequisites_text"),
            course.get("corequisites_text"),
        ) if t
    )


def section(title, findings, limit, total_courses):
    print("\n" + "-" * 74)
    print(title)
    print("-" * 74)
    if not findings:
        print("  (none)")
        return
    for key, courses in findings[:limit]:
        pct = 100.0 * len(courses) / total_courses
        print("  {:>4} course(s) {:>5.1f}%  {}".format(len(courses), pct, key))
        print("        e.g. {}".format(", ".join(sorted(courses)[:5])))
    if len(findings) > limit:
        print("  ... and {} more groups".format(len(findings) - limit))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=12, help="groups shown per section")
    args = ap.parse_args()

    payload = load("courses.json")
    courses = payload["courses"]
    n = len(courses)

    unknown_subjects = defaultdict(set)
    unrepresented = defaultdict(set)
    novel_words = defaultdict(set)
    long_text = []
    label_leftovers = defaultdict(set)

    for c in courses:
        code = c["code"]
        text = requirement_text(c)
        if not text:
            continue
        normalized = normalize_spelled_subjects(text)

        # 1. Code-shaped tokens naming a subject the vocabulary rejects.
        #    This is how a discontinued subject (E E, MIS) or a brand-new one
        #    surfaces, instead of quietly vanishing from the graph.
        known_spans = {m.span() for m in COURSE_CODE_RE.finditer(normalized)}
        for m in UNKNOWN_CODE_RE.finditer(normalized):
            if any(s <= m.start() < e for s, e in known_spans):
                continue
            subj = m.group(1)
            if subj in SUBJECT_CODES:
                continue
            # A capitalised word followed by a number is only interesting if it
            # reads like a code, not like "Note 1" or prose.
            if subj.lower() in KNOWN_GRAMMAR_WORDS:
                continue
            unknown_subjects[subj].add(code)

        # 2. Fragments the parser explicitly could not represent.
        for frag in c.get("unrepresented_requirements", []):
            key = re.sub(r"\b[A-Z]{2,8}(?: [A-Z]{1,4})? ?\d{2,3}\w*\b", "<COURSE>", frag)
            key = re.sub(r"\s+", " ", key).strip()[:90]
            unrepresented[key].add(code)

        # 3. Words with no rule attached. New grammar announces itself here.
        stripped = COURSE_CODE_RE.sub(" ", normalized)
        for w in WORD_RE.findall(stripped):
            lw = w.lower()
            if lw in KNOWN_GRAMMAR_WORDS or len(lw) < 3:
                continue
            novel_words[lw].add(code)

        # 4. Requirement text long enough to suggest a bad sentence split --
        #    MATH 467 swallowed an entire description this way.
        if len(text) > LONG_TEXT_CHARS:
            long_text.append((len(text), code, text[:110]))

        # 5. A label word still sitting inside the text after parsing usually
        #    means a second field was merged into the first.
        body = re.sub(r"^\s*(?:pre-?requisites?|co-?requisites?)[^:]*:\s*", "",
                      text, flags=re.I)
        if re.search(r"\b(?:pre-?requisite|co-?requisite)s?\b", body, re.I):
            label_leftovers[re.sub(r"\s+", " ", body)[:80]].add(code)

    rank = lambda d: sorted(d.items(), key=lambda kv: (-len(kv[1]), kv[0]))

    print("=" * 74)
    print("OUTLIER REPORT -- {} courses, {} subjects".format(
        n, len({c["subject"] for c in courses})))
    print("=" * 74)
    print("Nothing here is automatically wrong. These are the places the parser")
    print("had no rule for, ranked by how many courses each one affects.")

    section("1. UNKNOWN SUBJECT CODES  (course-shaped, subject not in the registry)",
            rank(unknown_subjects), args.limit, n)
    section("2. UNREPRESENTED REQUIREMENT SHAPES  (parser refused or could not read)",
            rank(unrepresented), args.limit, n)
    section("3. NOVEL VOCABULARY  (words in requirement text with no rule attached)",
            rank(novel_words), args.limit, n)
    section("4. LEFTOVER FIELD LABELS  (suggests two fields merged into one)",
            rank(label_leftovers), args.limit, n)

    print("\n" + "-" * 74)
    print("5. UNUSUALLY LONG REQUIREMENT TEXT  (suggests a bad sentence split)")
    print("-" * 74)
    if not long_text:
        print("  (none)")
    for length, code, snippet in sorted(long_text, reverse=True)[:args.limit]:
        print("  {:>4} chars  {}".format(length, code))
        print("        {}...".format(snippet))

    status = Counter(c["parse_status"] for c in courses)
    print("\n" + "=" * 74)
    print("parsed {}  partial {}  unparsed {}   of {} courses".format(
        status["parsed"], status["partial"], status["unparsed"], n))
    print("Review sections 1 and 2 first: those are requirements missing from the graph.")


if __name__ == "__main__":
    main()
