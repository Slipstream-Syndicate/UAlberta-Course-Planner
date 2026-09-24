"""
UAlberta Prerequisite Explorer -- Parser

Turns the raw prerequisite sentences captured by scraper/scraper.py into the
structured boolean tree described in CLAUDE.md's "Data model" section:

    node types: COURSE, AND, OR, LEVEL_MIN

Pure text in, pure data out -- no network, fully unit-tested (test_parser.py).

=============================================================================
GLOBAL RULES -- these hold for every subject, in every faculty
=============================================================================
The rules below are deliberately discipline-independent. Departments phrase
requirements differently, but they are all writing the same few things, and
every one of these was earned by a real bug rather than assumed up front.

R1. CLOSED VOCABULARY. A token is a subject code if and only if it is in the
    catalogue's published subject registry (parser/subjects.py). Never infer a
    subject from shape. Guessing gave us "OF MATH" and "EITHER MATH", and can
    never be made safe against real codes that are also English words -- DATA,
    AI, MM, BOT, ENT all exist.

R2. DIRECTION. "X is a prerequisite FOR Y" names a course this one UNLOCKS,
    not one it requires. Never a requirement. Getting this wrong draws every
    edge backwards, silently.

R3. POLARITY. A course named inside a negation or credit-exclusion window is
    an exclusion, never a requirement. Checked BEFORE any requirement rule,
    because exclusion sentences are full of course codes.

R4. FIELD BOUNDARIES. A label ("Prerequisite", "Corequisite", "Prerequisite or
    corequisite", "Note") starts a new field wherever it appears -- including
    mid-sentence, with no punctuation before it. Two fields merged into one is
    how a whole course description ends up parsed as a requirement.

R5. PERMISSIVE READING OF COMBINED FIELDS. "Prerequisite or corequisite" means
    it may be taken alongside, so it goes to the corequisite side. Reading it
    as a hard gate tells students they are ineligible for something they can
    actually register for.

R6. SCOPES. "one of" / "either" / "at least one of" / "any of" open an OR
    scope; "both" opens an AND scope. A scope ends at ';', at ', and ', at
    another scope opener, or at a bare 'and' before another course. Outer
    precedence rules must not reach inside a scope.

R7. PRECEDENCE BY PUNCTUATION, NOT KEYWORD. A comma-attached connector binds
    looser than a bare one:
        "CMPUT 175 or 275, and CMPUT 272"  -> (175 OR 275) AND 272
        "CMPUT 201 and 204, or 275"        -> (201 AND 204) OR 275
    Same keywords, opposite trees. A bare comma is itself a requirement
    separator when no connector closes the list.

R8. IMPLIED SUBJECT. A bare number inherits the last subject seen, left to
    right ("CMPUT 201 and 204" -> CMPUT 204). Done as a pre-pass so the
    recursive splitter never tracks lexical state.

R9. INFORMATIONAL, NOT STRUCTURAL. Consent/permission, minimum grades, program
    standing and "or equivalent" are recorded as notes, never modelled as
    graph constraints (CLAUDE.md non-goals).

R10. REFUSE RATHER THAN GUESS. Numbered alternatives, "when combined with",
    and topic-constrained level requirements are not parsed. A wrong tree is
    stated with exactly the same confidence as a right one, so these degrade
    to `unparsed`/`partial` and the UI falls back to the calendar text.

R11. REPORT WHAT WAS DROPPED. Anything not represented in the tree is recorded
    in `unrepresented`, separately from harmless informational drops, so the
    UI can say the diagram is incomplete instead of implying it is whole.

R12. SURFACE THE UNKNOWN. Whatever no rule matched is reported by
    parser/outliers.py, ranked by how many courses it affects. Rules R1-R11
    handle what we know; R12 is how we find out what we don't.

=============================================================================

GRAMMAR NOTES, derived from real catalogue text rather than from guesses
--------------------------------------------------------------------------
The catalogue's punctuation, not its keywords, carries the grouping. Compare:

    "CMPUT 175 or 275, and CMPUT 272"        -> (175 OR 275) AND 272
    "CMPUT 201 and 204, or 275"              -> (201 AND 204) OR 275

Same two keywords, opposite trees. What differs is which connector the comma
is attached to: a comma-prefixed connector binds *looser* than a bare one. So
precedence is, outermost first:

    1. ';'          separates top-level AND clauses
    2. ', and '     AND        3. ', or '   OR
    4. ' and '      AND        5. ' or '    OR

A bare comma is a list separator whose meaning is fixed by the connector that
closes the list ("A, B, or C" is OR; "A, B, and C" is AND), so commas are
flattened into whichever node the enclosing split produced -- but only when
that fragment holds no competing connector of its own.

"one of" is a no-op marker: it announces an OR-list that the punctuation rules
above already recover, so it is simply stripped.

Bare numbers inherit the last subject seen ("CMPUT 201 and 204" -> CMPUT 204).
That is done as a left-to-right pre-pass over the whole string (expand_bare_numbers)
so the recursive splitter never has to track lexical state.

CONFIDENCE
----------
Per CLAUDE.md ("Don't aim for 100% rule-based coverage"), anything not
confidently recognized degrades rather than guesses:
    parsed    every atom became a node
    partial   a tree was built, but >=1 atom was informational-only
              ("permission of the Department", "or equivalent") and dropped
    unparsed  no tree at all; the UI must fall back to the raw text
"""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import subjects as _subjects  # noqa: E402

