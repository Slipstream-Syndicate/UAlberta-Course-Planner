"""
CMPUT Prerequisite Explorer -- ETL step (Phase 1)

data/courses_raw.json  --(parser.py)-->  data/courses.json

Both files are generated. Never hand-edit either (CLAUDE.md "Dev conventions");
re-run this over the WHOLE set after any re-scrape rather than patching
entries, so a stale `parsed` status can't mask changed catalogue wording.

Also prints the parse_status breakdown that CLAUDE.md makes a Phase 1 exit
criterion -- the point is to know the real accuracy, not assume it.

    python parser/build_courses.py            # build + report
    python parser/build_courses.py --report    # report only, no write
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import (  # noqa: E402
    parse_prerequisite_text,
    parse_corequisite_text,
    extract_credit_exclusions,
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_PATH = DATA_DIR / "courses_raw.json"
OUT_PATH = DATA_DIR / "courses.json"

SCHEMA_VERSION = 1


def course_level(code: str) -> int:
    m = re.search(r"(\d{3})", code)
    return int(m.group(1)) if m else 0


def subject_of(code: str) -> str:
    return re.sub(r"\s+\d.*$", "", code).strip().upper()


def collect_referenced_codes(node, out: set):
    if not node:
        return
    if node["type"] == "COURSE":
        out.add(node["code"])
    for child in node.get("children", []):
        collect_referenced_codes(child, out)


def mark_external_against_dataset(node, known_codes: set) -> None:
    """CLAUDE.md: the frontend uses `external` directly to decide between
    "tracked" and "verify yourself" styling, with no separate lookup. So the
    flag has to mean "not in this dataset", not "not CMPUT" -- those differ.
    CMPUT 418 is referenced by CMPUT 411 and 428 but has no catalogue page, so
    a subject-only rule would mark it tracked and then resolve to nothing."""
    if not node:
        return
    if node["type"] == "COURSE":
        node["external"] = node["code"] not in known_codes
    for child in node.get("children", []):
        mark_external_against_dataset(child, known_codes)


def build(raw: list) -> list:
    courses = []
    for r in raw:
        code = r["code"]
        prereq = parse_prerequisite_text(r.get("prerequisites_text"))
        coreq = parse_corequisite_text(r.get("corequisites_text"))

        # Credit exclusions come from two places: the dedicated exclusion
        # sentences the scraper split out, and any course the parser found
        # sitting inside a negation window in the prerequisite text.
        exclusions = extract_credit_exclusions(r.get("credit_exclusion_text"), self_code=code)
        for c in prereq["credit_exclusion_candidates"]:
            if c != code and c not in exclusions:
                exclusions.append(c)

        notes = list(prereq["notes"])
        if r.get("min_grade_note"):
            notes.append(r["min_grade_note"] + " (informational -- not enforced in the graph)")
        if r.get("consent_note"):
            notes.append(r["consent_note"] + " (informational -- not enforced in the graph)")

        courses.append({
            "code": code,
            "number": r["number"],
            "subject": subject_of(code),
            "level": course_level(code),
            "title": r.get("title"),
            "credits": r.get("units"),
            "credits_text": r.get("credits_text"),
            "faculty": r.get("faculty"),
            "effective_term": r.get("effective_term"),
            "description": r.get("description"),
            # Raw text is kept even once parsed -- it is the fallback the UI
            # shows whenever parse_status is not "parsed" (CLAUDE.md data model).
            "prerequisites_text": r.get("prerequisites_text"),
            "prerequisites_field_present": r.get("prerequisites_field_present", False),
            "prerequisite_tree": prereq["tree"],
            "corequisites_text": r.get("corequisites_text"),
            "corequisite_tree": coreq["tree"],
            "credit_exclusion_text": r.get("credit_exclusion_text"),
            "credit_exclusions": exclusions,
            "notes": notes,
            # Requirement fragments the tree does not represent. Non-empty
            # means "the diagram below is incomplete" -- a stronger claim than
            # a `partial` status alone, which also covers harmless drops like
            # "or consent of the Department". The UI uses it to decide how
            # loudly to point the reader at the official catalogue entry.
            "unrepresented_requirements": prereq.get("unrepresented", []),
            "parse_status": prereq["parse_status"],
            "coreq_parse_status": coreq["parse_status"],
            "source_url": r.get("source_url"),
        })

    known = {c["code"] for c in courses}
    for c in courses:
        mark_external_against_dataset(c["prerequisite_tree"], known)
        mark_external_against_dataset(c["corequisite_tree"], known)
    return courses


def report(courses: list) -> None:
    total = len(courses)
    undergrad = [c for c in courses if c["level"] < 500]
    grad = [c for c in courses if c["level"] >= 500]

    print("\n" + "=" * 68)
    print("PARSE STATUS BREAKDOWN  (CLAUDE.md Phase 1 exit criterion)")
    print("=" * 68)

    for label, group in (("ALL COURSES", courses), ("UNDERGRAD (<500)", undergrad),
                         ("GRADUATE (>=500)", grad)):
        counts = Counter(c["parse_status"] for c in group)
        n = len(group) or 1
        print("\n{}  n={}".format(label, len(group)))
        for status in ("parsed", "partial", "unparsed"):
            k = counts.get(status, 0)
            print("  {:<9} {:>4}   {:>5.1f}%".format(status, k, 100.0 * k / n))

    # Per-subject, because accuracy does NOT transfer between subjects -- each
    # department phrases prerequisites differently, and an aggregate number can
    # hide a newly added subject parsing badly behind a well-tuned one. Sorted
    # worst-first: with 31 subjects the ones needing attention have to surface
    # without anyone scrolling.
    subjects = sorted({c["subject"] for c in courses})
    if len(subjects) > 1:
        print("\n\nPER-SUBJECT (undergrad only, worst `parsed` rate first)")
        print("  {:<8} {:>5} {:>8} {:>8} {:>9}   {}".format(
            "SUBJ", "n", "parsed", "partial", "unparsed", "with a prereq sentence"))
        rows = []
        for subj in subjects:
            group = [c for c in undergrad if c["subject"] == subj]
            if not group:
                continue
            counts = Counter(c["parse_status"] for c in group)
            n = len(group)
            with_text = sum(1 for c in group if c["prerequisites_text"])
            rows.append((100.0 * counts.get("parsed", 0) / n, subj, n, counts, with_text))
        for pct, subj, n, counts, with_text in sorted(rows):
            print("  {:<8} {:>5} {:>7.1f}% {:>7.1f}% {:>8.1f}%   {}".format(
                subj, n, pct,
                100.0 * counts.get("partial", 0) / n,
                100.0 * counts.get("unparsed", 0) / n,
                with_text))

    # "unparsed" is dominated by topics courses whose prerequisites genuinely
    # vary by section -- separate those from real parser failures.
    varies = [c for c in undergrad
              if c["parse_status"] == "unparsed"
              and any("vary by section" in n for n in c["notes"])]
    real_gaps = [c for c in undergrad
                 if c["parse_status"] == "unparsed" and c not in varies
                 and c["prerequisites_text"]]

    print("\nOf the undergrad `unparsed`:")
    print("  {} are topics courses whose prereqs vary by section (not a parser failure)".format(len(varies)))
    print("  {} are genuine parser gaps".format(len(real_gaps)))
    for c in real_gaps:
        print("     {}  {!r}".format(c["code"], c["prerequisites_text"]))

    partials = [c for c in undergrad if c["parse_status"] == "partial"]
    print("\nUndergrad `partial` ({}) -- tree built, something informational dropped:".format(len(partials)))
    for c in partials:
        print("     {}  {}".format(c["code"], "; ".join(c["notes"])[:96]))

    # Cross-subject leaves: referenced but never scraped.
    known = {c["code"] for c in courses}
    referenced = set()
    for c in courses:
        collect_referenced_codes(c["prerequisite_tree"], referenced)
        collect_referenced_codes(c["corequisite_tree"], referenced)
    external = sorted(referenced - known)
    print("\nExternal (non-CMPUT / unscraped) course references: {}".format(len(external)))
    print("  " + ", ".join(external))

    dangling = sorted(r for r in referenced if r.startswith("CMPUT ") and r not in known)
    if dangling:
        print("\n  WARNING: CMPUT codes referenced but not in the dataset: {}".format(dangling))

    print("\nCoverage: {}/{} courses have a prerequisite tree".format(
        sum(1 for c in courses if c["prerequisite_tree"]), total))
    print("Credit exclusions recorded on {} courses".format(
        sum(1 for c in courses if c["credit_exclusions"])))
    print("Corequisites recorded on {} courses".format(
        sum(1 for c in courses if c["corequisite_tree"])))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="report only; do not write courses.json")
    args = ap.parse_args()

    if not RAW_PATH.exists():
        sys.exit("Missing {} -- run scraper/scraper.py first.".format(RAW_PATH))

    raw = json.loads(RAW_PATH.read_text(encoding="utf-8"))
    courses = build(raw)

    if not args.report:
        payload = {
            "schema_version": SCHEMA_VERSION,
            "source": "https://apps.ualberta.ca/catalogue/course/cmput",
            "subject": "CMPUT",
            "course_count": len(courses),
            "courses": courses,
        }
        OUT_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print("Wrote {} courses -> {}".format(len(courses), OUT_PATH))

    report(courses)


if __name__ == "__main__":
    main()
