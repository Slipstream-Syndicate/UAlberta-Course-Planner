/**
 * UAlberta Prerequisite Explorer -- boolean eval engine (Phase 2)
 *
 * "What are my options": given a target course and the courses a student has
 * already completed, walk the prerequisite tree and report which branches are
 * satisfied and what concrete courses would unlock the rest.
 *
 * Runs entirely client-side (DESIGN.md: there is no backend). Deliberately has
 * no imports and no DOM/React dependency so it can be unit-tested with plain
 * node -- see evalEngine.test.js.
 *
 * Four rules from DESIGN.md are structural here, not incidental:
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
 *   4. Recursion is guarded by a visited set and a depth cap. A course that
 *      requires ITSELF is always a parse bug and is reported as an error. A
 *      loop between different courses can be faithful to the catalogue
 *      (MA PH 351 and MATH 337 each list the other as one alternative), so
 *      it is not an error: the looping branch is a dead end ON THIS PATH --
 *      you cannot use X to unlock the very course you need in order to get
 *      to X -- and the walk takes the other branches. It is recorded in
 *      `cycles` so the UI can say so neutrally.
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

// "CMPUT 201", "cmput201", "MA PH351", "E E 380", "MATH 30-1", "CMPUT 296A".
const CODE_SHAPE_RE = /^([A-Z]+(?: [A-Z]+)*)\s*(\d{2,3}[A-Z]{0,2}(?:-\d)?)$/;

/**
 * Parse what a student types into the completed-courses box.
 *
 * The box's own placeholder reads "e.g. CMPUT 201, MATH 125", so a comma
 * list is the expected input -- yet it used to be stored as ONE code,
 * "CMPUT 201, MATH 125", which matched nothing and silently changed every
 * eligibility answer. Likewise "cmput201" never matched "CMPUT 201".
 *
 * Returns { codes, invalid }: canonical codes, and the pieces that do not
 * look like a course code at all, so the UI can say so instead of guessing.
 */
export function parseCourseList(input) {
  const codes = [];
  const invalid = [];
  for (const piece of String(input || '').split(/[,;\n]+|\s+and\s+/i)) {
    const raw = normalizeCode(piece);
    if (!raw) continue;
    const m = raw.match(CODE_SHAPE_RE);
    if (!m) {
      invalid.push(piece.trim());
      continue;
    }
    const code = m[1] + ' ' + m[2];
    if (!codes.includes(code)) codes.push(code);
  }
  return { codes, invalid };
}

/** Subjects a LEVEL_MIN accepts: one code, or a department's whole list. */
export function levelSubjects(node) {
  return node.subjects && node.subjects.length ? node.subjects : [node.subject];
}

