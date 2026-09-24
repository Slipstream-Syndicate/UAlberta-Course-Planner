/**
 * Phase 2 exit criterion (CLAUDE.md): the boolean walk, the credit-exclusion
 * check, corequisite separation, cross-subject external leaves, and the
 * cycle/depth guard.
 *
 * No test framework -- plain node, so it runs with zero install:
 *     node frontend/src/lib/evalEngine.test.js
 *
 * Runs twice: once against hand-built fixtures (so a failure points at the
 * engine, not the scrape), and once against the REAL data/courses.json (so the
 * engine is proven against the data it will actually ship with).
 */

import { readFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  evaluateCourse,
  describeRequirement,
  MAX_DEPTH,
} from './evalEngine.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const COURSES_JSON = resolve(HERE, '../../../data/courses.json');

let passed = 0;
let failed = 0;

function check(name, actual, expected) {
  const a = JSON.stringify(actual);
  const e = JSON.stringify(expected);
  if (a === e) {
    passed += 1;
    console.log('  ok   ' + name);
  } else {
    failed += 1;
    console.log('  FAIL ' + name);
    console.log('       expected: ' + e);
    console.log('       actual:   ' + a);
  }
}

const course = (code, extra = {}) => ({
  code,
  title: code,
  parse_status: 'parsed',
  prerequisite_tree: null,
  corequisite_tree: null,
  credit_exclusions: [],
  notes: [],
  ...extra,
});

const C = (code, external = false) => ({ type: 'COURSE', code, external });
const OR = (...children) => ({ type: 'OR', children });
const AND = (...children) => ({ type: 'AND', children });
const LEVEL = (subject, min_level) => ({ type: 'LEVEL_MIN', subject, min_level });

// A miniature CMPUT catalogue mirroring the real shapes.
const FIXTURES = [
  course('CMPUT 174'),
  course('CMPUT 175', { prerequisite_tree: OR(C('CMPUT 174'), C('ENCMP 100', true)) }),
  course('CMPUT 201', { prerequisite_tree: C('CMPUT 175') }),
  course('CMPUT 274'),
  course('CMPUT 275', { prerequisite_tree: C('CMPUT 274') }),
  course('CMPUT 301', {
    prerequisite_tree: OR(C('CMPUT 201'), C('CMPUT 275')),
    credit_exclusions: ['BTM 419', 'MIS 419'],
  }),
  course('CMPUT 291', {
    prerequisite_tree: C('CMPUT 175'),
    corequisite_tree: OR(C('CMPUT 201'), C('CMPUT 275')),
  }),
  course('CMPUT 415', {
    prerequisite_tree: AND(
      OR(C('CMPUT 229'), C('E E 380', true), C('ECE 212', true)),
      LEVEL('CMPUT', 300)
    ),
  }),
  course('CMPUT 229', { prerequisite_tree: OR(C('CMPUT 201'), C('CMPUT 275')) }),
  // Deliberately broken data for the guard tests.
  course('CMPUT 900', { prerequisite_tree: C('CMPUT 901') }),
  course('CMPUT 901', { prerequisite_tree: C('CMPUT 900') }),
  course('CMPUT 902', { prerequisite_tree: C('CMPUT 902') }),
];

const codesOf = (reqs) => reqs.map((r) => (r.kind === 'level' ? 'any ' + r.minLevel + '-level ' + r.subject : r.code));

// ---------------------------------------------------------------------------

console.log('boolean walk: OR satisfied by either branch');
{
  const viaA = evaluateCourse(FIXTURES, 'CMPUT 301', ['CMPUT 201']);
  const viaB = evaluateCourse(FIXTURES, 'CMPUT 301', ['CMPUT 275']);
  const neither = evaluateCourse(FIXTURES, 'CMPUT 301', []);
  check('301 eligible via 201', viaA.eligible, true);
  check('301 eligible via 275', viaB.eligible, true);
  check('301 not eligible with nothing', neither.eligible, false);
}