CMPUT_SUBJECT = "CMPUT"

# ---------------------------------------------------------------------------
# Lexical patterns
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CLOSED VOCABULARY (see parser/subjects.py for the full rationale)
#
# A token is a subject if and only if it appears in the catalogue's own subject
# registry. The previous open-vocabulary pattern ("1-6 letters, minus a
# stopword list") had to be patched for every discipline added -- it matched
# "OF MATH" and "EITHER MATH" as subjects -- and could never be made safe
# against real codes that are also English words (DATA, AI, MM, BOT, ENT).
#
# Matching longest-first so a two-token code wins over its first token
# ("MA PH 351" must not match as "MA").
# ---------------------------------------------------------------------------

SUBJECT_CODES = _subjects.subject_codes()
SUBJECT_NAME_TO_CODE = _subjects.name_to_code()

_SUBJECT = "(?:" + "|".join(
    re.escape(c) for c in sorted(SUBJECT_CODES, key=len, reverse=True)
) + ")"

# Number: "272", "296A", and the high-school forms "30", "30-1", "30-2".
_NUMBER = r"\d{2,3}(?:[A-Z]{1,2}|-\d)?"

# Code-shaped tokens the vocabulary REJECTED. Not used for parsing -- used by
# parser/outliers.py to report "this looks like a course reference but names a
# subject I do not know", which is how a discontinued subject (E E, MIS) or a
# newly created one gets noticed instead of silently disappearing.
UNKNOWN_CODE_RE = re.compile(r"\b([A-Z][A-Za-z]{1,7}(?: [A-Z]{1,4})?)\s+(\d{2,3}(?:[A-Z]{1,2}|-\d)?)\b")

COURSE_CODE_RE = re.compile(r"\b(" + _SUBJECT + r")\s+(" + _NUMBER + r")\b")
COURSE_CODE_FULL_RE = re.compile(r"^(" + _SUBJECT + r")\s+(" + _NUMBER + r")$")
BARE_NUMBER_RE = re.compile(r"^" + _NUMBER + r"$")

# MATH widens every part of this shape relative to CMPUT:
#   determiner  "any 300-level" / "a 200-level" / bare "400-level MATH course"
#   subject     a CODE ("MATH") as well as a spelled name ("Computing Science")
#   noun        "course" or "class" ("any 300-level MATH class", MATH 421)
LEVEL_MIN_RE = re.compile(
    r"^(?:any|a|an|the|one|another)?\s*(\d)00-level\s+(.+?)\s+(?:course|class)$", re.I
)
# "any 200-level course" -- no subject named at all.
LEVEL_MIN_NO_SUBJECT_RE = re.compile(
    r"^(?:any|a|an|the|one|another)?\s*(\d)00-level\s+(?:course|class)$", re.I
)

