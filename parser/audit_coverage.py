"""
Coverage audit: does each parsed tree account for every course its raw
prerequisite sentence names?

Golden tests only cover shapes someone thought of. This is the safety net for
the ones nobody did -- it compares the SET of course codes in the raw text
against the SET in the parsed tree, for every course, and reports differences.

    code in text, not in tree  -> a dropped requirement. UNDER-constrained,
                                  which is the dangerous direction: the tool
                                  tells a student less is needed than really is.
    code in tree, not in text  -> a requirement was invented. Must always be 0.

This is what caught MATH 467 (a run-on description swallowed into the
prerequisite field) and MATH 556 (a one-of list eating a separate requirement)
after the golden test set was already fully green.

    python parser/audit_coverage.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import _codes_in, normalize_spelled_subjects  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "courses.json"


def tree_codes(node, out=None):
    out = set() if out is None else out
    if not node:
        return out
    if node["type"] == "COURSE":
        out.add(node["code"])
    for child in node.get("children", []):
        tree_codes(child, out)
    return out


def main():
    if not DATA.exists():
        sys.exit("Missing {} -- run parser/build_courses.py first.".format(DATA))
    courses = json.loads(DATA.read_text(encoding="utf-8"))["courses"]

    mismatches = []
    checked = 0
    for c in sorted(courses, key=lambda x: (x["subject"], x["code"])):
        raw = c["prerequisites_text"]
        if not raw:
            continue
        checked += 1
        in_text = set(_codes_in(normalize_spelled_subjects(raw)))
        in_tree = tree_codes(c["prerequisite_tree"])
        dropped = in_text - in_tree
        invented = in_tree - in_text
        if dropped or invented:
            mismatches.append((c, dropped, invented))

    print("=" * 72)
    print("COVERAGE AUDIT -- parsed tree vs. raw prerequisite text")
    print("=" * 72)
    for c, dropped, invented in mismatches:
        print("\n{}  [{}]".format(c["code"], c["parse_status"]))
        if dropped:
            print("   dropped  (in text, not in tree): {}".format(sorted(dropped)))
        if invented:
            print("   INVENTED (in tree, not in text): {}".format(sorted(invented)))
        print("   raw: {}".format(raw_snip(c)))

    invented_total = sum(1 for _, _, i in mismatches if i)
    print("\n{} courses with a prerequisite sentence".format(checked))
    print("{} mismatches, {} of them inventing a requirement".format(
        len(mismatches), invented_total))
    if invented_total:
        print("\nFAIL: a parsed tree names a course the calendar text does not.")
    return 1 if invented_total else 0


def raw_snip(course):
    t = course["prerequisites_text"] or ""
    return t[:130] + ("..." if len(t) > 130 else "")


if __name__ == "__main__":
    sys.exit(main())
