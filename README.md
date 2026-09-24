# UAlberta Prerequisite & Course Planning Explorer

Scrapes University of Alberta course catalogues (**all 31 Faculty of Science
subjects, 1,277 courses**),
parses prerequisite sentences into boolean trees, and answers "what are my
options to get into course X" entirely in the browser.

**Not official academic advising.** See the disclaimer in the app and in
[CLAUDE.md](CLAUDE.md).

## Quick start

```bash
# Python side (scraper + parser)
python -m venv venv
./venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
# source venv/bin/activate && pip install -r requirements.txt  # macOS/Linux

python parser/subjects.py --refresh    # -> data/subjects.json (the closed vocabulary)
python scraper/scraper.py              # all 31 Science subjects (~1,300 requests, 1s apart, ~25 min)
python scraper/scraper.py --subjects cmput math stat   # or pick subjects explicitly
python parser/test_parser.py           # golden test set -- run before trusting a fresh scrape
python parser/build_courses.py         # -> data/courses.json + parse-status report
python parser/spotcheck.py             # eyeball 15 core CMPUT courses against raw text
python parser/spotcheck.py --math      # the 15 MATH courses covering its new grammar
python parser/audit_coverage.py        # every tree vs. its raw text -- catches silent drops
python parser/verify_all.py            # schema, flags, cycles, honesty across all courses
python parser/outliers.py              # what the parser had NO rule for, ranked by blast radius

# Frontend
cd frontend
npm install
npm test                               # eval engine + print title + full-app render
npm run dev
```

