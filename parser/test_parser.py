"""
Golden test set for parser.py -- Phase 1 exit criterion per DESIGN.md.

Seeded with the three fixtures DESIGN.md names (CMPUT 272's flat OR, CMPUT
301's OR-plus-credit-exclusion, CMPUT 415's AND-of-OR-plus-LEVEL_MIN), then
grown with every edge case the real scrape turned up -- most importantly the
comma-precedence pair that has the same keywords and opposite trees:

    CMPUT 204  "CMPUT 175 or 275, and CMPUT 272"   -> (175 OR 275) AND 272
    CMPUT 361  "CMPUT 201 and CMPUT 204, or 275"   -> (201 AND 204) OR 275

Re-run after ANY regex change:  python parser/test_parser.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from parser import (  # noqa: E402
    parse_prerequisite_text,
    parse_corequisite_text,
    extract_credit_exclusions,
    expand_bare_numbers,
    course_node,
    or_node,
    and_node,
    level_min_node,
    _codes_in,
)

PASSED = 0
FAILED = 0


def check(name, actual, expected):
    global PASSED, FAILED
    if actual == expected:
        PASSED += 1
        print("  ok   " + name)
    else:
        FAILED += 1
        print("  FAIL " + name)
        print("       expected: {}".format(expected))
        print("       actual:   {}".format(actual))


def C(sub, num):
    return course_node(sub, num)


# ---------------------------------------------------------------------------
# The three fixtures named in DESIGN.md
# ---------------------------------------------------------------------------

def test_cmput_272_flat_or():
    r = parse_prerequisite_text(
        "Prerequisites: CMPUT 101, 174, 175, 274, SCI 100, or ENCMP 100."
    )
    check("272 status", r["parse_status"], "parsed")
    check("272 tree", r["tree"], or_node([
        C("CMPUT", "101"), C("CMPUT", "174"), C("CMPUT", "175"),
        C("CMPUT", "274"), C("SCI", "100"), C("ENCMP", "100"),
    ]))
    check("272 external flags",
          [c["external"] for c in r["tree"]["children"]],
          [False, False, False, False, True, True])


def test_cmput_301_or_plus_credit_exclusion():
    r = parse_prerequisite_text("Prerequisite: CMPUT 201 or CMPUT 275.")
    check("301 status", r["parse_status"], "parsed")
    check("301 tree", r["tree"], or_node([C("CMPUT", "201"), C("CMPUT", "275")]))
    check("301 credit exclusions (own code filtered out)",
          extract_credit_exclusions(
              "Credit may be obtained in only one of CMPUT 301, BTM 419, or MIS 419.",
              self_code="CMPUT 301"),
          ["BTM 419", "MIS 419"])


def test_cmput_415_and_of_or_plus_level_min():
    r = parse_prerequisite_text(
        "Prerequisites: one of CMPUT 229, E E 380, or ECE 212, "
        "and any 300-level Computing Science course."
    )
    check("415 status", r["parse_status"], "parsed")
    check("415 tree", r["tree"], and_node([
        or_node([C("CMPUT", "229"), C("E E", "380"), C("ECE", "212")]),
        level_min_node(300, "CMPUT"),
    ]))
    check("415 external flags",
          {c["code"]: c["external"] for c in r["tree"]["children"][0]["children"]},
          {"CMPUT 229": False, "E E 380": True, "ECE 212": True})


# ---------------------------------------------------------------------------
# Comma precedence -- the pair that makes or breaks the whole graph
# ---------------------------------------------------------------------------

def test_comma_and_groups_the_or_first():
    """CMPUT 204: '175 or 275, and 272' -> (175 OR 275) AND 272."""
    r = parse_prerequisite_text(
        "Prerequisites: CMPUT 175 or 275, and CMPUT 272; "
        "and one of MATH 100, 114, 117, 134, 144, or 154."
    )
    check("204 status", r["parse_status"], "parsed")
    check("204 tree", r["tree"], and_node([
        or_node([C("CMPUT", "175"), C("CMPUT", "275")]),
        C("CMPUT", "272"),
        or_node([C("MATH", "100"), C("MATH", "114"), C("MATH", "117"),
                 C("MATH", "134"), C("MATH", "144"), C("MATH", "154")]),
    ]))


def test_comma_or_groups_the_and_first():
    """CMPUT 361: '201 and 204, or 275' -> (201 AND 204) OR 275.
    Same keywords as the test above, opposite tree."""
    r = parse_prerequisite_text(
        "Prerequisites: CMPUT 201 and CMPUT 204, or CMPUT 275."
    )
    check("361 status", r["parse_status"], "parsed")
    check("361 tree", r["tree"], or_node([
        and_node([C("CMPUT", "201"), C("CMPUT", "204")]),
        C("CMPUT", "275"),
    ]))


def test_cmput_307_nested_or_of_and():
    """'CMPUT 206, or CMPUT 204 and one of MATH 225 or 227'."""
    r = parse_prerequisite_text(
        "Prerequisites: CMPUT 206, or CMPUT 204 and one of MATH 225 or 227."
    )
    check("307 status", r["parse_status"], "parsed")
    check("307 tree", r["tree"], or_node([
        C("CMPUT", "206"),
        and_node([C("CMPUT", "204"), or_node([C("MATH", "225"), C("MATH", "227")])]),
    ]))


def test_cmput_393_comma_list_means_and():
    """'CMPUT 200, 201, 204, and 291, and one of CMPUT 191 or 195' -- here the
    bare commas are an AND list, because the list closes with 'and'."""
    r = parse_prerequisite_text(
        "Prerequisites: CMPUT 200, 201, 204, and 291, and one of CMPUT 191 or 195."
    )
    check("393 status", r["parse_status"], "parsed")
    check("393 tree", r["tree"], and_node([
        C("CMPUT", "200"), C("CMPUT", "201"), C("CMPUT", "204"), C("CMPUT", "291"),
        or_node([C("CMPUT", "191"), C("CMPUT", "195")]),
    ]))


# ---------------------------------------------------------------------------
# Subject inheritance
# ---------------------------------------------------------------------------

def test_cmput_474_one_of_list_is_not_shredded_by_outer_or():
    """'CMPUT 204 and one of MATH 102, 125, 126, or 127' -- the ', or' belongs
    to the one-of list, so it must NOT become the outermost split."""
    r = parse_prerequisite_text(
        "Prerequisites: CMPUT 204 and one of MATH 102, 125, 126, or 127."
    )
    check("474 status", r["parse_status"], "parsed")
    check("474 tree", r["tree"], and_node([
        C("CMPUT", "204"),
        or_node([C("MATH", "102"), C("MATH", "125"), C("MATH", "126"), C("MATH", "127")]),
    ]))


def test_cmput_411_bare_comma_is_a_requirement_separator():
    """'CMPUT 204 or 275, 301' -- the comma separates two requirements; reading
    it as another OR alternative would tell a student 301 alone is enough."""
    r = parse_prerequisite_text(
        "Prerequisites: CMPUT 204 or 275, 301; one of CMPUT 340, 418, and MATH 214."
    )
    check("411 status", r["parse_status"], "parsed")
    check("411 tree", r["tree"], and_node([
        or_node([C("CMPUT", "204"), C("CMPUT", "275")]),
        C("CMPUT", "301"),
        or_node([C("CMPUT", "340"), C("CMPUT", "418")]),
        C("MATH", "214"),
    ]))


def test_cmput_200_semicolon_followed_by_or_is_an_or_join():
    """'...; or one of ...' -- the semicolon joins with OR here, not AND."""
    r = parse_prerequisite_text(
        "Prerequisite: one of CMPUT 191 or 195; or one of CMPUT 174 or 274 or ENCMP 100, "
        "and one of STAT 151, 161, or MATH 181."
    )
    check("200 status", r["parse_status"], "parsed")
    check("200 tree", r["tree"], or_node([
        or_node([C("CMPUT", "191"), C("CMPUT", "195")]),
        and_node([
            or_node([C("CMPUT", "174"), C("CMPUT", "274"), C("ENCMP", "100")]),
            or_node([C("STAT", "151"), C("STAT", "161"), C("MATH", "181")]),
        ]),
    ]))


def test_one_of_list_without_comma_before_or():
    """CMPUT 428: 'one of MATH 101, 115, 118, 136, 146 or 156' -- no comma
    before the closing 'or'."""
    r = parse_prerequisite_text(
        "Prerequisites: one of MATH 101, 115, 118, 136, 146 or 156."
    )
    check("428 list status", r["parse_status"], "parsed")
    check("428 list tree", r["tree"], or_node([
        C("MATH", "101"), C("MATH", "115"), C("MATH", "118"),
        C("MATH", "136"), C("MATH", "146"), C("MATH", "156"),
    ]))


def test_bare_numbers_inherit_last_subject():
    check("expand across subjects",
          expand_bare_numbers("CMPUT 204; one of MATH 209, 214, or 217"),
          "CMPUT 204; one of MATH 209, MATH 214, or MATH 217")
    check("expand does not touch '300-level'",
          expand_bare_numbers("any 300-level Computing Science course"),
          "any 300-level Computing Science course")


def test_cmput_461_leading_bare_number_defaults_to_cmput():
    """CMPUT 461's text starts '201 or 275' with no subject at all."""
    r = parse_prerequisite_text(
        "Prerequisites: 201 or 275, and any 300-level Computing Science course."
    )
    check("461 status", r["parse_status"], "parsed")
    check("461 tree", r["tree"], and_node([
        or_node([C("CMPUT", "201"), C("CMPUT", "275")]),
        level_min_node(300, "CMPUT"),
    ]))


