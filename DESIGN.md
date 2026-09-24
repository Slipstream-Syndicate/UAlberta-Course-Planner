# CMPUT Prerequisite & Course Planning Explorer

## What this is

Originally scoped as a rebuild of an old resume project (a UAlberta final-exam scraper + calendar sync tool). Pivoted after realizing that project wasn't actually "scheduling" anything — exams are fixed by the registrar, so the old idea was really a lookup/aggregation tool wearing a scheduler's name. This project earns the name: it scrapes UAlberta's course catalogue, parses prerequisite requirements (which are genuinely boolean logic, not a simple chain), and lets a student ask "what are my options to get into course X" given what they've already completed.

Scope for v1: CMPUT (Computing Science) only. Extend to other subjects only after the scraper and parser are validated against CMPUT, since that's the department the builder can sanity-check by hand.

## Audience & access

No login, no accounts — this stays a fully public, freely accessible static page. That's also just what the architecture already gives you for free (no backend to hold sessions or gate anything behind), so it isn't a new decision so much as naming what's already true.

That openness is a real feature for a second audience beyond current students: this is genuinely useful to prospective students deciding on a CS degree at UofA before they've even applied, not just current students planning their next term. With zero completed courses entered, "what are my options" naturally degrades into "here's the full prereq chain for this course from scratch" — exactly what a prospective student wants, no extra engineering needed.

Be honest about the boundary that creates, though: a CMPUT-only prereq-chain tool answers "what do I need before course X," not "what does the whole CS degree require." It says nothing about breadth/elective requirements, non-CMPUT required courses (MATH, STAT, WRS, etc.), admission requirements, or overall program structure — all real inputs into "should I go to UofA for CS." Don't let the framing oversell it as a full degree planner; keep it presented as what it is, a CMPUT prerequisite explorer, one input among several a prospective student would need.

Because the audience now includes people who haven't talked to an advisor yet and are weighing a multi-year commitment, the "not official academic advising, verify with the calendar or an advisor" disclaimer (see Non-goals) should be visible in the UI itself, not a footnote — a bad parse matters more to someone forming expectations about enrolling than to a current student double-checking one registration.

Skip real accounts, but do use `localStorage` to remember a visitor's entered completed-courses list between visits on their own device — free, no backend, no personal data leaving the browser, and it's the one actual convenience a login would have bought.

## Data source

`https://apps.ualberta.ca/catalogue/course/cmput` — index of all CMPUT courses.
`https://apps.ualberta.ca/catalogue/course/cmput/<number>` — individual course page, e.g. `.../cmput/272`.

Confirmed fetchable with a plain HTTP request (unlike the old registrar exam pages, which 403 bot-style requests). Clean structured HTML: course title, credit value, description, and a "Prerequisites" field (sometimes also "Corequisites") as a single sentence of fairly consistent grammar.

Real examples pulled directly from the site, used to design the parser below:

- CMPUT 272: `"Prerequisites: CMPUT 101, 174, 175, 274, SCI 100, or ENCMP 100."` — flat OR list.
- CMPUT 301: `"Prerequisite: CMPUT 201 or CMPUT 275."` plus, separately in the description: `"Credit may be obtained in only one of CMPUT 301, BTM 419, or MIS 419."` — a mutual-exclusion / credit-restriction clause, NOT a prerequisite. Must be modeled separately or the graph is wrong.
- CMPUT 415: `"Prerequisites: one of CMPUT 229, E E 380, or ECE 212, and any 300-level Computing Science course."` — real AND-of-OR, plus a wildcard category constraint (`any 300-level Computing Science course`) that names no specific course, and a subject code with a space in it (`E E 380`) that will break a naive "no whitespace in course codes" regex.

Expect more edge cases once you scrape the full CMPUT list: minimum-grade requirements ("minimum grade of C+"), "or equivalent," "permission of the instructor," and courses with no prerequisites at all. Don't try to handle all of these perfectly in v1 — see parser section.

Checked the index page (`.../catalogue/course/cmput`) directly: it's a single static page, no pagination, no JS rendering required — roughly 90+ entries from CMPUT 101 through the 400s, including topics-course variants like 296A/296B. One real quirk to build for from day one: the catalogue lists some courses more than once with an `Effective: <date>` marker — an old and an incoming version of the same course code during a curriculum transition. A naive scrape will produce duplicate entries with possibly different prerequisite text for the same course code. Dedupe by course code and keep the currently-in-effect version (effective date ≤ today), not whichever one happens to appear first in the HTML — silently picking the wrong one means shipping a prereq tree that's about to be (or already is) wrong.

