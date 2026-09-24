"""
Whole-dataset verification.

audit_coverage.py asks one question (does each tree name every course its text
names?). This asks everything else, over every course, so that "verified" means
something checkable rather than "I looked at fifteen of them".

Checks, grouped by what a failure would mean to a student:

  SCHEMA      the file is structurally what the frontend expects
  SEMANTIC    flags and statuses are self-consistent
  GRAPH       references resolve, nothing cycles, depth is sane
  HONESTY     nothing claims more certainty than it has

Exit code is non-zero if any ERROR-level check fails. WARN-level findings are
printed but do not fail: they are judgement calls worth eyeballing, not bugs.

    python parser/verify_all.py
    python parser/verify_all.py --verbose    # list every finding, not a sample
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import (  # noqa: E402
    COURSE_CODE_FULL_RE,
    _codes_in,
    normalize_spelled_subjects,
)

DATA = Path(__file__).resolve().parent.parent / "data" / "courses.json"

VALID_STATUS = {"parsed", "partial", "unparsed"}
VALID_TYPES = {"COURSE", "AND", "OR", "LEVEL_MIN"}

# Reuse the parser's own definition rather than restating it. A second copy
# here drifted immediately: it rejected "MATH 30-1" (high-school courses carry
# a -N suffix) and "E E 380" (a subject whose first token is a single letter),
# both of which are correct data.
CODE_RE = COURSE_CODE_FULL_RE

errors: list[str] = []
warnings: list[str] = []
SAMPLE = 6


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def walk_nodes(node, fn, depth=0):
    if not node:
        return
    fn(node, depth)
    for child in node.get("children", []):
        walk_nodes(child, fn, depth + 1)


def tree_course_codes(node, out=None):
    out = set() if out is None else out
    walk_nodes(node, lambda n, d: out.add(n["code"]) if n["type"] == "COURSE" else None)
    return out


def max_depth(node):
    best = [0]
    walk_nodes(node, lambda n, d: best.__setitem__(0, max(best[0], d)))
    return best[0]


# ---------------------------------------------------------------------------


def check_schema(courses, known):
    for c in courses:
        code = c.get("code", "<missing>")

        for field in ("code", "subject", "level", "parse_status", "source_url",
                      "prerequisites_text", "prerequisite_tree", "corequisite_tree",
                      "credit_exclusions", "notes", "unrepresented_requirements"):
            if field not in c:
                err("{}: missing field `{}`".format(code, field))

        if not CODE_RE.match(code):
            err("{}: course code does not match the expected shape".format(code))
        if c.get("parse_status") not in VALID_STATUS:
            err("{}: invalid parse_status {!r}".format(code, c.get("parse_status")))
        if not str(c.get("source_url", "")).startswith("https://apps.ualberta.ca/"):
            err("{}: source_url is not a catalogue URL".format(code))

        for tree_name in ("prerequisite_tree", "corequisite_tree"):
            problems = []

            def inspect(n, d, problems=problems):
                t = n.get("type")
                if t not in VALID_TYPES:
                    problems.append("invalid node type {!r}".format(t))
                elif t == "COURSE":
                    if not CODE_RE.match(n.get("code", "")):
                        problems.append("bad COURSE code {!r}".format(n.get("code")))
                    if not isinstance(n.get("external"), bool):
                        problems.append("COURSE {} missing bool `external`".format(n.get("code")))
                elif t == "LEVEL_MIN":
                    if not isinstance(n.get("min_level"), int):
                        problems.append("LEVEL_MIN has non-int min_level")
                    if not n.get("subject"):
                        problems.append("LEVEL_MIN has no subject")
                else:
                    kids = n.get("children")
                    if not isinstance(kids, list) or len(kids) < 2:
                        problems.append(
                            "{} node with {} children (should be >=2; "
                            "single-child nodes must be collapsed)".format(
                                t, len(kids) if isinstance(kids, list) else "?"))

            walk_nodes(c.get(tree_name), inspect)
            for p in problems:
                err("{} [{}]: {}".format(code, tree_name, p))


def check_semantic(courses, known):
    for c in courses:
        code = c["code"]
        status = c["parse_status"]
        tree = c["prerequisite_tree"]

        # `unparsed` must never ship a tree: the UI shows raw text instead.
        if status == "unparsed" and tree is not None:
            err("{}: parse_status=unparsed but a tree was emitted".format(code))

        # `parsed` means nothing was left unrepresented.
        if status == "parsed" and c["unrepresented_requirements"]:
            err("{}: parse_status=parsed but has unrepresented requirements".format(code))

        # A tree exists => there was text to parse it from.
        if tree is not None and not c["prerequisites_text"]:
            err("{}: has a prerequisite tree but no prerequisite text".format(code))

        # `external` must mean "not in this dataset", not "not this subject".
        def check_external(n, d, code=code, known=known):
            if n["type"] != "COURSE":
                return
            should = n["code"] not in known
            if n["external"] != should:
                err("{}: {} marked external={} but {} in the dataset".format(
                    code, n["code"], n["external"], "is" if not should else "is NOT"))

        walk_nodes(tree, check_external)
        walk_nodes(c["corequisite_tree"], check_external)

        # A course cannot be its own prerequisite, nor exclude itself.
        if code in tree_course_codes(tree):
            err("{}: names itself as its own prerequisite".format(code))
        if code in c["credit_exclusions"]:
            err("{}: lists itself as a credit exclusion".format(code))

        # Prereq and coreq are different claims; the same course being both is
        # contradictory ("must be done before" AND "take at the same time").
        overlap = tree_course_codes(tree) & tree_course_codes(c["corequisite_tree"])
        if overlap:
            warn("{}: {} appears as both prerequisite and corequisite".format(
                code, ", ".join(sorted(overlap))))


def check_graph(courses, known):
    index = {c["code"]: c for c in courses}

    # Cycles, via DFS over in-dataset COURSE edges.
    colour = defaultdict(int)  # 0 unvisited, 1 in-stack, 2 done
    cycles = []

    def visit(code, stack):
        if colour[code] == 2:
            return
        if colour[code] == 1:
            cycles.append(" -> ".join(stack[stack.index(code):] + [code]))
            return
        colour[code] = 1
        stack.append(code)
        for nxt in sorted(tree_course_codes(index[code]["prerequisite_tree"])):
            if nxt in index:
                visit(nxt, stack)
        stack.pop()
        colour[code] = 2

    sys.setrecursionlimit(10000)
    for c in courses:
        visit(c["code"], [])
    # A self-reference is always a parse bug: no course requires itself.
    # A cycle BETWEEN two courses can be faithful to the catalogue -- MA PH 351
    # lists MATH 337 as one OR alternative and MATH 337 lists MA PH 351 as one
    # of its own, so each is reachable by its other branch and neither is a
    # deadlock. The eval engine's cycle guard handles those, and verifyDataset
    # proves it on the real data, so they are reported rather than failed.
    for cyc in cycles:
        nodes = cyc.split(" -> ")
        if len(set(nodes)) == 1:
            err("course is its own prerequisite: {}".format(cyc))
        else:
            warn("prerequisite cycle (engine guards it; check both entries "
                 "are really alternatives): {}".format(cyc))

    # Deep chains are legal but worth seeing -- the eval engine caps at 12.
    for c in courses:
        d = max_depth(c["prerequisite_tree"])
        if d > 6:
            warn("{}: prerequisite tree nests {} levels deep".format(c["code"], d))

    # Every in-subject reference should resolve; if it cannot, it must at least
    # be flagged external so the UI says "verify yourself".
    subjects = {c["subject"] for c in courses}
    dangling = set()
    for c in courses:
        for ref in tree_course_codes(c["prerequisite_tree"]) | tree_course_codes(c["corequisite_tree"]):
            subj = re.sub(r"\s+\d.*$", "", ref)
            if subj in subjects and ref not in known:
                dangling.add(ref)
    for ref in sorted(dangling):
        warn("{} is referenced but has no catalogue entry in this dataset "
             "(correctly flagged external)".format(ref))


def check_honesty(courses):
    for c in courses:
        code = c["code"]
        raw = c["prerequisites_text"]
        if not raw:
            continue
        in_text = set(_codes_in(normalize_spelled_subjects(raw)))
        in_tree = tree_course_codes(c["prerequisite_tree"])

        invented = in_tree - in_text
        if invented:
            err("{}: tree names {} which the calendar text does not".format(
                code, sorted(invented)))

        dropped = in_text - in_tree
        # Dropping a course is only acceptable if the course SAYS it dropped
        # something -- i.e. it is not claiming a clean parse.
        if dropped and c["parse_status"] == "parsed":
            err("{}: claims parse_status=parsed but silently dropped {}".format(
                code, sorted(dropped)))
        elif dropped and not c["unrepresented_requirements"]:
            warn("{} [{}]: dropped {} without recording it as unrepresented".format(
                code, c["parse_status"], sorted(dropped)))


def report(courses):
    print("=" * 74)
    print("DATASET VERIFICATION -- {} courses".format(len(courses)))
    print("=" * 74)

    by_subject = Counter(c["subject"] for c in courses)
    for subj, n in sorted(by_subject.items()):
        rows = [c for c in courses if c["subject"] == subj]
        st = Counter(c["parse_status"] for c in rows)
        print("  {:<7} {:>4} courses   parsed {:>3}  partial {:>3}  unparsed {:>3}".format(
            subj, n, st["parsed"], st["partial"], st["unparsed"]))

    trees = [c for c in courses if c["prerequisite_tree"]]
    print("\n  {} courses carry a prerequisite tree".format(len(trees)))
    print("  {} carry a corequisite tree".format(
        sum(1 for c in courses if c["corequisite_tree"])))
    print("  {} carry credit exclusions".format(
        sum(1 for c in courses if c["credit_exclusions"])))
    print("  {} record an unrepresented requirement".format(
        sum(1 for c in courses if c["unrepresented_requirements"])))
    print("  deepest prerequisite tree: {} levels".format(
        max((max_depth(c["prerequisite_tree"]) for c in courses), default=0)))


def main():
    verbose = "--verbose" in sys.argv
    if not DATA.exists():
        sys.exit("Missing {} -- run parser/build_courses.py first.".format(DATA))

    payload = json.loads(DATA.read_text(encoding="utf-8"))
    courses = payload["courses"]
    known = {c["code"] for c in courses}

    if payload.get("course_count") != len(courses):
        err("course_count ({}) disagrees with the number of courses ({})".format(
            payload.get("course_count"), len(courses)))
    dupes = [k for k, v in Counter(c["code"] for c in courses).items() if v > 1]
    for d in dupes:
        err("duplicate course entry: {}".format(d))

    report(courses)
    check_schema(courses, known)
    check_semantic(courses, known)
    check_graph(courses, known)
    check_honesty(courses)

    for label, items in (("ERROR", errors), ("WARN", warnings)):
        print("\n{} ({})".format(label, len(items)))
        shown = items if verbose else items[:SAMPLE]
        for i in shown:
            print("  {}".format(i))
        if len(items) > len(shown):
            print("  ... and {} more (--verbose to list)".format(len(items) - len(shown)))

    print("\n" + ("FAILED" if errors else "PASSED") +
          ": {} errors, {} warnings".format(len(errors), len(warnings)))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