def test_multiword_subject_and_lowercase_subject():
    r = parse_prerequisite_text("Prerequisite: one of CMPUT 229, E E 380 or ECE 212.")
    check("329 tree (E E survives)", r["tree"], or_node([
        C("CMPUT", "229"), C("E E", "380"), C("ECE", "212"),
    ]))
    r2 = parse_prerequisite_text("Prerequisite: Math 30, 30-1, or 30-2.")
    check("174 high-school prereqs normalize to MATH", r2["tree"], or_node([
        C("MATH", "30"), C("MATH", "30-1"), C("MATH", "30-2"),
    ]))
    check("174 high-school prereqs are external",
          all(c["external"] for c in r2["tree"]["children"]), True)


# ---------------------------------------------------------------------------
# Empty / absent / varies
# ---------------------------------------------------------------------------

def test_field_absent():
    r = parse_prerequisite_text(None)
    check("absent status", r["parse_status"], "parsed")
    check("absent tree", r["tree"], None)


def test_field_says_none():
    r = parse_prerequisite_text("Prerequisites: None")
    check("'None' status", r["parse_status"], "parsed")
    check("'None' tree", r["tree"], None)


def test_instructor_defined_is_unparsed_not_empty():
    """'determined by the instructor' must NOT collapse to 'no prerequisites' --
    that would tell a student a gated course is wide open."""
    r = parse_prerequisite_text(
        "Prerequisites are determined by the instructor in the course outline."
    )
    check("varies status", r["parse_status"], "unparsed")
    check("varies tree", r["tree"], None)
    check("varies note present", bool(r["notes"]), True)