A course with no Prerequisites field at all is a distinct case from a course whose field exists but says "None" — treat both as an empty tree (no prerequisites), but don't let a missing-field case crash or fall through to `unparsed` by accident; the scraper should record "field absent" explicitly rather than the parser having to guess why a field is empty.

## Architecture

```
scraper/   Python + requests + BeautifulSoup
           -> hits the CMPUT index, then every course page
           -> extracts raw title, credits, description, prerequisite text,
              corequisite text, credit-exclusion text (faithfully, no parsing yet)
           -> writes data/courses_raw.json

parser/    Python, runs offline as part of the same ETL step
           -> turns raw prerequisite text into a structured boolean tree per course
           -> writes data/courses.json (see schema below)
           -> this is the hard, interesting part of the project — budget most of your time here

Scraper etiquette: this is a one-time-per-term batch job against a small (~90-course)
index, not a live service — add a short delay between requests (a second or so is
plenty), set a real identifying User-Agent (e.g. naming it as a student project, not
spoofing a browser), and don't re-run it more than you need to during development —
cache the raw HTML to disk locally instead of re-fetching on every parser iteration.

frontend/  React + TailwindCSS, no backend
           -> loads data/courses.json directly (small dataset, ~150 CMPUT courses)
           -> search by course code
           -> visual prerequisite tree for a course
           -> "what are my options": input completed courses + a target course,
              get back which prereq branches are satisfied and what combinations
              of remaining courses would unlock it, evaluated entirely client-side
```

No backend needed for v1 — this sidesteps the OAuth/secrets/hosting complexity the old calendar-sync idea had. If the dataset grows (multi-faculty) past what's comfortable to ship as a static JSON blob, revisit with a real DB then, not preemptively.

Deployment: static site host — Netlify, Vercel, or GitHub Pages all work identically well here since it's just the built React app plus a JSON file, no server-side piece at all.

## Data model (courses.json)

Each course record should carry, at minimum: course code, title, credits, raw prerequisite text (always keep this, even once parsed — it's the fallback), raw corequisite text, parsed prerequisite tree, parsed corequisite list, credit-exclusion list (courses that can't be double-counted, kept separate from prerequisites), and a `parse_status` of `parsed | partial | unparsed` so the frontend can show a confidence flag instead of silently trusting a parse that might be wrong.

Prerequisite tree node types: `COURSE` (a specific course code reference), `AND` (all children required), `OR` (any one child required), and `LEVEL_MIN` (a wildcard category constraint like "any 300-level Computing Science course" — store as subject + minimum level, not a course list).

Concrete shape, worked from the real CMPUT 415 text (`"one of CMPUT 229, E E 380, or ECE 212, and any 300-level Computing Science course"`):

```json
{
  "type": "AND",
  "children": [
    {
      "type": "OR",
      "children": [
        { "type": "COURSE", "code": "CMPUT 229", "external": false },
        { "type": "COURSE", "code": "E E 380", "external": true },
        { "type": "COURSE", "code": "ECE 212", "external": true }
      ]
    },
    { "type": "LEVEL_MIN", "subject": "CMPUT", "min_level": 300 }
  ]
}
```

`external: true` marks a course outside the scraped CMPUT dataset (see cross-subject references below) — the frontend uses this flag directly to decide whether to show "tracked" or "verify yourself" styling, no separate lookup needed.

### Cross-subject references (real gap, don't skip this)

CMPUT-only scope means the scraper only visits CMPUT pages — but CMPUT prerequisites constantly reference other subjects: MATH, STAT, SCI, ENCMP, E E, ECE, PHIL, and others (see the CMPUT 272 and 415 examples above). None of those courses are in the scraped dataset, so a naive implementation will produce `COURSE` nodes that point at nothing.