`data/courses_raw.json` and `data/courses.json` are **generated**. Never
hand-edit them; re-run the whole pipeline instead. They *are* committed to the
repo, though — see [Deploying](#deploying) for why.

If you just want to run the app and not touch the data, both JSON files are
already in the repo, so you can skip straight to the frontend steps.

## Layout

```
scraper/scraper.py        catalogue -> data/courses_raw.json (raw fields, no logic)
parser/parser.py          prerequisite text -> boolean tree
parser/build_courses.py   ETL: raw -> data/courses.json, + parse-status report
parser/test_parser.py     golden test set (92 assertions, CMPUT + MATH)
parser/spotcheck.py       human-readable tree vs. raw text, for manual validation
parser/audit_coverage.py  automated check: does each tree cover every course its text names?
parser/subjects.py        the closed vocabulary: 305 UAlberta subject codes + names
parser/outliers.py        ranked report of what no rule matched -- finds unknown unknowns
parser/verify_all.py      whole-dataset integrity: schema, flags, cycles, honesty
frontend/src/lib/verifyDataset.js  whole-dataset engine check (round-trips every course)
frontend/src/lib/evalEngine.js   the "what are my options" boolean walk
frontend/src/App.jsx      search, tree, options, print view
data/html_cache/          cached page HTML so parser iteration never re-hits the site
```

## Current accuracy (1,277 courses, 31 subjects, scraped 2026-09-05)

| Group | parsed | partial | unparsed |
|---|---|---|---|
| All courses (1,277) | 64.3% | 21.3% | 14.4% |
| Undergrad (755) | 58.0% | 31.1% | 10.9% |
| Graduate (522) | 73.4% | 7.1% | 19.5% |

`build_courses.py` prints a **per-subject table sorted worst-first**, because
accuracy does not transfer between departments and an aggregate hides a badly
parsed subject behind a well-tuned one. Read that table, not the total.

`partial` is the dominant non-clean status and is mostly honest: Science
departments attach "or consent of the Department", "or equivalent" and faculty
restrictions to a great many courses, and CLAUDE.md's non-goals keep those out
of the boolean graph. The tree is right; the dropped clause is recorded in
`notes` and shown in the UI and the printout.

**0 invented requirements** across all 853 courses that have prerequisite text
— nothing is fabricated. That property is asserted by `audit_coverage.py` on
every build.

## Things the catalogue does that the plan did not anticipate

Three findings changed the implementation, and all three are the kind that fail
silently rather than loudly:

**1. The index page's duplicate entries have no `Effective:` date.**
CLAUDE.md expected duplicated courses to be disambiguated by an effective date.
There is no such marker on the page today. 72 courses appear twice — a plain
`div.course` block and an indented `div.course.ms-3` one — with genuinely
different prerequisite text. Worse, checked against the individual course
pages, the block appearing **first** in the HTML is the *outdated* one for
CMPUT 101 and CMPUT 174. So the scraper ignores the index's description blocks
entirely and fetches every course page, which shows exactly one version and
labels the term it is in effect for.

**2. Prerequisites are not a labeled field.** They are a sentence embedded
mid-description. Extraction is sentence classification, not
"label: value up to the next label".

**3. Grouping is carried by comma placement, not by keywords.** These two
strings share their keywords and mean opposite things:

```
"CMPUT 175 or 275, and CMPUT 272"   ->  (175 OR 275) AND 272
"CMPUT 201 and 204, or 275"         ->  (201 AND 204) OR 275
```

A comma-prefixed connector binds looser than a bare one, `"one of ..."` is a
real scope bracket that outer splits must not reach inside of, and a bare comma
is itself a requirement separator (`"CMPUT 204 or 275, 301"` needs 301 *as well
as* one of 204/275 — reading it as another OR alternative would tell a student
301 alone is enough). All of this is in the golden test set.

## What MATH added that CMPUT never showed (Phase 5, subject 1 of 31)

Generalizing the scraper was nearly free — every Faculty of Science subject
uses the same URL pattern and `div.course` markup, and MATH has no duplicate
old/new course versions at all, so CMPUT's hardest problem simply doesn't
appear. The parser is where the work was. Each item below is a real shape that
broke the CMPUT-only parser:

| Shape | Example | Why it mattered |
|---|---|---|
| Reverse direction | `"...is a prerequisite for BIOL 108."` | Names a course this one **unlocks**. Keying on the word "prerequisite" draws every edge backwards. |
| Combined field | `"Prerequisite or corequisite: MATH 100."` | Read as a hard prerequisite it tells students they're ineligible for something they can register for. |
| Spelled-out subjects | `"Pure Mathematics 30 or Mathematics 30-1"` | CMPUT writes `Math 30-1`; both must resolve to one code or the graph gets duplicate nodes. |
| `either` / `at least one of` | `"either MATH 118 or MATH 216"` | New OR markers. `either` was being parsed as a subject named `EITHER MATH`. |
| `both X and Y` | `"MATH 227, or both MATH 225 and 228"` | An AND group nested inside an OR list. |
| Scope end | `"One of MATH 102, 125 or 127 and one of MATH 209, 215"` | No comma before `and`. The first list otherwise swallows the second, turning an AND of two choices into one flat OR of everything. |
| `LEVEL_MIN` variants | `"a 300-level MATH class"`, `"400-level MATH course"` | Determiner optional, subject given as a **code**, noun may be "class". |
| Malformed source | `"Prerequisite: MATH 127. 127;"` | The catalogue's own typo. |
| Run-on sentence | `"...Finite State Machines.Prerequisites: MATH 326..."` | No space after the period, so the prereq never separated from the description. |

Two MATH courses are **deliberately refused** rather than guessed at:

```
MATH 422  "either (1) MATH 227 or (2) MATH 228 and a 300-level MATH course or (3) ..."
MATH 421  "... or any 300-level MATH class when combined with MATH 111 or MATH 228"
```

Numbered alternatives and conditional combinations would be parsed with the
same confidence as a correct tree, so they report `unparsed` and the UI falls
back to the calendar text. Related fix: a null tree no longer renders as "No
prerequisites." when the status is `unparsed` — on screen *and* in the
printout it now says the requirements could not be read. Those are opposite
claims, and the render test asserts the distinction.

## Scaling to the whole Faculty: what made it safe

Going from 2 subjects to 31 was not more of the same parser. Two structural
changes did the work.

**1. A closed vocabulary replaced a guessing regex.** The parser used to decide
what a subject code looked like by shape — "1-6 letters, minus a stopword
list". That is unbounded: every subject added found a new way in (`OF MATH`,
`EITHER MATH`), and the fix was always another stopword. It could never be made
safe, because UAlberta has subjects literally named `DATA`, `AI`, `MM`, `BOT`
and `ENT`.

The catalogue publishes the real list at `/catalogue/course` — 305 subjects,
each as `CODE - Full Name`. `parser/subjects.py` scrapes it once into
`data/subjects.json`, and a token is now a subject **if and only if** it is in
that list. That deleted the stopword hack entirely, killed a whole class of
outlier, and supplied the spelled-out names (`Mathematics` → `MATH`) that had
been hardcoded one discipline at a time. It gets *stronger* as the university
adds subjects, not weaker.

Two small hand-kept lists remain, and both are bounded by nature rather than by
effort: Alberta high-school subjects (never in a university registry) and
**discontinued** codes still referenced in live text (`E E`, `MIS`, `HGP`,
`HGEO`). The outlier report is what tells you when one is missing.

**2. The parser reports what it does not understand.** `parser/outliers.py`
scans every course and groups what no rule matched — unknown subject codes,
unrepresented requirement shapes, novel vocabulary, leftover field labels,
suspiciously long text — ranked by how many courses each affects. At Faculty
scale you cannot read 1,277 courses, so the parser has to hand you the queue.