# Spelled-out subject names appearing directly in course references. CMPUT
# writes "Math 30-1"; MATH writes "Mathematics 30-1" and "Pure Mathematics 30"
# for the same kind of high-school prerequisite. Both must normalize to one
# code, or the same course becomes two unrelated nodes in the graph.
#
# Longest-first so "Pure Mathematics 30" is not matched as "Mathematics 30".
SPELLED_SUBJECT_RE = re.compile(
    r"\b(" + "|".join(
        sorted((re.escape(k) for k in SUBJECT_NAME_TO_CODE), key=len, reverse=True)
    ) + r")\s+(?=\d)",
    re.I,
)


def normalize_spelled_subjects(text: str) -> str:
    """'Pure Mathematics 30 or Mathematics 30-1' -> 'PURE MATH 30 or MATH 30-1'.

    Only rewrites a name immediately followed by a number, so prose like
    "reasoning in mathematics" is left alone.
    """
    def sub(m):
        return SUBJECT_NAME_TO_CODE[m.group(1).lower()] + " "

    return SPELLED_SUBJECT_RE.sub(sub, text)

# Atoms that carry real meaning for a human but cannot become graph nodes.
# CLAUDE.md non-goals: minimum grades / instructor permission are stored as
# informational flags, never modeled as graph constraints.
INFORMATIONAL_RE = re.compile(
    r"^(?:"
    r"(?:permission|consent|approval)\s+of\s+(?:the\s+)?[\w\s,]+"
    r"|(?:a\s+)?committed\s+thesis\s+supervisor"
    r"|minimum\s+gpa\s+of\s+[\d.]+"
    r"|equivalent(?:\s+knowledge)?"
    r"|some\s+computer\s+programming"
    r"|additional\s+prerequisites.*"
    r"|no\s+programming\s+skills.*"
    r"|(?:\w+[- ])?year\s+standing"
    r"|restricted to .*"
    r"|any introductory-level.*"
    r"|.*\bminimum grade\b.*"
    r"|see note.*"
    r")\.?$",
    re.I,
)

# Whole-sentence shapes that mean "there is no fixed prerequisite list".
VARIES_RE = re.compile(
    r"determined by the instructor|defined by the instructor|may differ"
    r"|depends? on the (?:subject|topic)", re.I
)
NONE_TEXT_RE = re.compile(r"^(none|n/?a|no prerequisites?)\.?$", re.I)

# "both MATH 214 and MATH 216" (MATH 336).
BOTH_AND_RE = re.compile(r"^both\s+(.+\s+and\s+.+)$", re.I)

# Asides are never requirements. Two bracket styles, same meaning:
#   "(MATH 322 recommended)"   a recommendation
#   "[Faculty of Science]"     a faculty restriction -- EAS and PSYCH append
#                              this to ~67 courses. It restricts WHO may
#                              register, not WHAT must be completed first, so
#                              it belongs in notes, never in the tree.
PAREN_ASIDE_RE = re.compile(r"\s*\(([^)]*)\)|\s*\[([^\]]*)\]")

# Shapes this parser deliberately refuses to guess at. MATH 421/422 enumerate
# alternatives with numbered markers or condition them on other courses; a
# wrong tree here would be stated with the same confidence as a right one, so
# these degrade to `unparsed` and the UI falls back to the calendar text.
TOO_COMPLEX_RE = re.compile(
    r"\(\s*\d\s*\)\s*\w|when combined with|as needed|varies", re.I
)

# MATH writes the label three ways: "Prerequisite:", "Prerequisite :" (MATH 327)
# and "Prerequisite MATH 227" with no colon at all (MATH 326).
PREREQ_LABEL_RE = re.compile(r"^\s*Pre-?requisites?\s*(?:are|is)?\s*:?\s*", re.I)
COREQ_LABEL_RE = re.compile(r"^\s*Co-?requisites?\s*(?:are|is)?\s*:?\s*", re.I)
# "Prerequisite or corequisite: MATH 100." must be stripped as ONE label. Left
# to the two patterns above it half-strips to "or corequisite: MATH 100." and
# the requirement is lost entirely -- an empty tree that silently claims the
# course has no corequisite.
PREREQ_OR_COREQ_LABEL_RE = re.compile(
    r"^\s*Pre-?requisites?\s+or\s+co-?requisites?\s*:?\s*", re.I
)

