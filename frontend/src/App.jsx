import { useCallback, useEffect, useMemo, useState } from 'react';

import PrereqTree from './components/PrereqTree.jsx';
import CoreqLine from './components/CoreqLine.jsx';
import PrintOutline from './components/PrintOutline.jsx';
import {
  buildIndex,
  evaluateCourse,
  describeRequirement,
  parseCourseList,
} from './lib/evalEngine.js';
import { loadCompleted, saveCompleted } from './lib/storage.js';
import { usePrintTitle } from './lib/usePrintTitle.js';
import { safeHref, codeFromHash, hashForCode } from './lib/links.js';

const STATUS_BADGE = {
  parsed: { text: 'parsed', className: 'bg-emerald-100 text-emerald-900 border-emerald-300' },
  partial: { text: 'partial parse', className: 'bg-amber-100 text-amber-900 border-amber-300' },
  unparsed: { text: 'not machine-readable', className: 'bg-rose-100 text-rose-900 border-rose-300' },
};
// An unexpected status in the data must not white-screen the page.
const UNKNOWN_BADGE = { text: 'unknown confidence', className: 'bg-slate-100 text-slate-800 border-slate-300' };

const SEARCH_LIMIT = 40;

/**
 * DESIGN.md makes this disclaimer a UI element rather than a footnote on
 * purpose: the audience includes prospective students weighing a multi-year
 * decision, for whom a bad parse matters more than it does to someone
 * double-checking one registration.
 */
function Disclaimer() {
  return (
    <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <p>
        <strong>This is a planning aid, not official academic advising.</strong> It reads
        the UAlberta course catalogue automatically, so parsing errors and stale data are
        possible. It covers <em>prerequisites only</em>, for the subjects listed above —
        not breadth or elective requirements, courses in subjects it does not track,
        admission requirements, or overall degree structure, and not which term a course
        actually runs. Check the official calendar and talk to an advisor before you
        register.
      </p>
    </div>
  );
}

