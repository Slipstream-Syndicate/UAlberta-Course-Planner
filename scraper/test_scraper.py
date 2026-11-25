"""
Offline tests for scraper/scraper.py -- no network, no HTML cache needed.

Covers the sentence classifier (the part that decides which sentence is a
prerequisite at all), the output merge that keeps a partial scrape from
deleting other subjects, and the retry/backoff behaviour of fetch().

    python scraper/test_scraper.py
"""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import scraper  # noqa: E402

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
        print("       expected: {!r}".format(expected))
        print("       actual:   {!r}".format(actual))


def test_abbreviations_do_not_split_sentences():
    """The guards once compared the characters BEFORE the period and never
    fired, so 'e.g. CMPUT 201' became two sentences."""
    check("e.g. and Dr. are not boundaries",
          scraper.split_sentences(
              "Prerequisites: a course e.g. CMPUT 201 or equivalent. Taught by Dr. Smith."),
          ["Prerequisites: a course e.g. CMPUT 201 or equivalent.", "Taught by Dr. Smith."])


def test_classifier_routes_each_sentence():
    f = scraper.classify_description(
        "An introduction to things. Prerequisites: CMPUT 201 or 275. "
        "Credit may be obtained in only one of CMPUT 301, BTM 419, or MIS 419. "
        "CMPUT 301 is a prerequisite for CMPUT 401."
    )
    check("prose", f["description"], "An introduction to things.")
    check("prereq", f["prerequisites_text"], "Prerequisites: CMPUT 201 or 275.")
    check("exclusion", f["credit_exclusion_text"],
          "Credit may be obtained in only one of CMPUT 301, BTM 419, or MIS 419.")
    check("reverse direction is a note, never a prereq", f["notes_text"],
          "CMPUT 301 is a prerequisite for CMPUT 401.")


def test_prereq_or_coreq_goes_to_the_corequisite_side():
    f = scraper.classify_description("Some calculus. Prerequisite or corequisite: MATH 100.")
    check("combined field is a coreq", f["corequisites_text"], "Prerequisite or corequisite: MATH 100.")
    check("and not a prereq", f["prerequisites_text"], None)


def test_parse_course_page_reads_the_real_markup_shape():
    """Synthetic page in the shape documented at the top of scraper.py, so
    the BeautifulSoup extraction is exercised without the HTML cache."""
    html = """<html><body><h1>CMPUT 301 - Introduction to Software Engineering</h1>
      <b>Fall Term 2026</b> <b>3 units (fi 6)(EITHER, 3-0-3)</b>
      <p>Faculty of Science</p>
      <p>Object-oriented design and analysis, with interactive applications as the
      primary example. Prerequisite: CMPUT 201 or 275. Credit may be obtained in
      only one of CMPUT 301, BTM 419, or MIS 419.</p></body></html>"""
    e = scraper.parse_course_page(html, "301", "https://apps.ualberta.ca/catalogue/course/cmput/301", "CMPUT")
    check("code", e.code, "CMPUT 301")
    check("title", e.title, "Introduction to Software Engineering")
    check("term", e.effective_term, "Fall Term 2026")
    check("units", e.units, 3.0)
    check("faculty", e.faculty, "Faculty of Science")
    check("prereq sentence", e.prerequisites_text, "Prerequisite: CMPUT 201 or 275.")
    check("exclusion kept apart", "BTM 419" in (e.credit_exclusion_text or ""), True)
    check("no warnings", e.scrape_warnings, [])


def test_merge_keeps_other_subjects():
    """`--subjects math` must replace MATH and leave every other subject."""
    existing = [
        {"subject": "CMPUT", "code": "CMPUT 101"},
        {"subject": "MATH", "code": "MATH 100"},
        {"subject": "STAT", "code": "STAT 151"},
    ]
    new = [{"subject": "MATH", "code": "MATH 100"}, {"subject": "MATH", "code": "MATH 101"},
           {"subject": "PHYS", "code": "PHYS 124"}]
    merged = scraper.merge_into_existing(new, existing)
    check("order kept, subject replaced in place, new subject appended",
          [e["code"] for e in merged],
          ["CMPUT 101", "MATH 100", "MATH 101", "STAT 151", "PHYS 124"])


class _Resp:
    def __init__(self, status, text="<html></html>", headers=None):
        self.status_code = status
        self.text = text
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise scraper.requests.HTTPError("HTTP {}".format(self.status_code))


def _with_fake_network(responses, fn):
    """Run fn with requests.get returning `responses` in order, sleeps
    recorded instead of slept, and the cache pointed at a temp dir."""
    calls, sleeps = [], []
    real_get, real_sleep, real_cache = scraper.requests.get, scraper.time.sleep, scraper.HTML_CACHE_DIR

    def fake_get(url, **kw):
        calls.append(url)
        r = responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    with tempfile.TemporaryDirectory() as tmp:
        scraper.requests.get = fake_get
        scraper.time.sleep = sleeps.append
        scraper.HTML_CACHE_DIR = Path(tmp)
        try:
            result = fn()
        except Exception as e:  # noqa: BLE001 -- the test inspects it
            result = e
        finally:
            scraper.requests.get = real_get
            scraper.time.sleep = real_sleep
            scraper.HTML_CACHE_DIR = real_cache
    return result, calls, sleeps


def test_fetch_retries_transient_errors_then_succeeds():
    result, calls, sleeps = _with_fake_network(
        [_Resp(503), _Resp(429, headers={"Retry-After": "7"}), _Resp(200, "ok")],
        lambda: scraper.fetch("https://example.invalid/x", "x", refresh=True),
    )
    check("eventually returns the body", result, "ok")
    check("three attempts", len(calls), 3)
    check("backs off, honours Retry-After, then the normal delay",
          sleeps, [scraper.BACKOFF_SECONDS, 7.0, scraper.REQUEST_DELAY_SECONDS])


def test_fetch_does_not_retry_a_404():
    result, calls, _ = _with_fake_network(
        [_Resp(404)], lambda: scraper.fetch("https://example.invalid/y", "y", refresh=True))
    check("404 raises", isinstance(result, scraper.requests.HTTPError), True)
    check("404 is not retried", len(calls), 1)


def main():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        print(t.__name__)
        t()
    print("\n{} passed, {} failed".format(PASSED, FAILED))
    sys.exit(1 if FAILED else 0)


if __name__ == "__main__":
    main()
