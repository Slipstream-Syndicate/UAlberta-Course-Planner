/**
 * CMPUT Prerequisite Explorer -- boolean eval engine (Phase 2)
 *
 * "What are my options": given a target course and the courses a student has
 * already completed, walk the prerequisite tree and report which branches are
 * satisfied and what concrete courses would unlock the rest.
 *
 * Runs entirely client-side (CLAUDE.md: there is no backend). Deliberately has
 * no imports and no DOM/React dependency so it can be unit-tested with plain
 * node -- see evalEngine.test.js.
 *
 * Four rules from CLAUDE.md are structural here, not incidental:
 *
 *   1. Credit exclusions are checked BEFORE eligibility. If the student
 *      already has a course that is mutually exclusive with the target, the
 *      honest answer is "you likely cannot take this", not a tidy eligibility
 *      readout that ignores it.
 *   2. Corequisites are NOT folded into the AND/OR check. "Take alongside" is
 *      a different claim from "must already be done", and merging them would
 *      tell students they are ineligible for courses they can register for.
 *   3. External (unscraped) courses are leaves. We never recurse into their
 *      prerequisites, because we never scraped them -- inventing a chain there
 *      would be a confident lie.
 *   4. Recursion is guarded by a visited set and a depth cap. Real catalogue
 *      prerequisites should not cycle, but a parser bug could produce one, and
 *      hanging the browser is a worse failure than a flagged error.
 */

export const MAX_DEPTH = 12;

/** Requirement kinds returned in `remaining`. */
export const REQ_COURSE = 'course';
export const REQ_LEVEL = 'level';

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

export function normalizeCode(code) {
  return String(code || '').trim().toUpperCase().replace(/\s+/g, ' ');
}

export function subjectOf(code) {
  return normalizeCode(code).replace(/\s+[\d-].*$/, '');
}

export function levelOf(code) {
  const m = normalizeCode(code).match(/(\d{3})/);
  return m ? parseInt(m[1], 10) : 0;
}

/** Build the lookup the engine works against. */
export function buildIndex(courses) {
  const index = new Map();
  for (const c of courses) index.set(normalizeCode(c.code), c);
  return index;
}

export function makeCompletedSet(codes) {
  return new Set((codes || []).map(normalizeCode).filter(Boolean));
}

function reqKey(req) {
  return req.kind === REQ_COURSE
    ? 'c:' + req.code
    : 'l:' + req.subject + ':' + req.minLevel;
}