function reqKey(req) {
  return req.kind === REQ_COURSE
    ? 'c:' + req.code
    : 'l:' + (req.subjects || [req.subject]).join('/') + ':' + req.minLevel;
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
 *   deadEnd     this branch cannot be completed on this path (it loops back
 *               to a course already being unlocked); OR nodes skip it
 *   error       set when the depth guard tripped or a course requires itself
 *
 * `options.root` is the course whose tree this is. It starts on the stack, so
 * a branch that loops straight back to it is caught at once.
 */
export function evaluateTree(node, completed, index, options = {}) {
  const stack = options.stack || new Set();
  const root = options.root ? normalizeCode(options.root) : null;
  if (root) stack.add(root);
  const ctx = {
    index,
    completed,
    depth: 0,
    root,
    stack,
    maxDepth: options.maxDepth || MAX_DEPTH,
    errors: options.errors || [],
    cycles: options.cycles || [],
  };
  const result = walk(node, ctx);
  if (root) stack.delete(root);
  result.errors = ctx.errors;
  result.cycles = ctx.cycles;
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

  if (ctx.stack.has(code)) {
    // A course naming ITSELF directly is always a parse bug.
    if (code === ctx.root && ctx.depth === 0) {
      const err = code + ' lists itself as its own prerequisite. ' +
        'This is a parsing error; read the calendar text instead.';
      ctx.errors.push(err);
      return { ...node, satisfied: false, remaining: [], deadEnd: true, error: err };
    }
    // A loop through other courses: a dead end on this path, not an error.
    const msg = 'One route loops back to ' + code +
      ' (the catalogue lists these courses as alternatives for each other), ' +
      'so that route is not counted.';
    if (!ctx.cycles.includes(msg)) ctx.cycles.push(msg);
    return { ...node, satisfied: false, remaining: [], deadEnd: true, cycle: true };
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
    // If every way into this course loops back, it is unreachable here too.
    deadEnd: !!sub.deadEnd,
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
  // A department-wide constraint ("a 200-level Biological Sciences course")
  // carries every subject it spans; any of them satisfies it.
  const subjects = levelSubjects(node);
  const match = [...ctx.completed].find(
    (c) => subjects.includes(subjectOf(c)) && levelOf(c) >= node.min_level
  );
  if (match) {
    return { ...node, satisfied: true, remaining: [], satisfiedBy: match };
  }
  const req = { kind: REQ_LEVEL, subject: node.subject, minLevel: node.min_level };
  if (node.subjects) {
    req.subjects = node.subjects;
    req.label = node.label;
  }
  return { ...node, satisfied: false, remaining: [req] };
}

function walkAnd(node, ctx) {
  const children = node.children.map((c) => walk(c, ctx));
  const satisfied = children.every((c) => c.satisfied);
  return {
    ...node,
    children,
    satisfied,
    // One unreachable requirement makes the whole AND unreachable.
    deadEnd: !satisfied && children.some((c) => c.deadEnd),
    // Every unmet branch must be met, so the costs add up.
    remaining: satisfied ? [] : unionReqs(children.filter((c) => !c.satisfied).map((c) => c.remaining)),
  };
}

function walkOr(node, ctx) {
  const children = node.children.map((c) => walk(c, ctx));
  const satisfied = children.some((c) => c.satisfied);

  // Each branch is a genuine alternative -- the UI should be able to show all
  // of them, not just the one we happen to score cheapest. Dead-end branches
  // (loops) are not alternatives anyone can actually take.
  const alternatives = children
    .filter((c) => !c.satisfied && !c.deadEnd)
    .map((c) => c.remaining)
    .filter((r) => r.length > 0);
  const deadEnd = !satisfied && children.every((c) => c.deadEnd);

  let remaining = [];
  if (!satisfied && alternatives.length) {
    // Cheapest = fewest courses still to take. Ties break toward the branch
    // listed first in the calendar, which tends to be the standard path.
    remaining = alternatives.reduce((best, r) => (r.length < best.length ? r : best));
  }

  return { ...node, children, satisfied, remaining, alternatives, deadEnd };
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
  // Callers that evaluate repeatedly (the UI, on every keystroke in the
  // completed list) should pass a prebuilt index; buildIndex is O(n).
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
  const prereq = evaluateTree(course.prerequisite_tree, completed, index, { root: code });

  // RULE 2: corequisites are evaluated separately and never gate eligibility.
  const coreq = course.corequisite_tree
    ? evaluateTree(course.corequisite_tree, completed, index, { root: code })
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
    (prereq.satisfied && unrepresented.length > 0) ||
    // Every route loops back on itself: nothing actionable can be said.
    !!prereq.deadEnd;

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
    // Loops through other courses: faithful catalogue data, explained, not errors.
    cycles: prereq.cycles || [],
    // Flat "here is what's left" list, ready to render.
    remaining: prereq.remaining || [],
  };
}

/** Human-readable label for one remaining requirement. */
export function describeRequirement(req) {
  if (req.kind === REQ_LEVEL) {
    return 'any ' + req.minLevel + '-level ' + levelLabel(req) + ' course';
  }
  return req.code + (req.external ? ' (not tracked here — verify yourself)' : '');
}

/** "CMPUT", or "Biological Sciences (BIOL, BOT, ...)" for a department. */
export function levelLabel(nodeOrReq) {
  if (nodeOrReq.subjects && nodeOrReq.subjects.length) {
    return (nodeOrReq.label || nodeOrReq.subject) + ' (' + nodeOrReq.subjects.join(', ') + ')';
  }
  return nodeOrReq.subject;
}