Handle this explicitly: a `COURSE` node whose subject isn't CMPUT is an "external" leaf — store it as a plain code (e.g. `MATH 125`) with no expansion, and let the eligibility check treat it exactly like a CMPUT course the student self-reports as completed or not (same self-report mechanism, no special case needed in the eval engine). Don't try to recurse into an external course's own prerequisites — that data was never scraped, and pretending otherwise would silently produce wrong "you need X before Y" chains for courses outside the dataset. The UI should visually distinguish external references (e.g., "not tracked in this dataset, verify eligibility yourself") from CMPUT courses the tool actually reasoned about.

## Parser design

Grammar is repetitive enough to handle with a rule-based tokenizer/recursive-descent parser rather than jumping straight to an LLM: `"and"` / semicolons generally separate AND-joined clauses, `"one of X, Y, or Z"` / a trailing-or comma list is an OR clause within it. Match course codes with a regex that tolerates a space in the subject code (`E E 380`, not just `CMPUT 272`). Match the `"any N00-level <subject> course"` pattern separately and emit a `LEVEL_MIN` node instead of trying to force it into a course reference. Strip and store `"Credit may be obtained in only one of..."` clauses as `credit_exclusions`, not as prerequisites.

Don't aim for 100% rule-based coverage. For whatever the parser can't confidently handle, mark it `unparsed` or `partial`, keep the raw text visible in the UI, and optionally run an LLM-assisted second pass on just that long tail to extract structured JSON — cheap at ~150 courses, and a reasonable fallback as long as it's clearly flagged as lower-confidence rather than presented with the same certainty as the rule-based output.

Watch for negation specifically — it's the parser bug most likely to silently corrupt the graph rather than fail loudly. Catalogue text sometimes names a course in a *negative* context ("not open to students with credit in CMPUT 275", antirequisite-style phrasing similar to the credit-exclusion clauses already called out above). A regex that just scans for course-code patterns anywhere in the sentence, blind to nearby "not"/"without"/"excluding", will happily emit a false `COURSE` prerequisite node for a course that's actually being excluded, not required. Treat any course mention within a negation window as a credit-exclusion candidate, never as a prerequisite, and add a test case for it (see below).