# ---------------------------------------------------------------------------
# Negation guard (CLAUDE.md: the bug most likely to silently corrupt the graph)
# ---------------------------------------------------------------------------

NEGATION_CUES = (
    "not open to",
    "without credit",
    "excluding",
    "may not be",
    "cannot be taken",
    "cannot be obtained",
    "not eligible",
    "will not be given",
    "only one of",
    "has already been obtained",
    "has been obtained",
)


# ---------------------------------------------------------------------------
# Node constructors -- exactly the JSON shape documented in CLAUDE.md
# ---------------------------------------------------------------------------

def course_node(subject: str, number: str, home_subject: str = CMPUT_SUBJECT) -> dict:
    subject = normalize_subject(subject)
    return {
        "type": "COURSE",
        "code": subject + " " + number,
        "external": subject != home_subject,
    }


def level_min_node(min_level: int, subject: str) -> dict:
    return {"type": "LEVEL_MIN", "subject": subject, "min_level": min_level}


def and_node(children: list) -> dict:
    children = _flatten(children, "AND")
    return children[0] if len(children) == 1 else {"type": "AND", "children": children}


def or_node(children: list) -> dict:
    children = _flatten(children, "OR")
    return children[0] if len(children) == 1 else {"type": "OR", "children": children}


def _flatten(children: list, kind: str) -> list:
    """Collapse a nested node of the same kind into its parent -- AND[a, AND[b, c]]
    is the same requirement as AND[a, b, c] and renders far better as a tree."""
    out = []
    for c in children:
        if c is None:
            continue
        if c.get("type") == kind:
            out.extend(c["children"])
        else:
            out.append(c)
    return out


def normalize_subject(subject: str) -> str:
    """'Math' -> 'MATH', 'E E' -> 'E E'. The catalogue is inconsistent about
    case ('Math 30-1' vs 'MATH 125') for what is the same subject."""
    return re.sub(r"\s+", " ", subject.strip()).upper()


# ---------------------------------------------------------------------------
# Pre-pass: expand bare numbers to full codes using the last subject seen
# ---------------------------------------------------------------------------

# Numbers that must NOT be read as course references.
_SKIP_NUMBER_CONTEXT_RE = re.compile(r"^\s*(?:-level|-year|\s*\))", re.I)


def expand_bare_numbers(text: str, home_subject: str = CMPUT_SUBJECT) -> str:
    """'CMPUT 201 and 204, or 275' -> 'CMPUT 201 and CMPUT 204, or CMPUT 275'.

    Left-to-right so each bare number picks up the most recent explicit
    subject, which is exactly how the catalogue's lists read."""
    out = []
    pos = 0
    current = home_subject
    # Walk every number-like token, deciding per token whether it is already
    # qualified by a preceding subject.
    for m in re.finditer(r"\b(" + _SUBJECT + r")?\s*\b(" + _NUMBER + r")\b", text):
        if m.start(2) < pos:
            continue
        after = text[m.end(2):]
        if _SKIP_NUMBER_CONTEXT_RE.match(after):
            continue  # "300-level", "(1)" etc.
        subject_tok = m.group(1)
        if subject_tok and not _is_connector(subject_tok):
            current = normalize_subject(subject_tok)
            out.append(text[pos:m.start(2)])
            out.append(m.group(2))
        else:
            # Bare number -- qualify it with the running subject.
            out.append(text[pos:m.start(2)])
            out.append(current + " " + m.group(2))
        pos = m.end(2)
    out.append(text[pos:])
    return "".join(out)


_CONNECTOR_WORDS = {"and", "or", "one", "of", "any", "the", "in", "for", "both", "level"}


def _is_connector(tok: str) -> bool:
    return tok.strip().lower() in _CONNECTOR_WORDS


# ---------------------------------------------------------------------------
# Recursive-descent splitter
# ---------------------------------------------------------------------------

@dataclass
class ParseContext:
    home_subject: str = CMPUT_SUBJECT
    dropped: list = field(default_factory=list)   # informational atoms dropped
    unrecognized: list = field(default_factory=list)  # atoms we could not classify


