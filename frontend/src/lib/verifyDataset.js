/**
 * Whole-dataset behavioural verification of the eval engine.
 *
 * parser/verify_all.py checks that the DATA is well formed. This checks that
 * the ENGINE behaves correctly on all of it, by asserting properties that must
 * hold for every course rather than by hand-picking examples.
 *
 * The central one is a round trip:
 *
 *     ask "what do I still need?" -> mark exactly that complete -> re-ask
 *
 * and the answer must flip to eligible. If it does not, the advice the app
 * gives is not actionable: a student could follow it exactly and still be
 * turned away. That single property exercises the AND/OR walk, the chain
 * expansion, the LEVEL_MIN handling and the external-leaf rule at once, on
 * every course, without anyone hand-writing an expected tree.
 *
 *     node frontend/src/lib/verifyDataset.js
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import { evaluateCourse, describeRequirement, MAX_DEPTH } from './evalEngine.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const payload = JSON.parse(
  readFileSync(resolve(HERE, '../../../data/courses.json'), 'utf8')
);
const courses = payload.courses;

const failures = [];
const notes = [];
const guarded = new Set();

function fail(code, msg) {
  failures.push(code + ': ' + msg);
}

/** A remaining requirement -> a course code a student could actually report. */
function satisfyingCode(req) {
  if (req.kind === 'course') return req.code;
  // LEVEL_MIN: any course in that subject at or above the level satisfies it.
  return req.subject + ' ' + req.minLevel;
}

let withTree = 0;
let roundTripped = 0;

for (const c of courses) {
  const cold = evaluateCourse(courses, c.code, []);

  // --- every course must evaluate without error -----------------------------
  if (!cold.found) {
    fail(c.code, 'not found by its own code');
    continue;
  }
  // A guarded cycle is expected in real data, not a failure: MA PH 351 and
  // MATH 337 each list the other as one OR alternative, and ~26 PHYS/GEOPH/
  // MATH courses reach that pair transitively. The engine catching it and
  // continuing is the behaviour we want; only a NEW kind of error is a bug.
  const nonCycle = cold.errors.filter((e) => !/cycle detected/.test(e));
  if (nonCycle.length) {
    fail(c.code, 'evaluation raised: ' + nonCycle.join('; '));
  } else if (cold.errors.length) {
    guarded.add(c.code);
  }

  // --- honesty: an unreadable course must never claim eligibility -----------
  if (c.parse_status === 'unparsed' && cold.eligible === true) {
    fail(c.code, 'unparsed but reports eligible:true');
  }
  if (c.parse_status === 'unparsed' && !cold.eligibilityUnknown) {
    fail(c.code, 'unparsed but not flagged eligibilityUnknown');
  }
  if (cold.eligibilityUnknown && !c.source_url) {
    fail(c.code, 'cannot be judged but offers no catalogue URL to fall back to');
  }

  // --- a course with no prerequisites is eligible from cold ------------------
  if (c.parse_status === 'parsed' && !c.prerequisite_tree) {
    if (cold.eligible !== true) {
      fail(c.code, 'has no prerequisites but is not eligible from an empty transcript');
    }
    continue;
  }

  if (!c.prerequisite_tree) continue;
  withTree += 1;

  // --- cold start must produce actionable advice ----------------------------
  if (cold.eligible === true) {
    fail(c.code, 'has a prerequisite tree yet is eligible with nothing completed');
    continue;
  }
  if (cold.eligible === false && cold.remaining.length === 0) {
    fail(c.code, 'is not eligible but names nothing that would fix it');
    continue;
  }

  // --- THE ROUND TRIP -------------------------------------------------------
  const plan = cold.remaining.map(satisfyingCode);
  const after = evaluateCourse(courses, c.code, plan);

  if (after.eligible === null) {
    // Legitimate: the tree is satisfied but known incomplete. Not a failure,
    // but it must be saying so rather than silently passing.
    if (!after.eligibilityUnknown) {
      fail(c.code, 'returned eligible:null without flagging why');
    }
    notes.push(c.code + ': plan satisfies the tree, but the tree is incomplete');
    continue;
  }
  if (after.eligible !== true) {
    fail(
      c.code,
      'following its own advice does not make it eligible.\n' +
        '        needed: ' + cold.remaining.map(describeRequirement).join(' + ') + '\n' +
        '        after:  ' + after.remaining.map(describeRequirement).join(' + ')
    );
    continue;
  }
  roundTripped += 1;

  // --- the plan must be ordered, and end on a load-bearing step -------------
  //
  // NOT a per-item minimality check: `remaining` is a CHAIN, not a set. For
  // MATH 412 it reads 30-1 -> 127 -> 227 -> 326, and dropping an ancestor
  // still leaves the target eligible, because the direct prerequisite is
  // self-reported and the engine takes the student at their word. Those items
  // are not redundant; they are how you get there.
  //
  // What must hold is that the chain is listed in walkable order, so the LAST
  // item is the direct prerequisite and removing it breaks eligibility.
  //
  // Skipped when the plan contains a LEVEL_MIN placeholder. BIOL 430 needs
  // "BIOL 330 and a 300-level Biological Sciences course" -- and BIOL 330 IS
  // a 300-level BIOL course, so the placeholder is genuinely redundant once
  // the rest of the plan is done. The tree is right; the plan just lists a
  // constraint another step already satisfies. Worth knowing, not a failure.
  const hasLevelPlaceholder = cold.remaining.some((r) => r.kind !== 'course');
  if (plan.length > 1 && !hasLevelPlaceholder) {
    const withoutLast = plan.slice(0, -1);
    if (evaluateCourse(courses, c.code, withoutLast).eligible === true) {
      fail(c.code, 'plan is listed out of order: dropping its last step (' +
        plan[plan.length - 1] + ') still leaves the course eligible');
    }
  }

  // --- completing the course itself must be recognised ---------------------
  if (!evaluateCourse(courses, c.code, [c.code]).alreadyCompleted) {
    fail(c.code, 'completing it is not recognised');
  }

  // --- a credit conflict must block regardless of prerequisites -------------
  if (c.credit_exclusions.length) {
    const blocked = evaluateCourse(courses, c.code, plan.concat([c.credit_exclusions[0]]));
    if (!blocked.blocked || blocked.eligible === true) {
      fail(c.code, 'credit exclusion ' + c.credit_exclusions[0] + ' does not block it');
    }
  }
}

// --- depth guard sanity -----------------------------------------------------
const depthBlowups = courses
  .map((c) => evaluateCourse(courses, c.code, []))
  .filter((r) => (r.errors || []).some((e) => /exceeded/.test(e)));
if (depthBlowups.length) {
  fail('dataset', depthBlowups.length + ' courses exceed the depth cap');
}

console.log('='.repeat(74));
console.log('ENGINE VERIFICATION -- ' + courses.length + ' courses');
console.log('='.repeat(74));
console.log('  ' + withTree + ' courses have a prerequisite tree');
console.log('  ' + roundTripped + ' round-tripped: their own advice makes them eligible');
console.log('  ' + notes.length + ' satisfied the tree but are flagged incomplete');
console.log('  ' + guarded.size + ' reach a guarded cycle (real catalogue data, handled)');
console.log('  depth cap: ' + MAX_DEPTH);

if (notes.length) {
  console.log('\nIncomplete-tree courses (correctly flagged, not failures):');
  for (const n of notes) console.log('  ' + n);
}

console.log('\nFAILURES (' + failures.length + ')');
for (const f of failures) console.log('  ' + f);

console.log('\n' + (failures.length ? 'FAILED' : 'PASSED'));
process.exit(failures.length ? 1 : 0);