That report is how the first pass got from 54.8% to 58.0% parsed and 16.8% to
10.9% unparsed on undergrad courses in one sitting. It surfaced, in order of
blast radius:

| Finding | Courses | Fix |
|---|---|---|
| `[Faculty of Science]` / `[Faculty of Arts]` annotations | ~67 | Restricts *who may register*, not what is required — treat like a parenthetical aside |
| `HGP` / `HGEO` unknown subject | 13 | Discontinued subjects, added to the legacy list |
| "a 200-level **Biological Sciences** course" | ~22 | Department names, not subject codes — added an alias map |
| "a committed Thesis Supervisor" | 12 | Informational, not a graph node |
| "one 300-level PSYCH course" | 4+ | `LEVEL_MIN` determiner widened past `any/a/an/the` |
| "Prerequisites depend on the subject" | 4 | Same as the topics-course "varies" case |

PLAN went 25% → 81% parsed and EAS 23% → 3% unparsed off the back of those.
What is left is a genuine long tail: no remaining outlier group affects more
than 5 courses.

**Two real cycles exist**, and they are faithful to the catalogue: MA PH 351
lists MATH 337 as one of its alternatives and MATH 337 lists MA PH 351 as one
of its own. Neither is a deadlock — each is reachable by its other branch — so
26 PHYS/GEOPH/MATH courses reach that pair transitively and the engine's cycle
guard handles them. `verify_all.py` treats a **self**-reference as an error
(always a parse bug — it caught EAS 200 reading an equivalence statement as a
requirement) and a mutual cycle as a warning.

## Design decisions worth knowing

- **`external` means "not in this dataset", not "not CMPUT".** CMPUT 418 is
  referenced by CMPUT 411 and 428 but has no catalogue page; a subject-only
  rule would mark it tracked and then resolve to nothing.
- **Eligibility is three-valued: yes / no / cannot say.** An unreadable course
  has an empty prerequisite tree, and an empty tree walks as *satisfied* — so
  MATH 422 with an empty transcript originally reported `eligible: true` and
  rendered a green "you satisfy the prerequisites". Any course whose parse is
  `unparsed`, or whose tree is satisfied but known to be incomplete
  (`unrepresented_requirements`), now returns `eligible: null` and the UI says
  it cannot judge, with a link to the official catalogue entry. A credit
  conflict still outranks this and stays a definite no.
- **Credit exclusions are checked before eligibility.** If you already have
  MIS 419, asking about CMPUT 301 gets "you likely can't take this", not a
  tidy eligibility readout that ignores it.
- **Corequisites are never folded into the eligibility check.** "Take
  alongside" is a different claim from "must already be done".
- **Recursion is guarded** by a visited set and a depth cap. The test suite
  asserts no course in the shipped dataset trips either.
- **`LEVEL_MIN` uses `min_level` semantics** (≥ the stated level), per the
  schema in CLAUDE.md. Note that "any 300-level course" in the calendar
  arguably means *exactly* 300-level; the UI shows the constraint verbatim so a
  reader can judge.