# Ordered outermost-first. See the module docstring on why the comma matters.
#
# Level 3 (a bare comma meaning AND) is what makes CMPUT 411's
# "CMPUT 204 or 275, 301" come out as (204 OR 275) AND 301 rather than a flat
# OR -- the comma there is a requirement separator, not a list separator. It
# sits below ", or" and above bare "and"/"or" because it binds looser than
# either keyword but tighter than a comma-prefixed one.
_SPLIT_LEVELS = [
    (re.compile(r"\s*;\s*"), "AND"),
    (re.compile(r"\s*,\s+and\s+", re.I), "AND"),
    (re.compile(r"\s*,\s+or\s+", re.I), "OR"),
    (re.compile(r"\s*,\s*"), "AND"),
    (re.compile(r"\s+and\s+", re.I), "AND"),
    (re.compile(r"\s+or\s+", re.I), "OR"),
]
_COMMA_CONNECTOR_LEVELS = (1, 2)  # levels whose fragments may be comma lists

# ---------------------------------------------------------------------------
# "one of ..." is a bracket, not a filler phrase.
#
# It announces an OR-list, and every comma and "or" up to the end of the clause
# belongs to that list. Without protecting that span, the outer precedence
# rules reach inside it and shred it:
#
#   "CMPUT 204 and one of MATH 102, 125, 126, or 127"
#        the ", or" is INSIDE the one-of list, so splitting on it first would
#        yield OR[ AND[204, ...102, 125, 126], 127 ] instead of
#        AND[ 204, OR[102, 125, 126, 127] ].
#
# The span ends at the first ';' or ', and ' -- which is what lets CMPUT 415's
# "one of CMPUT 229, E E 380, or ECE 212, and any 300-level ... course" still
# split into its two AND branches.
# ---------------------------------------------------------------------------

# MATH spells the same "here comes an OR list" marker four ways:
#   "one of MATH 100, 113, ..."          (as in CMPUT)
#   "at least one of MATH 326, ..."      (MATH 483)
#   "either MATH 118 or MATH 216"        (MATH 217)
#   "any of ..."
# The "at least" prefix has to be inside the pattern rather than stripped
# separately, or the scope starts at "one" and leaves a dangling "at least".
_ONE_OF_RE = re.compile(
    r"\b(?:at\s+least\s+)?(?:one|any)\s+of\b|\beither\b", re.I
)

# A one-of list ends at ';', at ', and ', or -- the MATH 348 case -- at a bare
# ' and ' that introduces ANOTHER one-of list:
#     "One of MATH 102, 125 or 127 and one of MATH 209, 215, 217, 315"
# with no comma before "and". Without this third terminator the first scope
# swallows the second list and the whole thing collapses into one flat OR,
# turning an AND of two choices into "any one of these nine".
#
# The last alternative encodes a convention read off the corpus: across all 321
# scraped courses, EVERY one-of list closes with "or" ("one of MATH 102, 125 or
# 127"). Not one closes with "and". So a bare " and " followed by another course
# reference is not a final list item -- it is a separate requirement:
#
#     "One of MATH 311, 411 and MATH 436"   ->  (311 OR 411) AND 436
#
# Without this the scope runs to the end, MATH 436 is swallowed, and the tree
# claims MATH 311 alone is enough -- under-constrained, which is the dangerous
# direction to be wrong in. Re-check this assumption when adding a subject: a
# department that writes "one of A, B and C" meaning a plain OR would break it.
_SCOPE_END_RE = re.compile(
    r";|,\s+and\s+"
    r"|\s+and\s+(?=(?:at\s+least\s+)?(?:one|any)\s+of\b|either\b)"
    r"|\s+and\s+(?=[A-Z]{2,6}(?: [A-Z]{1,4})?\s+\d{2,3})",
    re.I,
)

# "both MATH 225 and 228" (MATH 326) is an AND group that must survive the
# ' and ' split intact, so it gets the same protection a one-of list gets.
_BOTH_RE = re.compile(r"\bboth\b", re.I)
_BOTH_SCOPE_END_RE = re.compile(r";|,", re.I)