function CompletedCourses({ completed, setCompleted, index }) {
  const [draft, setDraft] = useState('');
  const [rejected, setRejected] = useState([]);

  // The placeholder invites "CMPUT 201, MATH 125", so a list is split into
  // separate codes, "cmput201" is canonicalised to "CMPUT 201", and anything
  // that is not course-shaped is shown back rather than stored.
  const add = (raw) => {
    const { codes, invalid } = parseCourseList(raw);
    const fresh = codes.filter((c) => !completed.includes(c));
    if (fresh.length) setCompleted([...completed, ...fresh]);
    setRejected(invalid);
    // Keep what could not be read in the box so it can be corrected.
    setDraft(invalid.join(', '));
  };

  const unknown = completed.filter((c) => !index.has(c));

  return (
    <section className="no-print rounded-lg border border-slate-200 bg-white p-4">
      <h2 className="font-semibold text-slate-900">Courses you have completed</h2>
      <p className="mt-1 text-sm text-slate-600">
        Entered by hand and stored only in this browser — nothing is sent anywhere. Leave
        it empty to see a course&rsquo;s full prerequisite chain from scratch.
      </p>

      <form
        className="mt-3 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          add(draft);
        }}
      >
        <input
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="e.g. CMPUT 201, MATH 125"
          aria-label="Add a completed course"
          className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
        />
        <button
          type="submit"
          className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700"
        >
          Add
        </button>
      </form>

      {rejected.length > 0 && (
        <p role="alert" className="mt-2 text-xs text-rose-800">
          Not a course code, so not added: {rejected.join(', ')}. Use the form
          &ldquo;CMPUT 201&rdquo;.
        </p>
      )}

      {completed.length > 0 && (
        <ul className="mt-3 flex flex-wrap gap-2">
          {completed.map((code) => (
            <li key={code}>
              <button
                type="button"
                onClick={() => setCompleted(completed.filter((c) => c !== code))}
                className="inline-flex items-center gap-2 rounded-md border border-slate-300 bg-slate-50 px-2 py-1 text-sm hover:border-rose-300 hover:bg-rose-50"
                title={'Remove ' + code}
              >
                {code}
                <span aria-hidden="true" className="text-slate-400">
                  ×
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}

      {unknown.length > 0 && (
        <p className="mt-3 text-xs text-amber-800">
          Not in this dataset (still counted if a prerequisite names them, but their own
          prerequisites are unknown here): {unknown.join(', ')}
        </p>
      )}

      {completed.length > 0 && (
        <button
          type="button"
          onClick={() => setCompleted([])}
          className="mt-3 text-xs text-slate-500 underline hover:text-slate-800"
        >
          Clear all
        </button>
      )}
    </section>
  );
}

/**
 * Shown whenever the tree cannot be trusted to be the whole story.
 *
 * The point is to stop promising. A course like MATH 422 ("either (1) ... or
 * (2) ... or (3) ...") or MATH 570 ("a 400 or 500 level course on Partial
 * Differential Equations") has real requirements this schema cannot express.
 * Rendering a confident-looking tree, or an empty one, invites the reader to
 * believe it is complete. So we say plainly what is missing and hand them the
 * official page to read themselves.
 *
 * Two distinct cases, because they are not equally bad:
 *   unparsed  -- there is no tree at all
 *   partial with unrepresented_requirements -- the tree is real but incomplete
 * A `partial` that dropped only "or consent of the Department" is neither, and
 * gets no banner: crying wolf on every course would train people to ignore it.
 */
function CatalogueFallback({ course, parseStatus }) {
  const missing = course.unrepresented_requirements || [];
  const isUnparsed = parseStatus === 'unparsed';
  if (!isUnparsed && missing.length === 0) return null;

  return (
    <div className="rounded-lg border-2 border-amber-400 bg-amber-50 p-4">
      <h3 className="font-semibold text-amber-900">
        {isUnparsed
          ? 'This course’s prerequisites could not be read automatically'
          : 'Part of this course’s requirements are not shown below'}
      </h3>
      <p className="mt-1 text-sm text-amber-900">
        {isUnparsed
          ? 'No prerequisite tree is shown for this course, and the "what you still need" answer would be incomplete. This is a limitation of this tool, not a sign the course has no prerequisites.'
          : 'The tree below is correct as far as it goes, but at least one requirement could not be represented, so treat it as a partial picture.'}
      </p>

      {missing.length > 0 && (
        <div className="mt-2 text-sm text-amber-900">
          <span className="font-medium">Not represented:</span>
          <ul className="mt-1 list-disc pl-5">
            {missing.map((m, i) => (
              <li key={i}>&ldquo;{m}&rdquo;</li>
            ))}
          </ul>
        </div>
      )}

      {safeHref(course.source_url) && (
        <p className="mt-3 text-sm">
          <a
            className="font-medium text-amber-900 underline underline-offset-2"
            href={safeHref(course.source_url)}
            target="_blank"
            rel="noreferrer noopener"
          >
            Read {course.code} in the official UAlberta catalogue →
          </a>
        </p>
      )}
    </div>
  );
}

function OptionsPanel({ result }) {
  const { eligible, blocked, conflicts, alreadyCompleted, remaining, prerequisite, course } = result;

  if (blocked) {
    return (
      <div className="rounded-lg border border-rose-300 bg-rose-50 p-4">
        <h3 className="font-semibold text-rose-900">You likely cannot take {course.code}</h3>
        <p className="mt-1 text-sm text-rose-900">
          You reported completing <strong>{conflicts.join(', ')}</strong>. The calendar says
          credit cannot be obtained for both, so the eligibility check below is moot —
          confirm with an advisor.
        </p>
      </div>
    );
  }

  if (alreadyCompleted) {
    return (
      <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-4 text-sm text-emerald-900">
        You have already marked {course.code} as completed.
      </div>
    );
  }

  // Three-valued on purpose: `null` means the tool cannot answer, which must
  // never be rendered as the green "you're good to go" panel.
  if (result.eligibilityUnknown) {
    return (
      <div className="rounded-lg border border-slate-300 bg-white p-4">
        <h3 className="font-semibold text-slate-900">
          This tool cannot tell you whether you are eligible
        </h3>
        <p className="mt-1 text-sm text-slate-700">
          {course.code}&rsquo;s requirements could not be fully read from the calendar,
          so any &ldquo;you qualify&rdquo; answer here would be a guess. Read the official
          entry above and check with an advisor.
        </p>
      </div>
    );
  }

  if (eligible) {
    return (
      <div className="rounded-lg border border-emerald-300 bg-emerald-50 p-4">
        <h3 className="font-semibold text-emerald-900">
          Your completed courses satisfy the prerequisites
        </h3>
        <p className="mt-1 text-sm text-emerald-900">
          Check term availability in the course listing before you plan around it.
        </p>
      </div>
    );
  }

  const alternatives = (prerequisite && prerequisite.alternatives) || [];

  return (
    <div className="rounded-lg border border-slate-300 bg-white p-4">
      <h3 className="font-semibold text-slate-900">What you still need</h3>

      {remaining.length === 0 ? (
        <p className="mt-1 text-sm text-slate-600">
          Nothing concrete to list — see the calendar text above; this course&rsquo;s
          requirements are not fully machine-readable.
        </p>
      ) : (
        <>
          <p className="mt-1 text-sm text-slate-600">Shortest remaining path:</p>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {remaining.map((r, i) => (
              <li key={i}>{describeRequirement(r)}</li>
            ))}
          </ul>
        </>
      )}

      {alternatives.length > 1 && (
        <div className="mt-4">
          <p className="text-sm font-medium text-slate-800">
            Every route that works (any one of these):
          </p>
          <ul className="mt-2 space-y-1 text-sm text-slate-700">
            {alternatives.map((alt, i) => (
              <li key={i} className="rounded border border-slate-200 bg-slate-50 px-2 py-1">
                {alt.map(describeRequirement).join(' + ')}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

export default function App() {
  const [data, setData] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [query, setQuery] = useState('');
  const [subjectFilter, setSubjectFilter] = useState('');
  // The viewed course lives in the URL hash, so a link or a refresh lands on
  // the same course and the back button steps through what was viewed.
  const [selected, setSelected] = useState(() => codeFromHash(window.location.hash));
  const [completed, setCompleted] = useState(loadCompleted);

  const selectCourse = useCallback((code) => {
    setSelected(code);
    const hash = hashForCode(code);
    if (window.location.hash !== hash) {
      window.history.pushState(null, '', hash || window.location.pathname);
    }
  }, []);

  useEffect(() => {
    const onNavigate = () => setSelected(codeFromHash(window.location.hash));
    window.addEventListener('popstate', onNavigate);
    window.addEventListener('hashchange', onNavigate);
    return () => {
      window.removeEventListener('popstate', onNavigate);
      window.removeEventListener('hashchange', onNavigate);
    };
  }, []);

  useEffect(() => {
    fetch('courses.json')
      .then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(setData)
      .catch((e) => setLoadError(String(e)));
  }, []);

  useEffect(() => {
    saveCompleted(completed);
  }, [completed]);

  const courses = useMemo(() => (data ? data.courses : []), [data]);
  // Built once per dataset and shared with the engine, so changing the
  // completed list does not rebuild a 1,277-entry index on every edit. Keys
  // are normalised the same way the engine normalises its lookups.
  const index = useMemo(() => buildIndex(courses), [courses]);
  const subjects = useMemo(
    () => [...new Set(courses.map((c) => c.subject))].sort(),
    [courses]
  );

  const { matches, totalMatches } = useMemo(() => {
    const q = query.trim().toLowerCase();
    // "cmput301" should find "CMPUT 301" too.
    const qCompact = q.replace(/\s+/g, '');
    const pool = subjectFilter ? courses.filter((c) => c.subject === subjectFilter) : courses;
    const hits = q
      ? pool.filter(
        (c) =>
          c.code.toLowerCase().includes(q) ||
            c.code.toLowerCase().replace(/\s+/g, '').includes(qCompact) ||
            (c.title || '').toLowerCase().includes(q)
      )
      : pool;
    return { matches: hits.slice(0, SEARCH_LIMIT), totalMatches: hits.length };
  }, [courses, query, subjectFilter]);

  const result = useMemo(
    () => (selected && index.size ? evaluateCourse(index, selected, completed) : null),
    [index, selected, completed]
  );

  // `selected` is the single source of truth for both the on-screen heading and
  // the print filename -- see usePrintTitle for why that matters here.
  usePrintTitle(result && result.found ? result.course.code : null);

  if (loadError) {
    return (
      <main className="mx-auto max-w-3xl p-6">
        <h1 className="text-xl font-bold">Could not load course data</h1>
        <p className="mt-2 text-sm text-slate-700">
          {loadError}. Run <code>python parser/build_courses.py</code>, then{' '}
          <code>npm run sync-data</code>.
        </p>
      </main>
    );
  }

  if (!data) {
    return <main className="mx-auto max-w-3xl p-6 text-slate-600">Loading course data…</main>;
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-6 print-page">
      <header className="no-print">
        <h1 className="text-2xl font-bold tracking-tight">UAlberta Prerequisite Explorer</h1>
        <p className="mt-1 text-sm text-slate-600">
          {data.course_count} University of Alberta courses ({subjects.join(', ')}), scraped from{' '}
          <a
            className="underline"
            href={safeHref(data.source)}
            target="_blank"
            rel="noreferrer noopener"
          >
            the course catalogue
          </a>
          . Search a course to see what it requires and what you still need.
        </p>
      </header>

      <div className="no-print mt-4">
        <Disclaimer />
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[320px_1fr]">
        <div className="no-print space-y-6">
          <CompletedCourses completed={completed} setCompleted={setCompleted} index={index} />

          <section className="rounded-lg border border-slate-200 bg-white p-4">
            <h2 className="font-semibold">Find a course</h2>
            {/* A row of chips reads well for a handful of subjects and becomes
                a wall at Faculty scale (31 of them), so past a threshold the
                same filter becomes a select. */}
            {subjects.length > 1 && subjects.length <= 8 && (
              <div className="mt-2 flex flex-wrap gap-1">
                {['', ...subjects].map((s) => (
                  <button
                    key={s || 'all'}
                    type="button"
                    onClick={() => setSubjectFilter(s)}
                    className={
                      'rounded-md border px-2 py-1 text-xs font-medium ' +
                      (subjectFilter === s
                        ? 'border-slate-900 bg-slate-900 text-white'
                        : 'border-slate-300 bg-white text-slate-700 hover:bg-slate-100')
                    }
                  >
                    {s || 'All'}
                  </button>
                ))}
              </div>
            )}
            {subjects.length > 8 && (
              <select
                value={subjectFilter}
                onChange={(e) => setSubjectFilter(e.target.value)}
                aria-label="Filter by subject"
                className="mt-2 w-full rounded-md border border-slate-300 px-2 py-2 text-sm focus:border-blue-500 focus:outline-none"
              >
                <option value="">All {subjects.length} subjects</option>
                {subjects.map((s) => (
                  <option key={s} value={s}>
                    {s}
                  </option>
                ))}
              </select>
            )}
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search by code or title"
              aria-label="Search courses"
              className="mt-2 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
            <ul className="mt-3 max-h-96 space-y-1 overflow-y-auto">
              {matches.map((c) => (
                <li key={c.code}>
                  <button
                    type="button"
                    onClick={() => selectCourse(c.code)}
                    className={
                      'w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-slate-100 ' +
                      (selected === c.code ? 'bg-slate-900 text-white hover:bg-slate-900' : '')
                    }
                  >
                    <span className="font-medium">{c.code}</span>{' '}
                    <span className={selected === c.code ? 'text-slate-200' : 'text-slate-600'}>
                      {c.title}
                    </span>
                  </button>
                </li>
              ))}
              {matches.length === 0 && (
                <li className="px-2 py-1 text-sm text-slate-500">No matching course.</li>
              )}
            </ul>
            {totalMatches > matches.length && (
              <p className="mt-2 text-xs text-slate-500">
                Showing {matches.length} of {totalMatches} — type more of a code or
                title, or pick a subject, to narrow the list.
              </p>
            )}
          </section>
        </div>

        <main>
          {!result && (
            <p className="no-print rounded-lg border border-dashed border-slate-300 bg-white p-8 text-center text-slate-600">
              Pick a course to see its prerequisite tree.
            </p>
          )}

          {result && !result.found && (
            <p className="no-print rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm">
              {result.error}
            </p>
          )}

          {result && result.found && (
            <>
              <article className="no-print space-y-4">
                <div className="rounded-lg border border-slate-200 bg-white p-4">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="text-xl font-bold">
                        {result.course.code} — {result.course.title}
                      </h2>
                      <p className="mt-1 text-sm text-slate-600">
                        {result.course.credits_text}
                        {result.course.effective_term ? ' · ' + result.course.effective_term : ''}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => window.print()}
                      className="rounded-md border border-slate-300 px-3 py-1.5 text-sm hover:bg-slate-100"
                    >
                      Print / save as PDF
                    </button>
                  </div>

                  {result.course.description && (
                    <p className="mt-3 text-sm text-slate-700">{result.course.description}</p>
                  )}

                  <div className="mt-3 flex flex-wrap items-center gap-2">
                    <span
                      className={
                        'rounded border px-2 py-0.5 text-xs font-medium ' +
                        (STATUS_BADGE[result.parseStatus] || UNKNOWN_BADGE).className
                      }
                    >
                      {(STATUS_BADGE[result.parseStatus] || UNKNOWN_BADGE).text}
                    </span>
                    {safeHref(result.course.source_url) && (
                      <a
                        className="text-xs text-slate-500 underline"
                        href={safeHref(result.course.source_url)}
                        target="_blank"
                        rel="noreferrer noopener"
                      >
                        official catalogue entry
                      </a>
                    )}
                  </div>

                  {/* The raw text stays visible always -- it is the fallback
                      whenever the parse is anything less than clean. */}
                  <p className="mt-3 rounded border border-slate-200 bg-slate-50 p-2 text-sm text-slate-700">
                    <span className="font-medium">Calendar text: </span>
                    {result.prerequisitesText || 'No prerequisite listed.'}
                  </p>

                  {result.notes.length > 0 && (
                    <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-amber-800">
                      {result.notes.map((n, i) => (
                        <li key={i}>{n}</li>
                      ))}
                    </ul>
                  )}
                </div>

                <CatalogueFallback course={result.course} parseStatus={result.parseStatus} />

                <OptionsPanel result={result} />

                {result.errors.length > 0 && (
                  <div className="rounded-lg border border-rose-300 bg-rose-50 p-4 text-sm text-rose-900">
                    {result.errors.map((e, i) => (
                      <p key={i}>{e}</p>
                    ))}
                  </div>
                )}

                {/* Loops are real catalogue data (MA PH 351 and MATH 337 list
                    each other as alternatives), so they are explained in a
                    neutral note -- never shown as a red parse error. */}
                {result.cycles.length > 0 && (
                  <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-600">
                    {result.cycles.map((e, i) => (
                      <p key={i}>{e}</p>
                    ))}
                  </div>
                )}

                <section className="rounded-lg border border-slate-200 bg-white p-4">
                  <h3 className="mb-3 font-semibold">Prerequisite tree</h3>
                  <PrereqTree
                    node={result.prerequisite}
                    onSelect={selectCourse}
                    unparsed={result.parseStatus === 'unparsed'}
                  />
                </section>

                {result.corequisite && (
                  <section className="rounded-lg border border-blue-200 bg-blue-50 p-4">
                    <h3 className="mb-1 font-semibold text-blue-900">
                      Take alongside (corequisite)
                    </h3>
                    <p className="mb-3 text-sm text-blue-900">
                      A corequisite is taken in the same term — it does not have to be
                      finished first, and it does not affect the eligibility check above.
                    </p>
                    <CoreqLine node={result.corequisite} onSelect={selectCourse} />
                  </section>
                )}

                {(result.course.credit_exclusions || []).length > 0 && (
                  <section className="rounded-lg border border-slate-200 bg-white p-4 text-sm">
                    <h3 className="font-semibold">Credit exclusions</h3>
                    <p className="mt-1 text-slate-700">
                      You cannot receive credit for both {result.course.code} and:{' '}
                      {result.course.credit_exclusions.join(', ')}.
                    </p>
                  </section>
                )}
              </article>

              <PrintOutline result={result} />
            </>
          )}
        </main>
      </div>

      <footer className="no-print mt-10 border-t border-slate-200 pt-4 text-xs text-slate-500">
        Unofficial student project. Not affiliated with the University of Alberta. Data
        scraped from the public course catalogue; verify everything against the official
        calendar.
      </footer>
    </div>
  );
}