- **Print export uses no PDF library.** A `@media print` stylesheet hides the
  chrome and renders an indented outline (graphs don't survive pagination), and
  `document.title` is swapped on `beforeprint` so the browser suggests
  `CMPUT415_Graph.pdf`. The filename derives from the same `course.code` that
  drives the page header, and `usePrintTitle.test.js` asserts both that two
  courses viewed back-to-back get different filenames and that the `useEffect`
  dependency array literally contains `code`.

## Scraper etiquette

One-time-per-term batch job: 1 second between requests, an identifying
User-Agent naming it as a student project (no browser spoofing), and on-disk
HTML caching so parser iteration never re-hits the site. Use `--limit` while
developing and `--refresh` only when you actually want fresh HTML.

## Phase status

- **Phase 1 — Data pipeline.** Done. Golden tests pass (57 assertions),
  15-course manual spot-check verified, parse-status breakdown reported above.
- **Phase 2 — Eval engine.** Done. 40 assertions, run against both fixtures and
  the real dataset.
- **Phase 3 — Frontend.** Done. Search, tree, and "what are my options",
  with an 18-assertion render test that mounts the real app.
- **Phase 4 — Export & polish.** Done. Print view, dynamic filename with its
  regression guard, XSS hygiene (no `dangerouslySetInnerHTML` anywhere),
  `npm audit` and `pip-audit` clean.
- **Phase 5 — Expand scope.** MATH added (1 of 31 Faculty of Science subjects).
  92 parser assertions and 27 render assertions pass; CMPUT's numbers are
  unchanged, so the generalization caused no regression. 15 MATH courses were
  spot-checked by hand against the calendar. Remaining subjects are mechanical
  by comparison — the reverse-direction, combined-field and spelled-out-subject
  handling that MATH forced is already in place, and BIOL/PHYS are where the
  reverse-direction sentences actually live.

### Verifying the whole dataset

Three layers, each answering a different question. All of them run over every
course, so "verified" means checked rather than sampled:

```bash
python parser/verify_all.py        # is the data self-consistent?
python parser/audit_coverage.py    # does each tree cover what its text names?
cd frontend && npm run verify      # does the engine behave on all of it?
```

`verify_all.py` checks schema shape, that `external` means "not in this
dataset", that no course is its own prerequisite or its own credit exclusion,
that `unparsed` never ships a tree, that `parsed` never hides a dropped
requirement, and that the graph has no cycles.

`npm run verify` is the behavioural one, and its central check is a round trip:
ask a course what you still need, mark exactly that complete, ask again — the
answer must flip to eligible. If it does not, the advice is not actionable: a
student could follow it exactly and still be turned away. That one property
exercises the AND/OR walk, chain expansion, LEVEL_MIN and external leaves on
every course at once, without anyone hand-writing an expected tree. It also
asserts the plan is listed in *walkable order* (deepest prerequisite first) and
that no unreadable course claims eligibility.

Current: 0 errors, 174 of 176 courses round-trip, the other 2 correctly
flagged as having incomplete trees.

### Auditing a subject

Golden tests only cover shapes you thought of. This catches the ones you
didn't, by comparing the set of course codes in each raw prerequisite sentence
against the set in its parsed tree:

```bash
python parser/audit_coverage.py
```

A code in the text but not the tree means a dropped requirement
(**under-constrained** -- the dangerous direction, since it tells a student
less is needed than really is). A code in the tree but not the text means one
was invented. Currently: **0 invented**, and 3 known drops, all deliberate
(MATH 421/422 refuse to guess; MATH 570 needs "a 400 or 500 level course on
Partial Differential Equations", which the schema cannot express and the notes
record instead).

This audit is what caught MATH 467 and MATH 556 after the golden tests were
already green.

### Adding the next subject

```bash
python scraper/scraper.py --subjects cmput math stat
python parser/test_parser.py          # must stay green -- catches regressions
python parser/build_courses.py        # read the PER-SUBJECT breakdown
python parser/spotcheck.py 265 --all  # eyeball the new subject's shapes
```

The per-subject report is the point: a new subject parsing badly is invisible
in the aggregate. Expect to add golden fixtures for whatever grammar the new
subject introduces — that is the actual work, not the scraping. Note that
validation gets weaker as you go, since you can falsify a wrong CMPUT tree from
memory and cannot do that for CHEM or BIOL.

Note that the LLM-assisted fallback pass described in CLAUDE.md's parser
section was **not needed** and is not implemented — the rule-based parser
covers everything except the two non-course requirements above, so there is no
long tail worth the added prompt-injection surface. If it is ever added, the
schema-validation constraints in CLAUDE.md's security section apply.

## Deploying

Netlify, Vercel, and GitHub Pages all work identically here — it is a static
bundle plus a JSON file, with no server-side piece, no environment variables,
and no secrets.

`netlify.toml` is committed and needs no dashboard configuration beyond
connecting the repo:

| Setting | Value |
|---|---|
| Base directory | `frontend` |
| Build command | `npm run build` |
| Publish directory | `frontend/dist` |
| Node version | 22 |

For Vercel, enter the same three values in the project settings. For GitHub
Pages, run `npm run build` and publish `frontend/dist` — `vite.config.js` sets
`base: './'`, so the bundle works from a repository subpath without changes.

**The build does not run the scraper, and must not.** `data/courses.json` is
committed precisely so deploys never touch `apps.ualberta.ca`; scraping on
every push would violate the etiquette rule this project set for itself. That
is also why `.gitignore` deliberately does *not* ignore the generated JSON —
a host builds from the git checkout, so ignoring it makes the build fail at
`npm run sync-data`.

Refreshing course data is therefore a deliberate local action, once a term:

```bash
python scraper/scraper.py --refresh    # re-fetch (ignores the HTML cache)
python parser/test_parser.py           # golden tests must pass first
python parser/build_courses.py         # regenerate courses.json + report
cd frontend && npm test                # engine + render tests against new data
git add data/ && git commit -m "Re-scrape catalogue for <term>"
```

Review the parse-status report before committing: if `parsed` drops or new
`unparsed` entries appear, the catalogue's wording changed and the parser needs
a look — that is exactly the signal the report exists to give you.