# ---------------------------------------------------------------------------
# Negation -- DESIGN.md's highest-risk parser bug
# ---------------------------------------------------------------------------

def test_negation_never_becomes_a_prerequisite():
    r = parse_prerequisite_text(
        "Prerequisites: CMPUT 175. Not open to students with credit in CMPUT 274."
    )
    check("negation status", r["parse_status"], "parsed")
    check("negation tree is only CMPUT 175", r["tree"], C("CMPUT", "175"))
    check("negated course captured as exclusion candidate",
          r["credit_exclusion_candidates"], ["CMPUT 274"])


def test_credit_exclusion_sentence_never_becomes_a_prerequisite():
    r = parse_prerequisite_text(
        "Prerequisite: CMPUT 201. Credit cannot be obtained for both CMPUT 201 and CMPUT 275."
    )
    check("exclusion-in-prereq tree", r["tree"], C("CMPUT", "201"))
    check("exclusion-in-prereq candidates",
          r["credit_exclusion_candidates"], ["CMPUT 201", "CMPUT 275"])


def test_credit_exclusion_both_phrasing():
    check("'both X and Y' exclusion",
          extract_credit_exclusions(
              "Credit cannot be obtained for both CMPUT 174 and CMPUT 274.",
              self_code="CMPUT 174"),
          ["CMPUT 274"])
    check("'cannot be taken for credit if' exclusion",
          extract_credit_exclusions(
              "This course cannot be taken for credit if credit has been obtained "
              "in CMPUT 174, 175, 274, 275, or ENCMP 100.",
              self_code="CMPUT 101"),
          ["CMPUT 174", "CMPUT 175", "CMPUT 274", "CMPUT 275", "ENCMP 100"])