def _protected_spans(text: str) -> list:
    # "both X and Y" groups are resolved first, because the "and" inside one is
    # part of that group and must not be mistaken for the end of an enclosing
    # one-of list. MATH 336's "either MATH 209, 217, 314 or both 214 and 216"
    # is exactly that collision.
    both_spans = []
    for m in _BOTH_RE.finditer(text):
        end = _BOTH_SCOPE_END_RE.search(text, m.end())
        both_spans.append((m.start(), end.start() if end else len(text)))

    spans = list(both_spans)
    for m in _ONE_OF_RE.finditer(text):
        end = len(text)
        for cand in _SCOPE_END_RE.finditer(text, m.end()):
            if any(s <= cand.start() < e for s, e in both_spans):
                continue
            end = cand.start()
            break
        spans.append((m.start(), end))
    return spans


def _split_unprotected(text: str, regex) -> list:
    """Split on `regex`, ignoring any match that falls inside a one-of span."""
    spans = _protected_spans(text)
    parts, last = [], 0
    for m in regex.finditer(text):
        if any(s <= m.start() < e for s, e in spans):
            continue
        parts.append(text[last:m.start()])
        last = m.end()
    parts.append(text[last:])
    return [p for p in parts if p.strip()]


def _is_whole_one_of_scope(text: str) -> bool:
    """True when the fragment is nothing but a one-of list, so every comma and
    'or' in it is an OR separator."""
    if not _ONE_OF_RE.match(text.strip()):
        return False
    spans = _protected_spans(text)
    return bool(spans) and spans[0][1] >= len(text.rstrip(".;, "))


# ", or " must be tried before a bare "," -- otherwise the comma matches first
# and the closing item is left as a stray "or 127".
_OR_LIST_SPLIT_RE = re.compile(r"\s*,\s*or\s+|\s*,\s*|\s+or\s+", re.I)

_COMMA_RE = re.compile(r"\s*,\s*")
# A fragment can start with a dangling connector -- splitting "...272; and one
# of MATH 100..." on ';' leaves "and one of MATH 100...". The enclosing split
# already fixed the node type, so a leading connector carries no information
# and would otherwise stop the atom from matching a course code.
_LEADING_CONNECTOR_RE = re.compile(r"^(?:and|or)\s+", re.I)
_HAS_CONNECTOR_RE = re.compile(r"\s+(?:and|or)\s+", re.I)


def _parse_expr(text: str, ctx: ParseContext, level: int = 0):
    text = _LEADING_CONNECTOR_RE.sub("", text.strip().strip(".;, ")).strip()
    if not text:
        return None

    # A fragment that is entirely a "one of ..." list is an OR over every item,
    # regardless of how its commas and "or"s are arranged.
    if _is_whole_one_of_scope(text):
        body = _ONE_OF_RE.sub("", text, count=1).strip(".;, ")
        children = [n for n in (_parse_atom(p, ctx) for p in _OR_LIST_SPLIT_RE.split(body)) if n]
        return or_node(children) if children else None

    for i in range(level, len(_SPLIT_LEVELS)):
        splitter, kind = _SPLIT_LEVELS[i]
        parts = _split_unprotected(text, splitter)
        if len(parts) < 2:
            continue

        if i == 0:
            # A semicolon usually joins AND clauses, but "...; or one of ..."
            # (CMPUT 200) makes the whole join an OR. The connector after the
            # semicolon is the only thing that says which.
            if any(_LEADING_CONNECTOR_RE.match(p.strip()) and
                   p.strip().lower().startswith("or ") for p in parts[1:]):
                kind = "OR"

        children = []
        for part in parts:
            # A bare-comma fragment is a list closed by this split's connector
            # ("A, B, or C"), so its commas mean the same thing this split does
            # -- but only when the fragment has no connector of its own.
            # ...but never flatten a one-of list this way: "one of CMPUT 340,
            # 418" is an OR regardless of which split produced it.
            if (i in _COMMA_CONNECTOR_LEVELS and "," in part
                    and not _HAS_CONNECTOR_RE.search(part)
                    and not _is_whole_one_of_scope(part)):
                for sub in _COMMA_RE.split(part):
                    node = _parse_expr(sub, ctx, i + 1)
                    if node:
                        children.append(node)
            else:
                node = _parse_expr(part, ctx, i + 1)
                if node:
                    children.append(node)

        if not children:
            return None
        return and_node(children) if kind == "AND" else or_node(children)

    return _parse_atom(text, ctx)