/** Union of requirement lists, order-preserving and de-duplicated. */
function unionReqs(lists) {
  const seen = new Set();
  const out = [];
  for (const list of lists) {
    for (const req of list) {
      const k = reqKey(req);
      if (!seen.has(k)) {
        seen.add(k);
        out.push(req);
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Tree evaluation
// ---------------------------------------------------------------------------

/**
 * Annotate a prerequisite tree against a completed-course set.
 *
 * Returns a parallel tree where every node carries:
 *   satisfied   boolean
 *   remaining   the cheapest set of requirements that would satisfy this node
 *   alternatives (OR nodes only) one entry per branch, so the UI can offer a
 *               real choice instead of only the shortest path
 *   error       set when the depth/cycle guard tripped
 */
export function evaluateTree(node, completed, index, options = {}) {
  const ctx = {
    index,
    completed,
    depth: 0,
    stack: options.stack || new Set(),
    maxDepth: options.maxDepth || MAX_DEPTH,
    errors: options.errors || [],
  };
  const result = walk(node, ctx);
  result.errors = ctx.errors;
  return result;
}

function walk(node, ctx) {
  if (!node) {
    return { type: 'EMPTY', satisfied: true, remaining: [] };
  }

  if (ctx.depth > ctx.maxDepth) {
    const err = 'Prerequisite chain exceeded ' + ctx.maxDepth +
      ' levels; stopped to avoid infinite recursion. This usually means a parse error.';
    ctx.errors.push(err);
    return { ...node, satisfied: false, remaining: [], error: err };
  }

  switch (node.type) {
    case 'COURSE':
      return walkCourse(node, ctx);
    case 'LEVEL_MIN':
      return walkLevelMin(node, ctx);
    case 'AND':
      return walkAnd(node, ctx);
    case 'OR':
      return walkOr(node, ctx);
    default: {
      const err = 'Unknown node type "' + node.type + '" in prerequisite tree.';
      ctx.errors.push(err);
      return { ...node, satisfied: false, remaining: [], error: err };
    }
  }
}

function walkCourse(node, ctx) {
  const code = normalizeCode(node.code);
  if (ctx.completed.has(code)) {
    return { ...node, satisfied: true, remaining: [] };
  }

  const req = { kind: REQ_COURSE, code, external: !!node.external };

  // Cycle guard: a course that (transitively) requires itself.
  if (ctx.stack.has(code)) {
    const err = 'Prerequisite cycle detected at ' + code +
      '. Treating it as a leaf; the parsed data for this chain is likely wrong.';
    ctx.errors.push(err);
    return { ...node, satisfied: false, remaining: [req], error: err };
  }

  const target = ctx.index.get(code);

  // External / untracked: a leaf by rule, not by accident. We have no data on
  // its prerequisites and must not pretend otherwise.
  if (node.external || !target) {
    return { ...node, satisfied: false, remaining: [req], external: true };
  }

  // Show the deeper chain: what would it take to unlock this course too?
  ctx.stack.add(code);
  ctx.depth += 1;
  const sub = walk(target.prerequisite_tree, ctx);
  ctx.depth -= 1;
  ctx.stack.delete(code);

  return {
    ...node,
    satisfied: false,
    // You need the course itself AND whatever unlocks it -- listed in the
    // order you would actually take them, deepest prerequisite first.
    //
    // The reverse order is what a naive implementation produces, and it reads
    // as a to-do list starting with the one course you cannot register for
    // yet: "CMPUT 201, CMPUT 175, ENCMP 100" tells a student to start at 201
    // when ENCMP 100 is where they have to begin. The UI labels this a
    // "path", so it has to actually be walkable top to bottom.
    remaining: unionReqs([sub.remaining, [req]]),
    chain: sub.type === 'EMPTY' ? null : sub,
    parseStatus: target.parse_status,
  };
}

function walkLevelMin(node, ctx) {
  const match = [...ctx.completed].find(
    (c) => subjectOf(c) === node.subject && levelOf(c) >= node.min_level
  );
  if (match) {
    return { ...node, satisfied: true, remaining: [], satisfiedBy: match };
  }
  return {
    ...node,
    satisfied: false,
    remaining: [{ kind: REQ_LEVEL, subject: node.subject, minLevel: node.min_level }],
  };
}

function walkAnd(node, ctx) {
  const children = node.children.map((c) => walk(c, ctx));
  const satisfied = children.every((c) => c.satisfied);
  return {
    ...node,
    children,
    satisfied,
    // Every unmet branch must be met, so the costs add up.
    remaining: satisfied ? [] : unionReqs(children.filter((c) => !c.satisfied).map((c) => c.remaining)),
  };
}

function walkOr(node, ctx) {
  const children = node.children.map((c) => walk(c, ctx));
  const satisfied = children.some((c) => c.satisfied);

  // Each branch is a genuine alternative -- the UI should be able to show all
  // of them, not just the one we happen to score cheapest.
  const alternatives = children
    .filter((c) => !c.satisfied)
    .map((c) => c.remaining)
    .filter((r) => r.length > 0);

  let remaining = [];
  if (!satisfied && alternatives.length) {
    // Cheapest = fewest courses still to take. Ties break toward the branch
    // listed first in the calendar, which tends to be the standard path.
    remaining = alternatives.reduce((best, r) => (r.length < best.length ? r : best));
  }

  return { ...node, children, satisfied, remaining, alternatives };
}

// ---------------------------------------------------------------------------
// Top-level: everything the UI needs about one target course
// ---------------------------------------------------------------------------

/**
 * @param {Array}  courses   parsed courses.json `courses` array
 * @param {string} targetCode e.g. "CMPUT 301"
 * @param {Array}  completedCodes course codes the student self-reports
 */
export function evaluateCourse(courses, targetCode, completedCodes) {
  const index = courses instanceof Map ? courses : buildIndex(courses);
  const code = normalizeCode(targetCode);
  const course = index.get(code);

  if (!course) {
    return { found: false, code, error: 'Course "' + code + '" is not in this dataset.' };
  }

  const completed = makeCompletedSet(completedCodes);

  // RULE 1: credit exclusions come first. Running an eligibility check on a
  // course the student can't receive credit for would answer the wrong
  // question convincingly.
  const conflicts = (course.credit_exclusions || [])
    .map(normalizeCode)
    .filter((c) => completed.has(c));

  const alreadyCompleted = completed.has(code);
  const prereq = evaluateTree(course.prerequisite_tree, completed, index);

  // RULE 2: corequisites are evaluated separately and never gate eligibility.
  const coreq = course.corequisite_tree
    ? evaluateTree(course.corequisite_tree, completed, index)
    : null;

  // An empty tree means "no prerequisites" ONLY when the parse succeeded.
  // When it did not, the tree is empty because we could not read the
  // requirements -- and a satisfied-by-default walk would report the student
  // eligible for a course that is in fact gated. MATH 422 with an empty
  // transcript hit exactly that: `eligible: true`, rendered as a green
  // "you satisfy the prerequisites".
  //
  // The same applies when the tree IS satisfied but we know it is incomplete
  // (MATH 570's "a 400 or 500 level course on Partial Differential
  // Equations"): satisfying the part we modelled says nothing about the part
  // we did not.
  //
  // So eligibility is three-valued: true / false / null = cannot say.
  const unrepresented = course.unrepresented_requirements || [];
  const cannotJudge =
    course.parse_status === 'unparsed' ||
    (prereq.satisfied && unrepresented.length > 0);

  let eligible;
  if (conflicts.length > 0) {
    eligible = false;
  } else if (cannotJudge) {
    eligible = null;
  } else {
    eligible = prereq.satisfied;
  }

  return {
    found: true,
    course,
    code,
    alreadyCompleted,
    blocked: conflicts.length > 0,
    conflicts,
    eligible,
    // True when the tool cannot honestly answer "am I eligible?" for this
    // course, whatever the completed list is.
    eligibilityUnknown: conflicts.length === 0 && cannotJudge,
    unrepresented,
    prerequisite: prereq,
    corequisite: coreq,
    // Surfaced so the UI can flag confidence rather than implying certainty.
    parseStatus: course.parse_status,
    prerequisitesText: course.prerequisites_text,
    notes: course.notes || [],
    errors: prereq.errors || [],
    // Flat "here is what's left" list, ready to render.
    remaining: prereq.remaining || [],
  };
}

/** Human-readable label for one remaining requirement. */
export function describeRequirement(req) {
  if (req.kind === REQ_LEVEL) {
    return 'any ' + req.minLevel + '-level ' + req.subject + ' course';
  }
  return req.code + (req.external ? ' (not tracked here — verify yourself)' : '');
}