# ---------------------------------------------------------------------------
# Informational atoms degrade to `partial`, never silently vanish
# ---------------------------------------------------------------------------

def test_permission_of_department_degrades_to_partial():
    r = parse_prerequisite_text(
        "Prerequisite: CMPUT 201 and CMPUT 204, or CMPUT 275; "
        "and permission of the Department."
    )
    check("312 status is partial", r["parse_status"], "partial")
    check("312 tree keeps the real courses", r["tree"], or_node([
        and_node([C("CMPUT", "201"), C("CMPUT", "204")]),
        C("CMPUT", "275"),
    ]))
    check("312 note records what was dropped",
          any("permission" in n.lower() for n in r["notes"]), True)


def test_single_course_no_connectors():
    r = parse_prerequisite_text("Prerequisite: CMPUT 274.")
    check("single status", r["parse_status"], "parsed")
    check("single tree", r["tree"], C("CMPUT", "274"))


def test_level_min_alone():
    r = parse_prerequisite_text("Prerequisite: any 300-level Computing Science course.")
    check("355 status", r["parse_status"], "parsed")
    check("455 tree", r["tree"], level_min_node(300, "CMPUT"))


def test_level_min_without_subject_is_flagged():
    """CMPUT 300: 'any 200-level course' names no subject. We assume CMPUT but
    must say so rather than presenting the guess as fact."""
    r = parse_prerequisite_text("Prerequisites: CMPUT 174, and any 200-level course.")
    check("300 status is partial", r["parse_status"], "partial")
    check("300 assumption is recorded",
          any("assumed" in n for n in r["notes"]), True)


def test_corequisites_parse_with_same_grammar():
    r = parse_corequisite_text("Corequisite: one of CMPUT 201 or 275.")
    check("coreq status", r["parse_status"], "parsed")
    check("coreq tree", r["tree"], or_node([C("CMPUT", "201"), C("CMPUT", "275")]))


# ---------------------------------------------------------------------------
# MATH (Phase 5, first subject beyond CMPUT)
#
# Every fixture below is real MATH calendar text. They exist because MATH
# phrases things CMPUT never does -- these are the shapes that broke the
# CMPUT-only parser.
# ---------------------------------------------------------------------------

def M(sub, num):
    return course_node(sub, num, "MATH")


def test_math_spelled_out_subject_names():
    """MATH 114: 'Pure Mathematics 30 or Mathematics 30-1 or equivalent.'
    CMPUT writes 'Math 30-1' for the same kind of high-school prerequisite;
    both must normalize to one code or the graph gets duplicate nodes."""
    r = parse_prerequisite_text(
        "Prerequisite: Pure Mathematics 30 or Mathematics 30-1 or equivalent.", "MATH"
    )
    check("114 status is partial ('or equivalent' dropped)", r["parse_status"], "partial")
    check("114 tree", r["tree"], or_node([M("PURE MATH", "30"), M("MATH", "30-1")]))
    check("114 records the dropped clause",
          any("equivalent" in n for n in r["notes"]), True)


def test_math_100_spelled_subject_and_join():
    r = parse_prerequisite_text(
        "Prerequisites: Mathematics 30-1 and Mathematics 31.", "MATH"
    )
    check("100 status", r["parse_status"], "parsed")
    check("100 tree", r["tree"], and_node([M("MATH", "30-1"), M("MATH", "31")]))