console.log('AND requires every branch');
{
  const partial = evaluateCourse(FIXTURES, 'CMPUT 415', ['CMPUT 229']);
  check('415 with only the OR half satisfied is not eligible', partial.eligible, false);
  check('415 remaining is the LEVEL_MIN half', codesOf(partial.remaining), ['any 300-level CMPUT']);
  const done = evaluateCourse(FIXTURES, 'CMPUT 415', ['CMPUT 229', 'CMPUT 301']);
  check('415 eligible once a 300-level CMPUT is done', done.eligible, true);
}

console.log('LEVEL_MIN evaluates against different completed lists');
{
  const tooLow = evaluateCourse(FIXTURES, 'CMPUT 415', ['CMPUT 229', 'CMPUT 201']);
  check('a 200-level course does not satisfy 300-level', tooLow.eligible, false);
  const wrongSubject = evaluateCourse(FIXTURES, 'CMPUT 415', ['CMPUT 229', 'MATH 314']);
  check('a 300-level MATH does not satisfy a CMPUT constraint', wrongSubject.eligible, false);
  const higher = evaluateCourse(FIXTURES, 'CMPUT 415', ['CMPUT 229', 'CMPUT 415']);
  check('a higher-level CMPUT does satisfy min_level 300', higher.eligible, true);
}

console.log('credit exclusion blocks before eligibility is even considered');
{
  const blocked = evaluateCourse(FIXTURES, 'CMPUT 301', ['CMPUT 201', 'MIS 419']);
  check('301 is blocked when MIS 419 is completed', blocked.blocked, true);
  check('301 names the conflict', blocked.conflicts, ['MIS 419']);
  check('301 is not reported eligible despite prereqs being met', blocked.eligible, false);
  const clean = evaluateCourse(FIXTURES, 'CMPUT 301', ['CMPUT 201']);
  check('no conflict when the excluded course is absent', clean.blocked, false);
}

console.log('corequisites stay separate from the eligibility check');
{
  const r = evaluateCourse(FIXTURES, 'CMPUT 291', ['CMPUT 175']);
  check('291 eligible on prereqs alone', r.eligible, true);
  check('291 corequisite is reported unsatisfied, not folded in', r.corequisite.satisfied, false);
  check('291 corequisite options', codesOf(r.corequisite.remaining), ['CMPUT 201']);
}

console.log('cross-subject references are leaves, never recursed into');
{
  const r = evaluateCourse(FIXTURES, 'CMPUT 175', []);
  const enc = r.prerequisite.children.find((c) => c.code === 'ENCMP 100');
  check('ENCMP 100 marked external', enc.external, true);
  check('ENCMP 100 has no expanded chain', enc.chain === undefined, true);
  check('external course counts as a plain unmet requirement',
    codesOf(enc.remaining), ['ENCMP 100']);
  const self = evaluateCourse(FIXTURES, 'CMPUT 175', ['ENCMP 100']);
  check('a self-reported external course satisfies the branch', self.eligible, true);
}

console.log('deeper chain: unsatisfied courses expand to show what unlocks them');
{
  const r = evaluateCourse(FIXTURES, 'CMPUT 301', []);
  // Deepest prerequisite FIRST: the list is labelled a "path" in the UI, so it
  // has to be walkable top to bottom. Listing CMPUT 275 before CMPUT 274 would
  // open the to-do list with the one course you cannot yet register for.
  check('301 cheapest path is the shorter of 201/275 chains, in walkable order',
    codesOf(r.remaining), ['CMPUT 274', 'CMPUT 275']);
  check('301 offers both branches as alternatives, each in walkable order',
    r.prerequisite.alternatives.map(codesOf),
    [['CMPUT 174', 'CMPUT 175', 'CMPUT 201'], ['CMPUT 274', 'CMPUT 275']]);
  check('the last step of the path is the direct prerequisite',
    codesOf(r.remaining).at(-1), 'CMPUT 275');
}