def _parse_atom(text: str, ctx: ParseContext):
    text = _ONE_OF_RE.sub("", text.strip(), count=1).strip(".;, ")
    if not text:
        return None

    m = LEVEL_MIN_RE.match(text)
    if m:
        raw_subject = m.group(2).strip()
        # MATH names the subject by CODE ("any 300-level MATH course") where
        # CMPUT spells it out ("any 300-level Computing Science course").
        # Accept either, but never guess at an unknown word.
        subject_code = SUBJECT_NAME_TO_CODE.get(raw_subject.lower())
        if not subject_code and re.fullmatch(_SUBJECT, raw_subject):
            subject_code = normalize_subject(raw_subject)
        if subject_code:
            return level_min_node(int(m.group(1)) * 100, subject_code)
        ctx.unrecognized.append(text)
        return None

    m = LEVEL_MIN_NO_SUBJECT_RE.match(text)
    if m:
        # "any 200-level course" with no subject -- assume the home subject,
        # and flag it, because that assumption is the parser's, not the
        # catalogue's.
        ctx.dropped.append(text + " (subject assumed to be " + ctx.home_subject + ")")
        return level_min_node(int(m.group(1)) * 100, ctx.home_subject)

    # "both 214 and 216" (MATH 336) -- an AND group sitting inside an OR list,
    # so it reaches the atom parser as a single fragment.
    m = BOTH_AND_RE.match(text)
    if m:
        parts = [_parse_atom(p, ctx) for p in re.split(r"\s+and\s+", m.group(1), flags=re.I)]
        parts = [p for p in parts if p]
        if len(parts) > 1:
            return and_node(parts)

    m = COURSE_CODE_FULL_RE.match(text)
    if m and not _is_connector(m.group(1)):
        return course_node(m.group(1), m.group(2), ctx.home_subject)

    if INFORMATIONAL_RE.match(text):
        ctx.dropped.append(text)
        return None

    ctx.unrecognized.append(text)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_prerequisite_text(text: Optional[str], home_subject: str = CMPUT_SUBJECT) -> dict:
    """Returns {tree, parse_status, notes, credit_exclusion_candidates}.

    tree is None for "no prerequisites" (whether the field was absent or said
    "None") and also for unparsed text -- parse_status is what tells them apart.
    """
    ctx = ParseContext(home_subject=home_subject)
    empty = {
        "tree": None,
        "parse_status": "parsed",
        "notes": [],
        "unrepresented": [],
        "credit_exclusion_candidates": [],
    }

    if text is None:
        return empty  # field absent entirely

    normalized = re.sub(r"\s+", " ", text).strip()
    normalized = PREREQ_OR_COREQ_LABEL_RE.sub("", normalized)  # before the two below
    normalized = PREREQ_LABEL_RE.sub("", normalized)
    normalized = COREQ_LABEL_RE.sub("", normalized)
    # "Pure Mathematics 30 or Mathematics 30-1" -> "PURE MATH 30 or MATH 30-1",
    # so the same high-school course is one node no matter how it is spelled.
    normalized = normalize_spelled_subjects(normalized)
    normalized = normalized.strip()

    if not normalized or NONE_TEXT_RE.match(normalized):
        return empty

    if TOO_COMPLEX_RE.search(normalized):
        # MATH 421/422: numbered alternatives and conditional combinations. A
        # guess here would be presented with the same confidence as a correct
        # parse, so refuse and let the raw text speak.
        return {
            "tree": None,
            "parse_status": "unparsed",
            "notes": ["Requirement structure is too complex to parse reliably; "
                      "read the calendar text."],
            # The whole requirement is unrepresented, not just a fragment.
            "unrepresented": [normalized],
            "credit_exclusion_candidates": [],
        }

    # Parenthetical asides ("(MATH 322 recommended)") name courses without
    # requiring them -- drop them from the tree, keep them as a note.
    # Two alternatives -> two capture groups; exactly one is filled per match.
    asides = [
        (a or b).strip()
        for a, b in PAREN_ASIDE_RE.findall(normalized)
        if (a or b).strip()
    ]
    if asides:
        normalized = PAREN_ASIDE_RE.sub(" ", normalized).strip()

    if VARIES_RE.search(normalized):
        # "Prerequisites are determined by the instructor in the course
        # outline." -- an honest statement that there is no fixed list, not a
        # parse failure we should paper over with an empty tree.
        return {
            "tree": None,
            "parse_status": "unparsed",
            "notes": ["Prerequisites vary by section and are set by the instructor."],
            "unrepresented": [],
            "credit_exclusion_candidates": [],
        }

    negated, kept = _strip_negated_sentences(normalized)
    if not kept:
        return {
            "tree": None,
            "parse_status": "parsed",
            "notes": [],
            "unrepresented": [],
            "credit_exclusion_candidates": negated,
        }

    tree = _parse_expr(expand_bare_numbers(kept, home_subject), ctx)

    notes = list(ctx.dropped)
    notes.extend("not required, mentioned only as an aside: " + a for a in asides)
    if ctx.unrecognized:
        notes.extend("could not interpret: " + u for u in ctx.unrecognized)

    if tree is None:
        status = "unparsed"
    elif ctx.dropped or ctx.unrecognized or asides:
        status = "partial"
    else:
        status = "parsed"

    return {
        "tree": tree,
        "parse_status": status,
        "notes": notes,
        # Fragments that state a real requirement the tree does NOT represent --
        # MATH 570's "a 400 or 500 level course on Partial Differential
        # Equations", for instance, which the schema cannot express. Kept apart
        # from `notes` (which also carries harmless drops like "consent of the
        # Department") so the UI can tell the two cases apart: one means the
        # tree is incomplete, the other does not.
        "unrepresented": list(ctx.unrecognized),
        "credit_exclusion_candidates": negated,
    }