def test_math_either_is_an_or_marker():
    """MATH 217: 'One of MATH 102, 125 or 127, and either MATH 118 or MATH 216.'
    'either' had to become a scope marker; without it the parser read a subject
    called 'EITHER MATH'."""
    r = parse_prerequisite_text(
        "Prerequisites: One of MATH 102, 125 or 127, and either MATH 118 or MATH 216.",
        "MATH",
    )
    check("217 status", r["parse_status"], "parsed")
    check("217 tree", r["tree"], and_node([
        or_node([M("MATH", "102"), M("MATH", "125"), M("MATH", "127")]),
        or_node([M("MATH", "118"), M("MATH", "216")]),
    ]))


def test_math_336_both_group_nested_in_an_or_list():
    """MATH 336: '...either MATH 209, 217, 314 or both 214 and 216.'
    'both X and Y' is an AND group sitting inside an OR list."""
    r = parse_prerequisite_text(
        "Prerequisites: MATH 225 or 227, and either MATH 209, 217, 314 or both 214 and 216.",
        "MATH",
    )
    check("336 status", r["parse_status"], "parsed")
    check("336 tree", r["tree"], and_node([
        or_node([M("MATH", "225"), M("MATH", "227")]),
        or_node([
            M("MATH", "209"), M("MATH", "217"), M("MATH", "314"),
            and_node([M("MATH", "214"), M("MATH", "216")]),
        ]),
    ]))


def test_math_at_least_one_of():
    """MATH 483. The 'at least' prefix must be consumed with 'one of', or the
    scope starts at 'one' and leaves a dangling fragment."""
    r = parse_prerequisite_text(
        "Prerequisite: at least one of MATH 326, MATH 327, MATH 328, MATH 329.", "MATH"
    )
    check("483 status", r["parse_status"], "parsed")
    check("483 tree", r["tree"], or_node([
        M("MATH", "326"), M("MATH", "327"), M("MATH", "328"), M("MATH", "329"),
    ]))


def test_math_level_min_by_subject_code_and_determiner():
    """MATH names the subject by CODE and varies the determiner and the noun --
    'Any 100-level MATH course', 'a 300-level MATH course', '400-level MATH
    course', 'any 300-level MATH class'."""
    for text, level in [
        ("Prerequisite: Any 100-level MATH course.", 100),
        ("Prerequisite: a 300-level MATH course.", 300),
        ("Prerequisite: 400-level MATH course.", 400),
        ("Prerequisite: any 300-level MATH class.", 300),
    ]:
        r = parse_prerequisite_text(text, "MATH")
        check("level_min: " + text[14:40], r["tree"], level_min_node(level, "MATH"))


def test_math_two_token_subject_ma_ph():
    r = parse_prerequisite_text(
        "Prerequisite: One of MATH 209, 215, 217, 315 or MA PH 351.", "MATH"
    )
    check("348 tree keeps MA PH intact", r["tree"], or_node([
        M("MATH", "209"), M("MATH", "215"), M("MATH", "217"),
        M("MATH", "315"), M("MA PH", "351"),
    ]))
    check("MA PH is external to MATH",
          r["tree"]["children"][-1]["external"], True)


def test_math_too_complex_degrades_rather_than_guesses():
    """MATH 422 enumerates alternatives with '(1) ... (2) ... (3) ...', and
    MATH 421 conditions one on 'when combined with'. A confident wrong tree is
    worse than an honest gap, so both refuse to parse."""
    for text in [
        "Prerequisites: either (1) MATH 227 or (2) MATH 228 and a 300-level MATH course "
        "or (3) MATH 226 and a 300-level MATH course.",
        "Prerequisites: MATH 326, or MATH 327, or any 300-level MATH class when combined "
        "with MATH 111 or MATH 228 (MATH 322 recommended).",
    ]:
        r = parse_prerequisite_text(text, "MATH")
        check("complex shape is unparsed: " + text[15:45], r["parse_status"], "unparsed")
        check("complex shape emits no tree", r["tree"], None)


def test_math_prerequisite_or_corequisite_label():
    """MATH 102/201/209 use a combined label CMPUT never does. Stripping it as
    two separate labels leaves 'or corequisite: MATH 100' and loses the
    requirement -- an empty tree claiming there is no corequisite at all."""
    r = parse_corequisite_text("Prerequisite or corequisite: MATH 100.", "MATH")
    check("102 coreq status", r["parse_status"], "parsed")
    check("102 coreq tree", r["tree"], M("MATH", "100"))


