"""
The subject registry -- the parser's closed vocabulary.

WHY THIS EXISTS
---------------
Until now the parser *guessed* what a subject code looks like: "1-6 letters,
optionally a second short token", minus a hand-maintained list of English
stopwords. That is an open vocabulary, and every subject added found a new way
to break it:

    "one of MATH 209"        -> matched a subject "OF MATH"
    "either MATH 118"        -> matched a subject "EITHER MATH"

Each fix meant appending another word to the stopword list, which is a losing
game: the list has to grow to cover all of English, and it collides with real
subject codes the moment one is also a common word. UAlberta has `DATA`, `AI`,
`MM`, `BOT` and `ENT`.

The catalogue publishes the actual list at /catalogue/course -- all 305
subjects across the university, each as "CODE - Full Name". So the parser does
not have to guess at all. A token is a subject if and only if it is in that
list. That single change removes the stopword hack, removes a whole class of
outlier, and gets *stronger* as the university adds subjects rather than
weaker.

It also supplies, for free, the spelled-out names ("Mathematics" -> MATH,
"Computing Science" -> CMPUT) that were previously hardcoded one subject at a
time as each new discipline was added.

    python parser/subjects.py --refresh    # re-fetch data/subjects.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
REGISTRY_PATH = DATA_DIR / "subjects.json"
REGISTRY_URL = "https://apps.ualberta.ca/catalogue/course"
USER_AGENT = (
    "UAlberta-Prereq-Explorer/1.0 (UAlberta student project, course-planning tool; "
    "contact: github.com/Slipstream-Syndicate/UAlberta-Course-Planner) python-requests"
)

# Faculty slug for Science, used to mark which subjects are in scope for the
# default scrape. Everything else stays a valid *reference* target.
SCIENCE_FACULTY_URL = "https://apps.ualberta.ca/catalogue/faculty/sc"

# Alberta high-school courses appear as prerequisites but are not university
# subjects, so they can never come from the registry. This is the ONLY
# hardcoded vocabulary left, and it is small and closed by nature -- a
# province's high-school course list, not a growing set of departments.
#
# Most map onto a real university subject code with a two-digit number, which
# is unambiguous: there is no university MATH 30. "Pure Mathematics" is the one
# that needs its own pseudo-code, because it is a distinct legacy course from
# "Mathematics 30-1" and conflating them would merge two different
# requirements into one node.
HIGH_SCHOOL_NAME_TO_CODE = {
    "pure mathematics": "PURE MATH",
    "applied mathematics": "APPLIED MATH",
    "mathematics": "MATH",
    "math": "MATH",
    "chemistry": "CHEM",
    "physics": "PHYS",
    "biology": "BIOL",
    "science": "SCI",
    "english language arts": "ENGL",
    "social studies": "SOC ST",
}
PSEUDO_SUBJECT_CODES = {"PURE MATH", "APPLIED MATH", "SOC ST"}

# Discontinued subjects: they have no catalogue page any more, so they cannot
# come from the registry, but live prerequisite text still references them.
# CMPUT 415 requires "E E 380"; CMPUT 301's credit exclusions name "MIS 419".
#
# This is hand-maintained, which is the thing the registry exists to avoid --
# but it is a fundamentally different list from the stopword hack it replaces.
# A stopword list has to enumerate *English*, and grows without bound. This
# enumerates *discontinued UAlberta subject codes that still appear in text*,
# which is small, closed, and evidence-driven: `parser/outliers.py` reports
# every code-shaped token the vocabulary rejected, so a missing one shows up as
# a finding instead of silently vanishing from the graph.
LEGACY_SUBJECT_CODES = {
    "E E",    # Electrical Engineering, now folded into ECE
    "MIS",    # Management Information Systems, now BTM
    "HGP",    # Human Geography and Planning -- still required by 13 PLAN courses
    "HGEO",   # Human Geography
}

# Department names used where a subject code would be expected:
#     "a 200-level Biological Sciences course"   (BIOL, BOT, ZOOL, GENET, ...)
# The registry maps CODE -> name ("BIOL - Biology"), which does not cover a
# department that spans several subject codes. These are the aliases the
# outlier report surfaced, mapped to the department's primary code.
#
# Deliberately imprecise, and flagged as such at parse time: "Biological
# Sciences" really spans BIOL/BOT/ZOOL/GENET/MICRB/ENT, so resolving it to
# BIOL alone under-counts what would satisfy it. Being explicit about the
# approximation beats either dropping the requirement or silently pretending
# a six-subject department is one code.
DEPARTMENT_ALIASES = {
    "biological sciences": "BIOL",
    "computing sciences": "CMPUT",
    "mathematical sciences": "MATH",
    "earth and atmospheric sciences": "EAS",
    "psychology": "PSYCH",
}
BROAD_DEPARTMENT_CODES = {"BIOL"}  # spans more subjects than the code implies

ROW_RE = re.compile(r"^\s*([A-Z][A-Z0-9]*(?: [A-Z][A-Z0-9]*)*)\s+-\s+(.+?)\s*$")
LINK_RE = re.compile(r"^/catalogue/course/([a-z0-9_-]+)$")


def _fetch(url: str) -> str:
    import requests

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    time.sleep(1.0)  # CLAUDE.md "Scraper etiquette"
    return resp.text


def _parse_registry(html: str) -> list:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    rows, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = LINK_RE.match(a["href"].strip())
        if not m:
            continue
        slug = m.group(1)
        if slug in seen:
            continue
        label = a.get_text(" ", strip=True)
        rm = ROW_RE.match(label)
        if not rm:
            continue
        seen.add(slug)
        rows.append({"slug": slug, "code": rm.group(1), "name": rm.group(2)})
    return sorted(rows, key=lambda r: r["code"])


def refresh() -> dict:
    """Re-fetch the registry and write data/subjects.json. Two requests total."""
    print("Fetching subject registry: " + REGISTRY_URL)
    subjects = _parse_registry(_fetch(REGISTRY_URL))

    print("Fetching Faculty of Science subject list: " + SCIENCE_FACULTY_URL)
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(_fetch(SCIENCE_FACULTY_URL), "html.parser")
    science = set()
    for a in soup.find_all("a", href=True):
        m = LINK_RE.match(a["href"].strip())
        if m:
            science.add(m.group(1))

    for s in subjects:
        s["science"] = s["slug"] in science

    payload = {
        "source": REGISTRY_URL,
        "subject_count": len(subjects),
        "science_count": sum(1 for s in subjects if s["science"]),
        "subjects": subjects,
    }
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print("Wrote {} subjects ({} in Science) -> {}".format(
        len(subjects), payload["science_count"], REGISTRY_PATH))
    return payload


def load() -> dict:
    if not REGISTRY_PATH.exists():
        sys.exit(
            "Missing {}\nRun: python parser/subjects.py --refresh".format(REGISTRY_PATH)
        )
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Derived lookups -- what the parser and scraper actually consume
# ---------------------------------------------------------------------------

def subject_codes(registry=None) -> set:
    """Every valid subject code, university-wide, plus the high-school pseudo
    subjects. This is the closed vocabulary."""
    reg = registry or load()
    codes = {s["code"] for s in reg["subjects"]}
    codes |= set(HIGH_SCHOOL_NAME_TO_CODE.values())
    codes |= PSEUDO_SUBJECT_CODES
    codes |= LEGACY_SUBJECT_CODES
    return codes


def name_to_code(registry=None) -> dict:
    """Spelled-out subject name -> code, taken from the catalogue's own
    labelling ("CMPUT - Computing Science") rather than hand-maintained.

    Names containing a comma ("Engineering, Computer") are skipped: they never
    appear that way inside a prerequisite sentence, and admitting them would
    let a comma-separated fragment match a subject name by accident.
    """
    reg = registry or load()
    out = {}
    for s in reg["subjects"]:
        name = s["name"].strip()
        if "," in name:
            continue
        out[name.lower()] = s["code"]
    # High-school names win where they disagree: "Mathematics 30-1" is a
    # high-school course, and MATH is the right code for it either way.
    out.update(DEPARTMENT_ALIASES)
    out.update(HIGH_SCHOOL_NAME_TO_CODE)
    return out


def slug_to_code(registry=None) -> dict:
    reg = registry or load()
    return {s["slug"]: s["code"] for s in reg["subjects"]}


def science_slugs(registry=None) -> list:
    reg = registry or load()
    return [s["slug"] for s in reg["subjects"] if s.get("science")]


def main():
    ap = argparse.ArgumentParser(description="UAlberta subject registry")
    ap.add_argument("--refresh", action="store_true", help="re-fetch from the catalogue")
    args = ap.parse_args()

    reg = refresh() if args.refresh else load()
    codes = subject_codes(reg)
    names = name_to_code(reg)
    print("\n{} subjects, {} in Faculty of Science".format(
        reg["subject_count"], reg["science_count"]))
    print("{} codes in the closed vocabulary (incl. high-school pseudo-subjects)".format(
        len(codes)))
    print("{} spelled-out names map to a code".format(len(names)))
    multi = sorted(c for c in codes if " " in c)
    print("multi-token codes ({}): {}".format(len(multi), ", ".join(multi)))
    print("\nScience slugs ({}): {}".format(
        len(science_slugs(reg)), " ".join(science_slugs(reg))))


if __name__ == "__main__":
    main()