Validate the parser against CMPUT specifically because the builder already knows these prereq chains firsthand — spot-check parsed output against actual memory of what's required for courses already taken, don't just trust that it ran without erroring. Beyond spot-checking, keep a small golden test set: hardcode the raw text -> expected-tree pairs already gathered here (CMPUT 272's flat OR, CMPUT 301's OR-plus-credit-exclusion, CMPUT 415's AND-of-OR-plus-LEVEL_MIN) as fixtures the parser must pass, and add to it every time a new edge case turns up in the full scrape. Re-run this fixture set after any regex change — it's the difference between "I tweaked the parser" and "I tweaked the parser and silently broke five other courses."

## Boolean-eval engine ("what are my options")

Runs client-side in the frontend, not the backend (there is no backend). Input: a target course code, and a list of course codes the student has already completed. Walk the target course's prerequisite tree: for each `OR` node, check if any child is already satisfied; for each `AND` node, all children must resolve; for `LEVEL_MIN` nodes, check completed courses against the subject+level constraint. Recurse into unsatisfied `COURSE` nodes to show the deeper chain (e.g., if CMPUT 301 isn't reachable yet, show what's needed to unlock CMPUT 201 or CMPUT 275, whichever path is shorter). Output should show, per unsatisfied branch, the concrete remaining course(s) needed — that's the actual "options" feature.

Before showing a target course's requirements at all, check its `credit_exclusions` against the student's completed list — if they've already completed something on that list (e.g. already have MIS 419 and are asking about CMPUT 301), tell them outright they likely can't take it rather than running the eligibility check as if it were a normal open course. The data's already being collected for this; it's wasted if the eval engine doesn't use it.

Corequisites are not prerequisites and shouldn't be folded into the same AND/OR eligibility check — a corequisite means "must be taken in the same term," not "must already be completed." Surface them as a separate "take alongside" note on the target course, evaluated independently of whether the prerequisite tree is satisfied.

Guard the recursion with a depth limit or a visited-set cycle check. Real UAlberta prerequisites shouldn't cycle, but a parser bug (especially around the negation cases above) could produce a course that appears to require itself or a chain that loops — fail loudly with a flagged error on that course rather than hanging the browser in infinite recursion.

## Export / printable view

Worth having, and it pairs naturally with the "verify with an advisor" disclaimer — a student showing up to an advising meeting with a printed prereq chain for the course they're asking about is a real use case. Don't build this with a PDF-generation library, though. Build a dedicated print-friendly view (a `@media print` stylesheet that hides the app chrome — search box, nav, buttons — and shows only the tree) and let the browser's native print-to-PDF do the actual export. Zero new dependencies, same result a custom "download PDF" button would give.

Render the printable version as an indented text outline (course code + title, nested under what it requires), not the interactive node-and-edge graph — graphs don't survive pagination (crossing lines, nodes cut off at page breaks), outlines do. Keep the graph for the on-screen exploring experience; make the export path text-first.

Whatever gets exported has to carry the same honesty the live page shows: if a course's tree is `partial` or `unparsed`, that flag and the raw prerequisite text need to be in the printout too, not just on-screen — once it's a piece of paper, the reader's lost the easy "can I trust this?" check they'd get glancing at the live app. Same for the "not official academic advising" line from Non-goals — it needs to print, not just render.

Filename: `<SUBJECT><NUMBER>_Graph.pdf` for whichever course is currently being viewed — `CMPUT229_Graph.pdf` was just the worked example, not a fixed string to reuse for every course. There's no file-system API from a print dialog, so the mechanism is the standard trick: browsers suggest a "Save as PDF" filename based on `document.title` at print time. Derive that title from the exact same `course.code` value already driving the on-page header — one source of truth, computed as `course.code.replace(/\s+/g, '') + "_Graph"` — never a separate hardcoded string, or the two will drift out of sync the first time someone edits one and not the other.

The bug to specifically guard against, since this is a React SPA: navigating from one course to another via client-side routing does *not* re-run title-setting code on its own the way a full page load would. If the `document.title` assignment lives in a `useEffect` with no dependency array (or one that doesn't include `course.code`), it'll fire once for whichever course was mounted first and then silently stay stuck on that value — e.g. genuinely producing `CMPUT229_Graph.pdf` for every course afterward, which is exactly the failure mode to test for. Make `course.code` an explicit dependency so the effect re-runs on every course change, and write a test/manual check that specifically views two different courses back-to-back and confirms the print title updates both times, not just once on first load. Restore `document.title` to the app's normal per-course title (itself already dynamic, not a generic constant) on the `afterprint` event. This is well-supported in Chrome/Edge and generally respected by Firefox — solid default, not a hard guarantee on every browser, since it's implementation behavior rather than a formal spec.

Build this after the core tree visualization works, not before — there's nothing worth printing until then.

## Build phases

Build this in phases, not one continuous push. The reasoning is already implicit everywhere else in this file: the parser is the one thing everything downstream depends on, and it's also the piece most likely to be subtly wrong on a first pass — that's the whole reason for the negation handling, the cross-subject leaf rule, and the golden test set. If the eval engine, UI, and export polish all get built on top of an unvalidated parser, every parser fix later ripples through code that was written against wrong assumptions. Phasing puts a checkpoint before that can compound, not after.

**Phase 1 — Data pipeline.** Scraper → `courses_raw.json` → parser → `courses.json`. Don't move on when it "runs without erroring" — the exit criterion is the golden test set passing *and* a manual spot-check against ~15 real CMPUT courses, including several the builder has actually taken, *and* a reported `parse_status` breakdown (what % came out `parsed` vs `partial` vs `unparsed`) so the real accuracy is known, not assumed. Nothing else should start until this holds.

**Phase 2 — Eval engine.** Pure logic, no UI needed — testable directly against `courses.json` with a script or a handful of unit tests. Covers the boolean walk, the credit-exclusion check, corequisite separation, cross-subject external-leaf handling, and the cycle/depth guard. Exit criterion: the known test cases already named in this file pass (CMPUT 301 reachable via 201 or 275, a credit-exclusion correctly blocking eligibility, a `LEVEL_MIN` node evaluating correctly against a few different completed-course lists).

**Phase 3 — Frontend.** Two pieces here don't have to be strictly sequential: search plus read-only tree display only depend on Phase 1's data and can be built in parallel with Phase 2's eval engine. The "what are my options" input specifically depends on Phase 2 being done, since it's just a UI wrapped around that logic. Exit criterion: a cold read — you, or ideally someone else, searching a course and getting a correct, readable answer without needing to cross-check the raw JSON to trust it.

**Phase 4 — Export & polish.** Print-friendly view, dynamic filename, and the Security considerations items (schema-validating the LLM fallback if it's used, XSS hygiene on rendered fields). Genuinely optional for a first working version — nothing in Phases 1-3 depends on it, so it's fine to ship without this and add it later if time's tight.

**Phase 5 — Expand scope.** Generalize the scraper and parser to other subjects, re-validating accuracy against the new corpus rather than assuming it transfers cleanly (other departments may phrase prerequisites differently). Hard-gated behind Phases 1-3 being solid on CMPUT specifically — stated elsewhere in this file already, repeated here because it's the phase most tempting to start early once CMPUT feels "done enough."

## Dev conventions

`data/courses.json` and `data/courses_raw.json` are generated — never hand-edit them. On every re-scrape, regenerate both fully from scratch and re-run the parser over the whole set rather than patching individual entries; the catalogue's wording can change between terms, and a stale `parsed` status from a previous run could mask a change that now needs re-parsing. Python scraper/parser code lives in its own venv (`pip install -r requirements.txt`). Run the golden parser test set before trusting a fresh scrape's output.

## Security considerations

Given the architecture — static frontend, no backend, no login, no live LLM in the request path (the eval engine is deterministic JS, not a model call) — most of the standard web-app threat model doesn't have a surface here yet. Worth being precise about where it actually does apply instead of bolting on a generic checklist that doesn't fit a static site with nothing to log into and no server to breach.

**Prompt injection.** The only place an LLM touches this pipeline is the offline fallback for prereq text the regex parser can't confidently handle (see Parser design). That's the real injection surface: scraped course text is external, not-fully-trusted input being handed to a model. Mitigate it structurally rather than by trying to filter every possible injection phrase — constrain the call to return only schema-validated JSON matching the fixed node types (`COURSE`/`AND`/`OR`/`LEVEL_MIN`) and a whitelist-shaped course-code pattern, reject or flag anything that doesn't validate against that schema instead of accepting it as-is, and never let the model's output be treated as anything other than data — it never becomes a prompt, a config value, or code that executes. Keep those entries tagged `parse_status: partial` with visibly lower confidence in the UI, same as any other uncertain parse. If a future version adds a chat-style "ask about your prereqs" feature that takes free-text user input into an LLM, that's a materially bigger injection surface than this one and needs its own review at that point — nothing in v1's scope does that.

**Rendering scraped content.** Course titles/descriptions come from an external site and get rendered in React. React escapes text by default, which is enough as long as nothing uses `dangerouslySetInnerHTML` on scraped fields — don't introduce that shortcut for formatting; if a description ever needs rich text, sanitize it explicitly (e.g. DOMPurify) rather than trusting it.

**Scraper hygiene.** Treat scraped HTML as text to extract, never as something to execute — no `eval`, no dynamically constructed commands built from scraped strings. Moot for this project's v1 since there's no database, but worth stating as a habit now, before the Job Application Tracker project (which does have one).

**Dependency hygiene.** Run `npm audit` / `pip-audit` occasionally — a static hobby site's most realistic risk is an outdated JS dependency with a known CVE, not a targeted attack, so this ordinary, boring practice matters more here than anything exotic.

**What's explicitly not a concern for v1, and why.** No auth to compromise (no login), no server secrets to leak (no backend, no API keys), no user-submitted content stored or shown to other users (the completed-courses list is local input only, never sent anywhere). That changes the moment this gets a real backend — the multi-faculty version, or if "my options" ever becomes account-based — so don't assume today's low-risk profile carries forward automatically once that happens.

## Non-goals for v1

No backend, no login, no integration with a student's actual transcript — completed courses are entered manually. No enforcement of minimum-grade or "permission of instructor" clauses in the boolean logic; store them as informational flags on the course record and surface them in the UI, don't try to model them as graph constraints yet. No multi-faculty support until CMPUT is validated.

Term availability (which semesters a course actually runs) isn't captured in v1's schema at all — "options" tells a student what's *prerequisite-eligible*, not what's actually offered next term. Worth flagging in the UI (e.g. "check the course listing for term availability") so this doesn't get mistaken for a full registration planner. This tool is not official academic advising — parsing errors or stale scrapes are possible, and a wrong answer here could steer someone into a bad registration decision, so the UI should say plainly that it's a planning aid, not a substitute for checking the calendar or talking to an advisor before actually registering.