def test_math_527_embedded_corequisite_split_off():
    """'Prerequisite: MATH 436 or equivalent; corequisite: MATH 516.' -- one
    sentence, two fields. The corequisite must not become a hard prerequisite."""
    r = parse_prerequisite_text("Prerequisite: MATH 436 or equivalent", "MATH")
    check("527 prereq tree excludes the coreq", r["tree"], M("MATH", "436"))
    c = parse_corequisite_text("corequisite: MATH 516.", "MATH")
    check("527 coreq tree", c["tree"], M("MATH", "516"))


def test_math_326_both_group_outside_an_either_list():
    """MATH 326: 'MATH 227, or both MATH 225 and 228.' The 'both' group has no
    enclosing 'either' to protect it, so it needs its own scope."""
    r = parse_prerequisite_text("Prerequisite MATH 227, or both MATH 225 and 228.", "MATH")
    check("326 status", r["parse_status"], "parsed")
    check("326 tree", r["tree"], or_node([
        M("MATH", "227"),
        and_node([M("MATH", "225"), M("MATH", "228")]),
    ]))


def test_math_348_one_of_scope_ends_at_a_following_one_of():
    """'One of MATH 102, 125 or 127 and one of MATH 209, 215' -- no comma before
    'and'. If the first scope runs to the end it swallows the second list and an
    AND of two choices collapses into one flat OR of everything."""
    r = parse_prerequisite_text(
        "Prerequisites: One of MATH 102, 125 or 127 and one of MATH 209, 215.", "MATH"
    )
    check("348 status", r["parse_status"], "parsed")
    check("348 tree", r["tree"], and_node([
        or_node([M("MATH", "102"), M("MATH", "125"), M("MATH", "127")]),
        or_node([M("MATH", "209"), M("MATH", "215")]),
    ]))


def test_math_556_bare_and_ends_a_one_of_list():
    """MATH 556: 'One of MATH 311, 411 and MATH 436' -> (311 OR 411) AND 436.

    Across all 321 scraped courses every one-of list closes with "or", never
    "and", so a bare "and" before another course starts a new requirement. The
    bug this replaced left a tree saying MATH 311 alone was enough --
    under-constrained, which is the dangerous direction to be wrong in.
    """
    r = parse_prerequisite_text(
        "Prerequisites: One of MATH 311, 411 and MATH 436.", "MATH"
    )
    check("556 status", r["parse_status"], "parsed")
    check("556 tree", r["tree"], and_node([
        or_node([M("MATH", "311"), M("MATH", "411")]),
        M("MATH", "436"),
    ]))


def test_one_of_scope_still_survives_an_inner_both_group():
    """The rule above must not fire on the 'and' inside a 'both X and Y' group
    (MATH 336), which would truncate the enclosing list."""
    r = parse_prerequisite_text(
        "Prerequisites: either MATH 209, 217, 314 or both 214 and 216.", "MATH"
    )
    check("336 scope survives inner 'both'", r["tree"], or_node([
        M("MATH", "209"), M("MATH", "217"), M("MATH", "314"),
        and_node([M("MATH", "214"), M("MATH", "216")]),
    ]))


def test_math_parenthetical_aside_is_not_a_requirement():
    """'(MATH 322 recommended)' names a course without requiring it."""
    r = parse_prerequisite_text("Prerequisite: MATH 326 (MATH 322 recommended).", "MATH")
    check("aside status is partial", r["parse_status"], "partial")
    check("aside is not in the tree", r["tree"], M("MATH", "326"))
    check("aside is recorded as a note",
          any("MATH 322" in n for n in r["notes"]), True)


# ---------------------------------------------------------------------------
# QC regressions. Each fixture is real catalogue text that the parser got
# wrong at some point; the comment names the course it came from.
# ---------------------------------------------------------------------------

def shape(node):
    """A tree as a compact string, ignoring `external` (which depends on the
    dataset, not the parser) so these tests pin the STRUCTURE."""
    if not node:
        return "None"
    if node["type"] == "COURSE":
        return node["code"]
    if node["type"] == "LEVEL_MIN":
        subs = "/".join(node.get("subjects") or [node["subject"]])
        return "LEVEL({}>={})".format(subs, node["min_level"])
    return node["type"] + "[" + ", ".join(shape(c) for c in node["children"]) + "]"


