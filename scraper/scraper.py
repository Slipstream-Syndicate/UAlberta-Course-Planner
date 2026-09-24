"""
CMPUT Prerequisite Explorer -- Scraper (Phases 1 and 5)

Fetches one or more UAlberta subject catalogues and writes data/courses_raw.json with
*raw* fields only. No prerequisite-logic parsing happens here -- that is
parser/parser.py's job. See CLAUDE.md "Architecture".

Selectors below were written against the real markup at apps.ualberta.ca as
fetched on 2026-09-01, not guessed:

  index page  https://apps.ualberta.ca/catalogue/course/cmput
      -> `div.course` blocks, each with an <a href="/catalogue/course/cmput/<n>">

  course page https://apps.ualberta.ca/catalogue/course/cmput/<n>
      -> <h1>            "CMPUT 272 - Formal Systems and Logic in Computing Science"
      -> first <b>       the term this listing is in effect for, e.g. "Fall Term 2026"
      -> short <p>       "Faculty of Science"
      -> first long <p>  description, with "Prerequisites: ..." embedded in it

WHY WE FETCH EVERY COURSE PAGE INSTEAD OF JUST SCRAPING THE INDEX
-----------------------------------------------------------------
The index page carries full descriptions, so scraping it alone would be one
request instead of ~190. We deliberately don't, because the index is
*ambiguous*: 72 courses appear on it twice (a plain `div.course` block and an
indented `div.course.ms-3` one) with genuinely different description and
prerequisite text -- the curriculum-transition duplication CLAUDE.md warned
about. Two things about it differ from CLAUDE.md's description, and both
matter:

  1. There is no "Effective: <date>" marker anywhere on the page today, so the
     effective-date rule CLAUDE.md specifies has nothing to read.
  2. Checked against the individual course pages, the *first* block in
     document order is the OUTDATED one for CMPUT 101 and CMPUT 174 -- the
     authoritative current text matches the SECOND (ms-3) block.

So "take whichever appears first" silently ships a stale prereq tree, exactly
the failure CLAUDE.md called out. The individual course page shows exactly one
version and labels the term it is in effect for, which makes it the
disambiguator. We use the index purely as a list of course numbers.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "parser"))
import subjects as _subjects  # noqa: E402

BASE = "https://apps.ualberta.ca"

# Slug -> code and the default subject list both come from the scraped subject
# registry (parser/subjects.py), not from a hand-kept table. The old table had
# to be extended by hand for every multi-token subject ("ma_ph" -> "MA PH");
# there are 38 such codes university-wide, and guessing them from the slug
# would have been wrong for most.
_REGISTRY = _subjects.load()
SLUG_TO_SUBJECT = _subjects.slug_to_code(_REGISTRY)
DEFAULT_SUBJECTS = _subjects.science_slugs(_REGISTRY)


def subject_code_for(slug: str) -> str:
    return SLUG_TO_SUBJECT.get(slug.lower(), slug.upper())


def index_url_for(slug: str) -> str:
    return BASE + "/catalogue/course/" + slug.lower()
USER_AGENT = (
    "CMPUT-Prereq-Explorer/1.0 (UAlberta student project, course-planning tool; "
    "contact: github.com/Slipstream-Syndicate/UAlberta-Course-Planner) python-requests"
)
REQUEST_DELAY_SECONDS = 1.0  # CLAUDE.md "Scraper etiquette"

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HTML_CACHE_DIR = DATA_DIR / "html_cache"
RAW_OUTPUT_PATH = DATA_DIR / "courses_raw.json"

def course_link_re(slug: str):
    return re.compile(r"^/catalogue/course/" + re.escape(slug.lower()) + r"/([A-Za-z0-9]+)$")
H1_CODE_RE = re.compile(
    r"^\s*([A-Z]{1,8}(?:\s[A-Z]{1,4})?\s+\d{2,3}[A-Z]{0,2})\s*[-–]\s*(.+?)\s*$"
)
UNITS_RE = re.compile(r"\d+(?:\.\d+)?\s*units?\s*\(fi\s*\d+\)(?:\([^)]*\))*", re.I)
TERM_MARKER_RE = re.compile(r"^(?:Fall|Winter|Spring|Summer)\s+Term\s+\d{4}$", re.I)

# ---------------------------------------------------------------------------
# Sentence-level field extraction.
#
# UAlberta does NOT render "Prerequisites" as its own labeled HTML field -- it
# is a sentence embedded mid-description. So we split the description into
# sentences and classify each one, rather than regexing "label: value up to the
# next label", which would over-capture everything to the end of the text.
# ---------------------------------------------------------------------------

# Don't split on the period inside these.
_ABBREV = r"(?<!\be\.g)(?<!\bi\.e)(?<!\bBSc)(?<!\bMSc)(?<!\bDr)(?<!\bNo)"
SENTENCE_SPLIT_RE = re.compile(_ABBREV + r"(?<=[.;])\s+(?=[A-Z(])")

PREREQ_LABEL_RE = re.compile(r"\bPre-?requisites?\b\s*:?", re.I)
COREQ_LABEL_RE = re.compile(r"\bCo-?requisites?\b\s*:?", re.I)

# "Prerequisite or corequisite: MATH 100." (MATH 102, 201, 209) -- a field type
# CMPUT never uses. It means the course may be taken EITHER before or in the
# same term, so treating it as a hard prerequisite would tell students they are
# ineligible for something they can in fact register for. It is routed to the
# corequisite side, which is the permissive and honest reading.
PREREQ_OR_COREQ_LABEL_RE = re.compile(
    r"\bPre-?requisites?\s+or\s+co-?requisites?\b\s*:?", re.I
)

# THE REVERSE-DIRECTION TRAP.
#
# BIOL and PHYS descriptions contain sentences like
#     "...is a prerequisite for BIOL 108."
#     "...prerequisite for 200 or higher level ASTRO, GEOPH, MA PH, or PHYS courses."
# That names a course this one UNLOCKS, not one it requires. A classifier that
# keys on the word "prerequisite" would emit those as requirements and draw
# every edge backwards -- the same silent-corruption failure mode as the
# negation case, and just as invisible without a test. Any sentence matching
# this is never a requirement of this course.
REVERSE_DIRECTION_RE = re.compile(r"\bpre-?requisite\s+(?:for|to)\b", re.I)

# EQUIVALENCE STATEMENTS -- the same trap as reverse direction, different words.
#     EAS 200: "EAS 200 and EAS 201 are considered to be equivalent to EAS 100
#               for prerequisite purposes."
# That defines a substitution rule; it requires nothing. Read as a requirement
# it made EAS 200 its own prerequisite -- caught by verify_all.py's cycle
# check, which is exactly the kind of self-reference that check exists for.
EQUIVALENCE_RE = re.compile(
    r"\b(?:are|is)\s+considered\b|\bfor\s+pre-?requisite\s+purposes\b"
    r"|\b(?:count|counts|serve|serves)\s+as\s+(?:a\s+)?pre-?requisite\b",
    re.I,
)

# Sentences that open with "Note:" / "Notes:" are commentary, not requirements.
# MATH 217's note ("MATH 216 may be accepted as corequisite with consent of the
# Department") and MATH 498's ("Additional prerequisites may be required")
# both mention requirement words but state no requirement to parse.
NOTE_LABEL_RE = re.compile(r"^\(?\d?\)?\s*Notes?\s*:", re.I)

# Sentences that mention prerequisites without stating any. MATH 498 follows a
# real list with "Additional prerequisites may be required." -- joining that to
# the real sentence corrupts an otherwise clean parse.
VAGUE_REQUIREMENT_RE = re.compile(
    r"^(?:additional|further)\s+(?:pre-?requisites?|co-?requisites?)", re.I
)

# MATH 527: "Prerequisite: MATH 436 or equivalent; corequisite: MATH 516."
# Two different fields inside one sentence, separated by a semicolon and a
# lowercase word, so the sentence splitter never sees a boundary. Without this
# the corequisite is swallowed into the prerequisite tree as a hard gate.
EMBEDDED_COREQ_RE = re.compile(r";\s*(co-?requisites?\s*:.*)$", re.I)

# "Credit may be obtained in only one of ...", "cannot be taken for credit if
# credit has been obtained in ...", "Credit cannot be obtained for both X and Y"
# MATH adds "Credit can be obtained in at most one of MATH 111 or MATH 222."
# -- same meaning, a phrasing CMPUT never uses. Missing it would silently drop
# the exclusion rather than misread it, but dropping it still means the
# eligibility check stops warning students about a real credit conflict.
CREDIT_EXCLUSION_RE = re.compile(
    r"\bcredit\b(?=[^.;]*\b(?:only one of|at most one of|cannot be obtained"
    r"|will not be given|may not be obtained|cannot be taken for credit"
    r"|has been obtained|has already been obtained)\b)",
    re.I,
)
# Some phrasings lead with the course, not the word "credit".
CREDIT_EXCLUSION_ALT_RE = re.compile(
    r"\bcannot be taken for credit\b|\bnot open to students (?:with|who have)\b", re.I
)

MIN_GRADE_RE = re.compile(r"\bminimum grade of\s+([A-D][+-]?)\b", re.I)
CONSENT_RE = re.compile(
    r"\b(consent|permission)\s+of\s+(?:the\s+)?(instructor|department|Department|program)", re.I
)


def fetch(url: str, cache_key: str, refresh: bool = False) -> str:
    """Fetch with on-disk HTML caching so parser iteration never re-hits the
    live site (CLAUDE.md "Scraper etiquette")."""
    HTML_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = HTML_CACHE_DIR / (cache_key + ".html")
    if cache_path.exists() and not refresh:
        return cache_path.read_text(encoding="utf-8")

    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    cache_path.write_text(resp.text, encoding="utf-8")
    time.sleep(REQUEST_DELAY_SECONDS)
    return resp.text


@dataclass
class RawCourseEntry:
    code: str
    number: str
    subject: str = "CMPUT"
    title: Optional[str] = None
    credits_text: Optional[str] = None
    units: Optional[float] = None
    faculty: Optional[str] = None
    # The term this listing is in effect for, e.g. "Fall Term 2026".
    effective_term: Optional[str] = None
    # Description with the prereq/coreq/exclusion sentences pulled out:
    description: Optional[str] = None
    description_full: Optional[str] = None  # verbatim, nothing stripped
    prerequisites_text: Optional[str] = None
    # False = no prerequisite sentence at all, which is a distinct case from a
    # sentence that exists and says "None" (CLAUDE.md "Data source").
    prerequisites_field_present: bool = False
    corequisites_text: Optional[str] = None
    corequisites_field_present: bool = False
    # Raw sentence(s); pulling course codes out of them is the parser's job.
    credit_exclusion_text: Optional[str] = None
    # Commentary and reverse-direction ("is a prerequisite for X") sentences.
    # Kept verbatim so nothing is lost, but never parsed as a requirement.
    notes_text: Optional[str] = None
    # Informational only -- NOT modeled in the boolean graph (CLAUDE.md non-goals).
    min_grade_note: Optional[str] = None
    consent_note: Optional[str] = None
    source_url: str = ""
    scrape_warnings: list = field(default_factory=list)


def list_course_numbers(index_html: str, slug: str) -> list[str]:
    """Return course numbers from the index, in document order, de-duplicated.
    We only take the *links* -- see the module docstring on why the index's own
    description blocks are not trusted."""
    soup = BeautifulSoup(index_html, "html.parser")
    link_re = course_link_re(slug)
    numbers, seen = [], set()
    for a in soup.find_all("a", href=True):
        m = link_re.match(a["href"].strip())
        if not m:
            continue
        num = m.group(1).upper()
        if num in seen:
            continue
        seen.add(num)
        numbers.append(num)
    return numbers


# MATH 421's description runs a sentence straight into the next with no space:
# "...Finite State Machines.Prerequisites: MATH 326, or ...". Without repairing
# that, the prerequisite sentence never separates from the course description
# and the UI ends up showing a whole paragraph as the "calendar text".
MISSING_SPACE_RE = re.compile(r"(?<=[a-z])\.(?=[A-Z][a-z])")

# MATH 227's text is malformed at the source: "Prerequisite: MATH 127. 127;".
# Splitting before a bare number recovers the real requirement instead of
# failing the whole course over a duplicated fragment.
NUMBER_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;])\s+(?=\d)")

# MATH 467's description is one enormous comma-separated list that runs into
# the requirement with no sentence break at all:
#     "...analysis, geometry, combinatorics Prerequisites: MATH 214 and ..."
# With no period to split on, the WHOLE description was classified as the
# prerequisite sentence, and the parser then produced a confident, wrong and
# under-constrained tree from it. A label appearing mid-sentence always starts
# a new field, so split there regardless of punctuation.
# The "(?<!or )" is load-bearing: without it the bare corequisite alternative
# matches inside "Prerequisite or corequisite:" and splits that single label in
# half, leaving a stub sentence "Prerequisite or" and losing the requirement.
INLINE_LABEL_SPLIT_RE = re.compile(
    r"(?<=[^.;\s])\s+(?=Pre-?requisites?\s*(?:or\s+co-?requisites?\s*)?:"
    r"|(?<!or )Co-?requisites?\s*:)",
    re.I,
)


def split_sentences(text: str) -> list[str]:
    text = MISSING_SPACE_RE.sub(". ", text)
    parts = []
    for chunk in SENTENCE_SPLIT_RE.split(text):
        for sub in NUMBER_SENTENCE_SPLIT_RE.split(chunk):
            parts.extend(INLINE_LABEL_SPLIT_RE.split(sub))
    return [s.strip() for s in parts if s.strip()]


def classify_description(desc: str) -> dict:
    """Split a description into its prose part and the special sentences
    embedded in it.

    Order matters throughout: each test below is placed so that a sentence
    which could match two rules lands on the safer one. Anything that mentions
    a course without requiring it -- an exclusion, a reverse-direction
    "prerequisite for", a note -- must be pulled out BEFORE the prerequisite
    label is ever considered.
    """
    prereq, coreq, exclusions, notes, prose = [], [], [], [], []

    for sent in split_sentences(desc):
        if CREDIT_EXCLUSION_RE.search(sent) or CREDIT_EXCLUSION_ALT_RE.search(sent):
            # An exclusion sentence lists courses; none of them is a requirement.
            # Checked before the note rule because MATH writes real exclusions
            # *as* notes ("Note : Credit can only be obtained in at most one of
            # MATH 111 or MATH 222."), and filing those under commentary would
            # silently drop a conflict the eligibility check must warn about.
            exclusions.append(sent)
        elif NOTE_LABEL_RE.match(sent) or VAGUE_REQUIREMENT_RE.match(sent):
            # Commentary. May well contain requirement words; states none.
            notes.append(sent)
        elif REVERSE_DIRECTION_RE.search(sent) or EQUIVALENCE_RE.search(sent):
            # Names a course this one unlocks, or declares a substitution --
            # either way it states no requirement of its own.
            notes.append(sent)
        elif PREREQ_OR_COREQ_LABEL_RE.search(sent):
            # "May be taken before or alongside" -> the corequisite side.
            coreq.append(sent)
        elif PREREQ_LABEL_RE.search(sent):
            # One sentence can carry both fields (MATH 527). Split the trailing
            # corequisite clause off rather than letting it gate eligibility.
            m = EMBEDDED_COREQ_RE.search(sent)
            if m:
                coreq.append(m.group(1).strip())
                sent = sent[: m.start()].strip()
            prereq.append(sent)
        elif COREQ_LABEL_RE.search(sent):
            coreq.append(sent)
        else:
            prose.append(sent)

    def joined(xs):
        return " ".join(xs).strip() or None

    return {
        "prerequisites_text": joined(prereq),
        "corequisites_text": joined(coreq),
        "credit_exclusion_text": joined(exclusions),
        "notes_text": joined(notes),
        "description": joined(prose),
    }


def parse_course_page(html: str, number: str, url: str, subject: str) -> RawCourseEntry:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    warnings: list[str] = []
    h1 = soup.find("h1")
    heading = h1.get_text(" ", strip=True) if h1 else ""
    m = H1_CODE_RE.match(heading)
    if m:
        code, title = m.group(1), m.group(2)
    else:
        code, title = subject + " " + number, None
        warnings.append("could not parse code/title out of h1 " + repr(heading))

    b_tags = h1.find_all_next("b") if h1 else soup.find_all("b")
    effective_term = None
    credits_text = None
    for b in b_tags[:6]:
        t = b.get_text(" ", strip=True)
        if effective_term is None and TERM_MARKER_RE.match(t):
            effective_term = t
        if credits_text is None and UNITS_RE.search(t):
            credits_text = UNITS_RE.search(t).group(0)
    if credits_text is None:
        um = UNITS_RE.search(soup.get_text(" ", strip=True))
        credits_text = um.group(0) if um else None
        if credits_text is None:
            warnings.append("no units string found")

    units = None
    if credits_text:
        um = re.match(r"(\d+(?:\.\d+)?)", credits_text)
        if um:
            units = float(um.group(1))

    faculty = None
    description_full = None
    for p in (h1.find_all_next("p") if h1 else soup.find_all("p")):
        t = p.get_text(" ", strip=True)
        if not t:
            continue
        if faculty is None and t.lower().startswith("faculty of"):
            faculty = t
            continue
        if len(t) >= 60:
            description_full = t
            break
    if description_full is None:
        warnings.append("no description paragraph found (>=60 chars)")

    if description_full:
        fields = classify_description(description_full)
    else:
        fields = {
            "prerequisites_text": None,
            "corequisites_text": None,
            "credit_exclusion_text": None,
            "notes_text": None,
            "description": None,
        }

    haystack = description_full or ""
    mg = MIN_GRADE_RE.search(haystack)
    cs = CONSENT_RE.search(haystack)

    return RawCourseEntry(
        code=code,
        number=number,
        subject=subject,
        title=title,
        credits_text=credits_text,
        units=units,
        faculty=faculty,
        effective_term=effective_term,
        description=fields["description"],
        description_full=description_full,
        prerequisites_text=fields["prerequisites_text"],
        prerequisites_field_present=fields["prerequisites_text"] is not None,
        corequisites_text=fields["corequisites_text"],
        corequisites_field_present=fields["corequisites_text"] is not None,
        credit_exclusion_text=fields["credit_exclusion_text"],
        notes_text=fields["notes_text"],
        min_grade_note=mg.group(0) if mg else None,
        consent_note=cs.group(0) if cs else None,
        source_url=url,
        scrape_warnings=warnings,
    )


def run_subject(slug, limit=None, debug=False, refresh=False):
    subject = subject_code_for(slug)
    index_url = index_url_for(slug)
    print("")
    print("Fetching index: " + index_url)
    numbers = list_course_numbers(fetch(index_url, "_index_" + slug, refresh=refresh), slug)
    print("{} index lists {} distinct course numbers".format(subject, len(numbers)))
    if limit:
        numbers = numbers[:limit]

    entries: list[RawCourseEntry] = []
    for i, num in enumerate(numbers, 1):
        url = BASE + "/catalogue/course/" + slug.lower() + "/" + num.lower()
        try:
            html = fetch(url, cache_key=slug.lower() + "_" + num, refresh=refresh)
        except requests.RequestException as e:
            print("  [{}/{}] ERROR fetching {}: {}".format(i, len(numbers), url, e), file=sys.stderr)
            continue
        entry = parse_course_page(html, num, url, subject)
        entries.append(entry)
        flag = "!" if entry.scrape_warnings else " "
        print("[{}/{}]{}{:<12} {}".format(i, len(numbers), flag, entry.code, (entry.title or "?")[:48]))
        if debug:
            print("      term={} units={}".format(entry.effective_term, entry.credits_text))
            print("      prereq={!r}".format(entry.prerequisites_text))
            if entry.corequisites_text:
                print("      coreq={!r}".format(entry.corequisites_text))
            if entry.credit_exclusion_text:
                print("      exclusion={!r}".format(entry.credit_exclusion_text))
            if entry.scrape_warnings:
                print("      WARNINGS: {}".format(entry.scrape_warnings))
    return entries


def run(subjects, limit=None, debug=False, refresh=False) -> list[RawCourseEntry]:
    entries: list[RawCourseEntry] = []
    for slug in subjects:
        entries.extend(run_subject(slug, limit=limit, debug=debug, refresh=refresh))
    return entries


def main():
    ap = argparse.ArgumentParser(
        description="Scrape UAlberta course catalogue -> data/courses_raw.json"
    )
    ap.add_argument("--subjects", nargs="+", default=DEFAULT_SUBJECTS,
                    help="catalogue URL slugs, e.g. cmput math stat (default: %(default)s)")
    ap.add_argument("--limit", type=int, default=None, help="only scrape the first N courses per subject (dev)")
    ap.add_argument("--debug", action="store_true", help="print per-course extraction detail")
    ap.add_argument("--refresh", action="store_true", help="ignore the HTML cache and re-fetch")
    args = ap.parse_args()

    entries = run(args.subjects, limit=args.limit, debug=args.debug, refresh=args.refresh)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RAW_OUTPUT_PATH.write_text(
        json.dumps([asdict(e) for e in entries], indent=2), encoding="utf-8"
    )
    print("")
    print("Wrote {} courses -> {}".format(len(entries), RAW_OUTPUT_PATH))

    by_subject = {}
    for e in entries:
        by_subject[e.subject] = by_subject.get(e.subject, 0) + 1
    for subj, n in sorted(by_subject.items()):
        print("  {:<8} {}".format(subj, n))

    no_prereq = sum(1 for e in entries if not e.prerequisites_field_present)
    warned = sum(1 for e in entries if e.scrape_warnings)
    print("  {} courses have no prerequisite sentence at all".format(no_prereq))
    print("  {} have a corequisite sentence".format(
        sum(1 for e in entries if e.corequisites_field_present)))
    print("  {} have credit-exclusion text".format(
        sum(1 for e in entries if e.credit_exclusion_text)))
    print("  {} have notes/reverse-direction text held back from parsing".format(
        sum(1 for e in entries if e.notes_text)))
    print("  {} have scrape_warnings".format(warned))


if __name__ == "__main__":
    main()