console.log('cycle and depth guards fail loudly instead of hanging');
{
  const mutual = evaluateCourse(FIXTURES, 'CMPUT 900', []);
  check('mutual cycle is detected', mutual.errors.length > 0, true);
  check('mutual cycle error names the course',
    mutual.errors.some((e) => e.includes('cycle')), true);
  const self = evaluateCourse(FIXTURES, 'CMPUT 902', []);
  check('self-referencing course is detected', self.errors.length > 0, true);
  check('guarded result still returns rather than hanging', self.found, true);
}

console.log('eligibility is three-valued: an unreadable course never reports "eligible"');
{
  // A course whose prerequisites could not be parsed has an EMPTY tree, and an
  // empty tree walks as satisfied. Before this was handled, MATH 422 with an
  // empty transcript reported eligible:true and rendered a green "you satisfy
  // the prerequisites" -- a confident promise about a course we cannot read.
  const fixtures = [
    course('CMPUT 800'),                                    // genuinely no prereqs
    course('CMPUT 801', { parse_status: 'unparsed' }),      // unreadable
    course('CMPUT 802', {                                   // readable but incomplete
      parse_status: 'partial',
      prerequisite_tree: C('CMPUT 800'),
      unrepresented_requirements: ['a 400 or 500 level course on PDEs'],
    }),
  ];

  const none = evaluateCourse(fixtures, 'CMPUT 800', []);
  check('a course with genuinely no prerequisites is still eligible', none.eligible, true);
  check('...and is not flagged unknown', none.eligibilityUnknown, false);

  const unreadable = evaluateCourse(fixtures, 'CMPUT 801', []);
  check('an unparsed course reports eligible:null, not true', unreadable.eligible, null);
  check('an unparsed course is flagged unknown', unreadable.eligibilityUnknown, true);

  const incompleteUnmet = evaluateCourse(fixtures, 'CMPUT 802', []);
  check('an incomplete tree that is UNMET is still a definite no',
    incompleteUnmet.eligible, false);

  const incompleteMet = evaluateCourse(fixtures, 'CMPUT 802', ['CMPUT 800']);
  check('an incomplete tree that is MET cannot be called eligible',
    incompleteMet.eligible, null);
  check('...and says why', incompleteMet.unrepresented.length > 0, true);

  // A credit conflict is still a definite "no", never "unknown".
  const conflicted = evaluateCourse(
    [course('CMPUT 803', { parse_status: 'unparsed', credit_exclusions: ['MIS 419'] })],
    'CMPUT 803', ['MIS 419']
  );
  check('a credit conflict outranks unknown', conflicted.eligible, false);
  check('a credit conflict is not reported as unknown', conflicted.eligibilityUnknown, false);
}

console.log('misc');
{
  const missing = evaluateCourse(FIXTURES, 'CMPUT 999', []);
  check('unknown course reports found:false', missing.found, false);
  const done = evaluateCourse(FIXTURES, 'CMPUT 301', ['CMPUT 301', 'CMPUT 201']);
  check('already-completed target is flagged', done.alreadyCompleted, true);
  check('case and spacing are normalized',
    evaluateCourse(FIXTURES, 'cmput  301', ['cmput 201']).eligible, true);
  check('describeRequirement labels a level constraint',
    describeRequirement({ kind: 'level', subject: 'CMPUT', minLevel: 300 }),
    'any 300-level CMPUT course');
  check('MAX_DEPTH is a real cap', MAX_DEPTH > 0, true);
}

// ---------------------------------------------------------------------------
// Same engine, real scraped data.
// ---------------------------------------------------------------------------