def P(text, home):
    return parse_prerequisite_text(text, home)


def test_qc_trailing_or_list_without_serial_comma():
    """MATH 228: 'MATH 102, 125 or 127' is ANY ONE of three. Reading the bare
    comma as AND shipped 'MATH 102 AND (125 OR 127)' marked `parsed`."""
    r = P("Prerequisite: MATH 102, 125 or 127.", "MATH")
    check("228 status", r["parse_status"], "parsed")
    check("228 tree", shape(r["tree"]), "OR[MATH 102, MATH 125, MATH 127]")
    r = P("Prerequisites: PSYCH 350, 354, 356 or 357.", "PSYCH")
    check("458-shape tree", shape(r["tree"]), "OR[PSYCH 350, PSYCH 354, PSYCH 356, PSYCH 357]")


def test_qc_or_list_before_and_one_of():
    """ASTRO 320: the ' and one of' is the top-level join, not the comma."""
    r = P("Prerequisites: MATH 101, 115, 118, 136, 146 or 156 and one of PHYS 208 or 271.", "ASTRO")
    check("ASTRO 320 tree", shape(r["tree"]),
          "AND[OR[MATH 101, MATH 115, MATH 118, MATH 136, MATH 146, MATH 156], OR[PHYS 208, PHYS 271]]")


def test_qc_trailing_or_group_with_several_ors_stays_anded():
    """PHYS 372 / PSYCH 405: a last item that is its own multi-way OR is a
    separate requirement; the trailing-OR-list rule must not fire."""
    r = P("Prerequisites: PHYS 244, PHYS 271, MATH 334 or 336 or 201 or MA PH 251.", "PHYS")
    check("372 status", r["parse_status"], "parsed")
    check("372 tree", shape(r["tree"]),
          "AND[PHYS 244, PHYS 271, OR[MATH 334, MATH 336, MATH 201, MA PH 251]]")
    # CMPUT 411's requirement-separating comma is unchanged.
    r = P("Prerequisite: CMPUT 204 or 275, 301.", "CMPUT")
    check("411 still AND", shape(r["tree"]), "AND[OR[CMPUT 204, CMPUT 275], CMPUT 301]")


def test_qc_mixed_subject_list_is_flagged_ambiguous():
    """EAS 250: 'EAS 100, BIOL 108 or SCI 100' could mean either reading.
    Keep the conservative AND, but never claim a clean parse for it."""
    r = P("Prerequisite: EAS 100, BIOL 108 or SCI 100.", "EAS")
    check("EAS 250 status", r["parse_status"], "partial")
    check("EAS 250 keeps the conservative reading", shape(r["tree"]),
          "AND[EAS 100, OR[BIOL 108, SCI 100]]")
    check("EAS 250 is recorded as unrepresented",
          any(u.startswith("ambiguous grouping") for u in r["unrepresented"]), True)


def test_qc_minimum_grade_keeps_the_course():
    """The grade is informational; the course it qualifies is required."""
    r = P("Prerequisites: CMPUT 201 and CMPUT 175 with a minimum grade of C-.", "CMPUT")
    check("grade suffix keeps course", shape(r["tree"]), "AND[CMPUT 201, CMPUT 175]")
    check("grade suffix is partial", r["parse_status"], "partial")
    r = P("Prerequisite: a minimum grade of B in MATH 125.", "MATH")
    check("grade prefix keeps course", shape(r["tree"]), "MATH 125")


def test_qc_informational_fragment_naming_a_course_is_unrepresented():
    """A dropped 'informational' fragment that names a course must be
    reported as unrepresented, never dropped quietly."""
    r = P("Prerequisites: STAT 151 and restricted to students with credit in STAT 141.", "STAT")
    check("restricted fragment recorded",
          any("STAT 141" in u for u in r["unrepresented"]), True)


