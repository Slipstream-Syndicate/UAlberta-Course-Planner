"""
Phase 1 exit criterion: eyeball parsed trees against the raw catalogue text.

CLAUDE.md is explicit that "it ran without erroring" is not the bar -- the
parsed output has to be read against what the calendar actually says, for
courses the builder knows firsthand. This renders both side by side so that
check takes a minute instead of an afternoon of scrolling raw JSON.

    python parser/spotcheck.py              # the 15-course core sequence
    python parser/spotcheck.py 415 301      # specific courses
    python parser/spotcheck.py --all        # every course with a prereq tree
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data" / "courses.json"

# The core CMPUT sequence -- the courses whose prerequisites a CS student has
# personally navigated and can therefore falsify from memory.
DEFAULT_CHECKS = [
    "CMPUT 174", "CMPUT 175", "CMPUT 201", "CMPUT 204", "CMPUT 229",
    "CMPUT 272", "CMPUT 274", "CMPUT 291", "CMPUT 301", "CMPUT 304",
    "CMPUT 313", "CMPUT 379", "CMPUT 391", "CMPUT 411", "CMPUT 415",
]

# MATH's own 15, chosen to cover every shape the subject added rather than just
# its most common courses: spelled-out high-school subjects (100, 114), the
# "prerequisite or corequisite" field (102, 209), "either" (217), a nested
# "both X and Y" (326, 336), "at least one of" (483), LEVEL_MIN by subject code
# (241, 322), two-token MA PH references (337), and the two shapes the parser
# deliberately refuses (421, 422).
MATH_CHECKS = [
    "MATH 100", "MATH 102", "MATH 114", "MATH 115", "MATH 209",
    "MATH 217", "MATH 225", "MATH 241", "MATH 322", "MATH 326",
    "MATH 336", "MATH 337", "MATH 421", "MATH 422", "MATH 483",
]

STATUS_MARK = {"parsed": "[ok]", "partial": "[~]", "unparsed": "[!]"}


def render(node, indent=1) -> list:
    pad = "    " * indent
    if node is None:
        return [pad + "(no prerequisites)"]
    t = node["type"]
    if t == "COURSE":
        tag = "  <- external, not tracked here" if node["external"] else ""
        return [pad + node["code"] + tag]
    if t == "LEVEL_MIN":
        return [pad + "any {}-level {} course".format(node["min_level"], node["subject"])]
    lines = [pad + t]
    for child in node["children"]:
        lines.extend(render(child, indent + 1))
    return lines


def show(course):
    print("=" * 72)
    print("{} {}  -- {}".format(
        STATUS_MARK.get(course["parse_status"], "[?]"),
        course["code"], course["title"]))
    print("  raw:  {}".format(course["prerequisites_text"] or "(no prerequisite text)"))
    print("  tree:")
    if course["prerequisite_tree"] is None and course["parse_status"] == "unparsed":
        # "(no prerequisites)" would be a lie here: there ARE requirements, we
        # just could not read them. Say which it is.
        print("      (could not be parsed -- see the raw text above)")
    else:
        for line in render(course["prerequisite_tree"]):
            print("  " + line)
    if course["corequisite_tree"]:
        print("  corequisite (take alongside, NOT a prerequisite):")
        for line in render(course["corequisite_tree"]):
            print("  " + line)
    if course["credit_exclusions"]:
        print("  credit exclusions: {}".format(", ".join(course["credit_exclusions"])))
    if course["notes"]:
        for n in course["notes"]:
            print("  note: {}".format(n))
    print()


def main():
    if not DATA.exists():
        sys.exit("Missing {} -- run parser/build_courses.py first.".format(DATA))
    courses = json.loads(DATA.read_text(encoding="utf-8"))["courses"]
    index = {c["code"]: c for c in courses}

    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    if "--math" in sys.argv:
        targets = MATH_CHECKS
    elif "--all" in sys.argv:
        targets = [c["code"] for c in courses if c["prerequisite_tree"]]
    elif args:
        targets = [a if not a.isdigit() else "CMPUT " + a for a in args]
    else:
        targets = DEFAULT_CHECKS

    for code in targets:
        code = " ".join(code.upper().split())
        if code not in index:
            print("!! {} not in dataset\n".format(code))
            continue
        show(index[code])


if __name__ == "__main__":
    main()