def _strip_negated_sentences(text: str):
    """Drop any sentence carrying a negation cue, capturing the course codes it
    mentioned as credit-exclusion candidates instead of letting them reach the
    requirement parser. Returns (excluded_codes, kept_text)."""
    sentences = re.split(r"(?<=[.;])\s+", text)
    kept, excluded = [], []
    for sentence in sentences:
        lowered = sentence.lower()
        if any(cue in lowered for cue in NEGATION_CUES):
            excluded.extend(_codes_in(sentence))
        else:
            kept.append(sentence)
    return excluded, " ".join(kept).strip()


def _codes_in(text: str) -> list:
    """Every course code in a fragment, with bare numbers resolved against the
    last subject seen (same list grammar as prerequisites)."""
    codes = []
    for m in COURSE_CODE_RE.finditer(expand_bare_numbers(text)):
        if _is_connector(m.group(1)):
            continue
        after = text[m.end(2):] if m.end(2) <= len(text) else ""
        if _SKIP_NUMBER_CONTEXT_RE.match(after):
            continue
        code = normalize_subject(m.group(1)) + " " + m.group(2)
        if code not in codes:
            codes.append(code)
    return codes


def extract_credit_exclusions(exclusion_text: Optional[str], self_code: Optional[str] = None) -> list:
    """Pull course codes out of credit-exclusion sentences such as
        "Credit may be obtained in only one of CMPUT 301, BTM 419, or MIS 419."
        "Credit cannot be obtained for both CMPUT 174 and CMPUT 274."
    These are NOT prerequisites and must never reach parse_prerequisite_text.
    The course's own code is filtered out -- "only one of CMPUT 301, ..." names
    301 itself, which is not an exclusion *for* 301."""
    if not exclusion_text:
        return []
    codes = _codes_in(exclusion_text)
    if self_code:
        codes = [c for c in codes if c != self_code]
    return codes


def parse_corequisite_text(text: Optional[str], home_subject: str = CMPUT_SUBJECT) -> dict:
    """Corequisites use the same list grammar as prerequisites but are NOT
    folded into the eligibility check (CLAUDE.md: 'must be taken in the same
    term', not 'must already be completed'). Parsed into the same tree shape so
    the UI can render them, kept in a separate field."""
    return parse_prerequisite_text(text, home_subject)