if (existsSync(COURSES_JSON)) {
  console.log('against the real data/courses.json');
  const real = JSON.parse(readFileSync(COURSES_JSON, 'utf8')).courses;

  const r301a = evaluateCourse(real, 'CMPUT 301', ['CMPUT 201']);
  const r301b = evaluateCourse(real, 'CMPUT 301', ['CMPUT 275']);
  check('real 301 reachable via 201', r301a.eligible, true);
  check('real 301 reachable via 275', r301b.eligible, true);
  check('real 301 blocked by MIS 419',
    evaluateCourse(real, 'CMPUT 301', ['CMPUT 201', 'MIS 419']).blocked, true);

  const r415 = evaluateCourse(real, 'CMPUT 415', ['CMPUT 229']);
  check('real 415 still needs a 300-level CMPUT',
    codesOf(r415.remaining), ['any 300-level CMPUT']);

  const r204 = evaluateCourse(real, 'CMPUT 204', ['CMPUT 175', 'CMPUT 272', 'MATH 114']);
  check('real 204 eligible on a real transcript', r204.eligible, true);

  const r313 = evaluateCourse(real, 'CMPUT 313', ['CMPUT 275', 'STAT 151']);
  check('real 313 accepts the 275 shortcut branch', r313.eligible, true);
  const r313b = evaluateCourse(real, 'CMPUT 313', ['CMPUT 201', 'STAT 151']);
  check('real 313 rejects 201 without 204', r313b.eligible, false);

  // Every course must EVALUATE -- returning a result rather than hanging.
  // Cycles do exist in the real catalogue: MA PH 351 lists MATH 337 as one of
  // its alternatives and MATH 337 lists MA PH 351 as one of its own. Neither
  // is a deadlock (each is reachable by its other branch), and the data is
  // faithful, so the requirement is not "no cycles" but "cycles are caught and
  // reported instead of spinning".
  const withErrors = [];
  for (const c of real) {
    const res = evaluateCourse(real, c.code, []);
    if (!res.found) throw new Error('did not evaluate: ' + c.code);
    if (res.errors && res.errors.length) withErrors.push(c.code);
  }
  check('every course in the real dataset evaluates without hanging', true, true);
  check('any cycle is reported as a flagged error, not silently swallowed',
    withErrors.every((code) =>
      evaluateCourse(real, code, []).errors.some((e) => /cycle|levels/.test(e))),
    true);
  // Count distinct cycles, not courses touching one. A single MA PH 351 <->
  // MATH 337 cycle is reached transitively by ~26 PHYS/GEOPH/MATH courses, so
  // counting affected courses measures how well-connected the graph is, not
  // how much is wrong. The number that must stay small is the set of points
  // where a cycle is actually detected.
  const cyclePoints = new Set();
  for (const code of withErrors) {
    for (const e of evaluateCourse(real, code, []).errors) {
      const m = e.match(/cycle detected at ([A-Z][A-Z ]*\d+\w*)/);
      if (m) cyclePoints.add(m[1]);
    }
  }
  // NOTE: this file's `check` compares actual to expected -- not a truthiness.
  check('only a couple of distinct cycles exist -- a spike means a parser regression',
    cyclePoints.size <= 4, true);
  check('the known cycle is the MA PH 351 / MATH 337 pair',
    [...cyclePoints].sort(), ['MA PH 351', 'MATH 337']);

  // A prospective student with zero completed courses should still get a full
  // chain rather than an empty answer (CLAUDE.md "Audience & access").
  const cold = evaluateCourse(real, 'CMPUT 415', []);
  check('cold start on 415 still yields a concrete plan', cold.remaining.length > 0, true);

  // No unreadable course in the shipped data may claim eligibility.
  const falsePromises = real
    .filter((c) => c.parse_status === 'unparsed')
    .map((c) => evaluateCourse(real, c.code, []))
    .filter((r) => r.eligible === true)
    .map((r) => r.code);
  check('no unparsed course in the real dataset reports eligible', falsePromises, []);

  check('real MATH 422 cannot be judged',
    evaluateCourse(real, 'MATH 422', []).eligibilityUnknown, true);
  check('real MATH 422 carries a catalogue URL to fall back to',
    Boolean(evaluateCourse(real, 'MATH 422', []).course.source_url), true);
}

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