def test_qc_bare_numbers_use_the_courses_own_subject():
    """'361 or 362' in a CHEM course is CHEM, not CMPUT."""
    r = P("Prerequisite: 361 or 362.", "CHEM")
    check("home subject", shape(r["tree"]), "OR[CHEM 361, CHEM 362]")
    check("credit exclusions use home subject",
          extract_credit_exclusions("Credit may be obtained in only one of 102, 125 or 127.",
                                    self_code="MATH 127", home_subject="MATH"),
          ["MATH 102", "MATH 125"])


def test_qc_title_case_subject_code():
    """CHEM 460 writes 'Chem 361'."""
    r = P("Prerequisites: Chem 361 or consent of instructor.", "CHEM")
    check("Chem 361 -> CHEM 361", shape(r["tree"]), "CHEM 361")


def test_qc_quantities_are_not_course_numbers():
    """'30 units' is a quantity, not a course called CMPUT 30."""
    check("units are not codes", _codes_in("a minimum of 30 units or consent", "INT D"), [])
    r = P("Prerequisites: BIOL 322 or any 300 level MICRB course.", "MICRB")
    check("'300 level' without hyphen", shape(r["tree"]), "OR[BIOL 322, LEVEL(MICRB>=300)]")


def test_qc_codes_in_offsets_use_the_expanded_text():
    """Context checks used offsets from the expanded string against the
    original one and dropped 302 here."""
    check("302 survives", _codes_in("only one of CMPUT 301, 302 (Fall) or MATH 300"),
          ["CMPUT 301", "CMPUT 302", "MATH 300"])


def test_qc_sentence_boundary_and_repeated_labels():
    """BIOL 392 and PHYS 181 carry a second label inside the field."""
    r = P("Prerequisite: BIOL 207 and BIOL 208. Pre-requisite: BIOL 380.", "BIOL")
    check("BIOL 392 tree", shape(r["tree"]), "AND[BIOL 207, BIOL 208, BIOL 380]")
    r = P("Prerequisite: Prerequisite: PHYS 124 or 144 or EN PH 131.", "PHYS")
    check("PHYS 181 tree", shape(r["tree"]), "OR[PHYS 124, PHYS 144, EN PH 131]")
    r = P("Prerequisite CHEM 261 or 266. Prerequisite or co- requisite: CHEM265.", "CHEM")
    check("CHEM 267 prereq tree excludes the coreq option", shape(r["tree"]), "OR[CHEM 261, CHEM 266]")


def test_qc_any_one_of_slash_lists_and_stray_comma():
    r = P("Prerequisite: Any one of ENT 220, 222, or REN R 205, or ZOOL 250.", "ENT")
    check("ENT 327 any one of", shape(r["tree"]), "OR[ENT 220, ENT 222, REN R 205, ZOOL 250]")
    r = P("Prerequisites: GENET 270, MICRB 265 and BIOCH 203/205 or BIOCH 200.", "MICRB")
    check("MICRB 316 slash list", shape(r["tree"]),
          "AND[GENET 270, MICRB 265, OR[BIOCH 203, BIOCH 205, BIOCH 200]]")
    r = P("Prerequisites: PSYCH 212 and, PSYCH 213 or STAT 151 or STAT 161.", "PSYCH")
    check("PSYCH 315 stray comma", shape(r["tree"]),
          "AND[PSYCH 212, OR[PSYCH 213, STAT 151, STAT 161]]")


def test_qc_except_is_refused_not_inverted():
    """INT D 420: courses named after 'except' are NOT requirements."""
    r = P("Prerequisites: All courses in the BScN program except NURS 422, NURS 425 and NURS 485.", "INT D")
    check("except -> unparsed", r["parse_status"], "unparsed")
    check("except -> no tree claiming NURS 425 is required", r["tree"], None)


def test_qc_department_level_spans_its_subjects():
    """'a 200-level Biological Sciences course' accepts ZOOL/BOT/... too."""
    r = P("Prerequisite: a 200-level Biological Sciences course.", "ZOOL")
    check("department LEVEL_MIN", shape(r["tree"]), "LEVEL(BIOL/BOT/ENT/GENET/MICRB/ZOOL>=200)")


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        print(t.__name__)
        t()
    print("\n{} passed, {} failed".format(PASSED, FAILED))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
