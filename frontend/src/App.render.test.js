/**
 * Phase 3 exit criterion, automated: mount the real App against the real
 * courses.json in a DOM and read what a visitor would actually see.
 *
 * The point is the "cold read" CLAUDE.md asks for -- a correct, readable
 * answer without cross-checking the raw JSON -- so these assertions look at
 * rendered text, not component internals.
 *
 *     npm run test:render
 * (scripts/jsx-loader.mjs compiles the .jsx sources on import.)
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import { JSDOM } from 'jsdom';

const HERE = dirname(fileURLToPath(import.meta.url));
const COURSES = JSON.parse(
  readFileSync(resolve(HERE, '../../data/courses.json'), 'utf8')
);

let passed = 0;
let failed = 0;

function check(name, cond, detail = '') {
  if (cond) {
    passed += 1;
    console.log('  ok   ' + name);
  } else {
    failed += 1;
    console.log('  FAIL ' + name + (detail ? '  ' + detail : ''));
  }
}

// --- DOM + fetch stub -------------------------------------------------------
const dom = new JSDOM('<!doctype html><html><body><div id="root"></div></body></html>', {
  url: 'http://localhost/',
  pretendToBeVisual: true,
});
global.window = dom.window;
global.document = dom.window.document;
global.HTMLElement = dom.window.HTMLElement;
global.Element = dom.window.Element;
global.Node = dom.window.Node;
global.requestAnimationFrame = (cb) => setTimeout(cb, 0);
global.cancelAnimationFrame = clearTimeout;
global.IS_REACT_ACT_ENVIRONMENT = true;
global.fetch = async (url) => {
  if (String(url).includes('courses.json')) {
    return { ok: true, status: 200, json: async () => COURSES };
  }
  throw new Error('unexpected fetch: ' + url);
};

const React = (await import('react')).default;
const { createRoot } = await import('react-dom/client');
const { act } = await import('react');
const App = (await import('./App.jsx')).default;

const container = document.getElementById('root');
const root = createRoot(container);

const flush = async () => {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
};

await act(async () => {
  root.render(React.createElement(App));
});
await flush();

const text = () => container.textContent.replace(/\s+/g, ' ');
const type = async (el, value) => {
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      dom.window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, value);
    el.dispatchEvent(new dom.window.Event('input', { bubbles: true }));
  });
  await flush();
};
const click = async (predicate) => {
  const btn = [...container.querySelectorAll('button')].find(predicate);
  if (!btn) throw new Error('button not found');
  await act(async () => {
    btn.dispatchEvent(new dom.window.MouseEvent('click', { bubbles: true }));
  });
  await flush();
};

console.log('cold load');
check('course data rendered', text().includes('UAlberta Prerequisite Explorer'));
check('disclaimer is visible on the page, not buried',
  text().includes('not official academic advising'), text().slice(0, 200));
check('course count shown', text().includes(String(COURSES.course_count)));

console.log('selecting CMPUT 301 with nothing completed');
// The listing is capped, and at Faculty scale (1,277 courses across 31
// subjects) the first page is all AI/ASTRO/BIOL -- so search, exactly as a
// visitor would.
await type(container.querySelector('input[aria-label="Search courses"]'), 'CMPUT 301');
await click((b) => b.textContent.includes('CMPUT 301') && b.textContent.includes('Software'));
{
  const t = text();
  check('title rendered', t.includes('CMPUT 301 — Introduction to Software Engineering'));
  check('calendar text shown as fallback', t.includes('CMPUT 201 or CMPUT 275'));
  check('confidence flag shown', t.includes('parsed'));
  check('tree offers the OR choice', t.includes('ANY ONE of these'));
  check('shows what is still needed', t.includes('What you still need'));
  check('credit exclusions surfaced', t.includes('BTM 419'));
  check('document.title tracks the course', document.title.startsWith('CMPUT 301'));
}

console.log('marking CMPUT 201 complete makes 301 eligible');
{
  const input = container.querySelector('input[aria-label="Add a completed course"]');
  await type(input, 'CMPUT 201');
  await act(async () => {
    input.form.dispatchEvent(new dom.window.Event('submit', { bubbles: true, cancelable: true }));
  });
  await flush();

  const t = text();
  check('eligibility flips to satisfied',
    t.includes('satisfy the prerequisites'), t.slice(0, 300));
  check('term-availability caveat shown', t.includes('term availability'));
}

console.log('navigating to a second course updates the print title');
// The default listing is truncated, so search first -- which also exercises
// the search box a visitor would use to reach a 400-level course.
await type(container.querySelector('input[aria-label="Search courses"]'), '415');
await click((b) => b.textContent.includes('CMPUT 415') && b.textContent.includes('Compiler'));
{
  check('second course rendered', text().includes('CMPUT 415 — Compiler Design'));
  check('document.title followed the navigation',
    document.title.startsWith('CMPUT 415'), document.title);
  await act(async () => {
    dom.window.dispatchEvent(new dom.window.Event('beforeprint'));
  });
  check('print filename is CMPUT415_Graph, not the first course viewed',
    document.title === 'CMPUT415_Graph', document.title);
  await act(async () => {
    dom.window.dispatchEvent(new dom.window.Event('afterprint'));
  });
  check('title restored after print', document.title.startsWith('CMPUT 415'));
}

console.log('LEVEL_MIN and external leaves read correctly');
{
  const t = text();
  check('level constraint is spelled out', t.includes('any 300-level CMPUT course'));
  check('external courses flagged for the reader',
    t.includes('not tracked in this dataset'));
}

console.log('MATH renders alongside CMPUT (Phase 5)');
{
  // Past 8 subjects the chip row becomes a select (see App.jsx).
  const chips = [...container.querySelectorAll('button')]
    .filter((b) => ['All', 'CMPUT', 'MATH'].includes(b.textContent.trim()));
  const picker = container.querySelector('select[aria-label="Filter by subject"]');
  const subjectCount = new Set(COURSES.courses.map((c) => c.subject)).size;
  if (subjectCount > 8) {
    check('subject filter is a select at Faculty scale', Boolean(picker));
    check('select lists every subject plus All',
      picker && picker.options.length === subjectCount + 1,
      picker && 'got ' + picker.options.length + ' for ' + subjectCount + ' subjects');
  } else {
    check('subject filter offers a chip per subject',
      chips.length === 3, 'got ' + chips.length);
  }

  await type(container.querySelector('input[aria-label="Search courses"]'), 'MATH 336');
  await click((b) => b.textContent.includes('MATH 336'));
  const t = text();
  check('MATH 336 rendered', t.includes('MATH 336'));
  check('nested "both 214 and 216" shows an ALL group inside an ANY group',
    t.includes('ALL of these') && t.includes('ANY ONE of these'));
  check('print filename follows into MATH',
    document.title.startsWith('MATH 336'), document.title);

  // "Prerequisite or corequisite" must surface as take-alongside, not a gate.
  await type(container.querySelector('input[aria-label="Search courses"]'), 'MATH 102');
  await click((b) => b.textContent.includes('MATH 102'));
  check('MATH 102 shows its corequisite',
    text().includes('Take alongside'), text().slice(0, 200));
}

console.log('an unparsed course never claims it has no prerequisites');
{
  await type(container.querySelector('input[aria-label="Search courses"]'), 'MATH 422');
  await click((b) => b.textContent.includes('MATH 422'));
  const t = text();
  check('MATH 422 flagged not machine-readable', t.includes('not machine-readable'));
  check('does NOT say "No prerequisites."', !t.includes('No prerequisites.'), t.slice(0, 300));
  check('tells the reader to use the calendar text',
    t.includes('could not be read automatically'));
  check('raw calendar text is still shown',
    t.includes('MATH 226 and a 300-level MATH course'));

  // It must NOT claim eligibility for a course it cannot read.
  check('does not claim the prerequisites are satisfied',
    !t.includes('satisfy the prerequisites'), t.slice(0, 300));
  check('says plainly that it cannot judge eligibility',
    t.includes('cannot tell you whether you are eligible'));

  // ...and must hand the reader the official page instead of a promise.
  const link = [...container.querySelectorAll('a')]
    .find((a) => a.textContent.includes('official UAlberta catalogue'));
  check('offers a link to the official catalogue entry', Boolean(link));
  check('the link points at this course’s own page',
    link && link.getAttribute('href').includes('/math/422'),
    link && link.getAttribute('href'));
  check('the link opens safely in a new tab',
    link && link.getAttribute('rel').includes('noopener'), true);
}

console.log('a partial course with an unrepresented requirement warns too');
{
  await type(container.querySelector('input[aria-label="Search courses"]'), 'MATH 570');
  await click((b) => b.textContent.includes('MATH 570'));
  const t = text();
  check('MATH 570 warns the tree is incomplete',
    t.includes('not shown below'), t.slice(0, 260));
  check('MATH 570 names the requirement it could not represent',
    t.includes('Partial Differential Equations'));
  check('MATH 570 links to the catalogue',
    [...container.querySelectorAll('a')].some((a) =>
      a.textContent.includes('official UAlberta catalogue')));
}

console.log('a clean course shows no catalogue-fallback banner');
{
  await type(container.querySelector('input[aria-label="Search courses"]'), 'CMPUT 301');
  await click((b) => b.textContent.includes('CMPUT 301') && b.textContent.includes('Software'));
  const t = text();
  // Crying wolf on every course would train people to ignore the banner.
  check('no fallback banner on a cleanly parsed course',
    !t.includes('could not be read automatically') && !t.includes('not shown below'),
    t.slice(0, 200));
}

console.log('corequisites render on one line, not as a tree');
{
  const coreqSection = () =>
    [...container.querySelectorAll('section')]
      .find((s) => s.textContent.includes('Take alongside'));

  // MATH 209: a single corequisite (MATH 102). A whole tree block for one
  // course is what prompted this; it should read as one line.
  await type(container.querySelector('input[aria-label="Search courses"]'), 'MATH 209');
  await click((b) => b.textContent.includes('MATH 209'));
  let sec = coreqSection();
  check('single corequisite section exists', Boolean(sec));
  check('single corequisite names the course', sec.textContent.includes('MATH 102'));
  check('single corequisite drops the ANY ONE / ALL header',
    !sec.textContent.includes('ANY ONE of these') && !sec.textContent.includes('ALL of these'),
    sec.textContent.slice(0, 160));

  // CMPUT 261: a two-way choice. The joining word carries the logic, so it has
  // to be visible inline rather than implied by a header further up.
  await type(container.querySelector('input[aria-label="Search courses"]'), 'CMPUT 261');
  await click((b) => b.textContent.includes('CMPUT 261'));
  sec = coreqSection();
  check('two-way corequisite lists both options',
    sec.textContent.includes('CMPUT 204') && sec.textContent.includes('CMPUT 275'));
  check('two-way corequisite spells out the joining word inline',
    /CMPUT 204\s*or\s*CMPUT 275/.test(sec.textContent.replace(/\s+/g, ' ')),
    sec.textContent.replace(/\s+/g, ' ').slice(0, 160));
  check('two-way corequisite still drops the tree header',
    !sec.textContent.includes('ANY ONE of these'), sec.textContent.slice(0, 160));

  // The prerequisite tree must be untouched -- it genuinely needs the headers.
  check('prerequisite tree keeps its grouping headers',
    text().includes('ANY ONE of these') || text().includes('ALL of these'));

  // The inline form is only safe for a one-level tree. No course in today's
  // data nests its corequisites, but the catalogue may next term, and
  // flattening a nested one would silently change what it means.
  const { isFlat } = await import('./components/CoreqLine.jsx');
  const C_ = (code) => ({ type: 'COURSE', code, external: false });
  // NOTE: this file's `check` takes a boolean condition, not an expected value.
  check('isFlat: single course', isFlat(C_('MATH 447')) === true);
  check('isFlat: flat OR', isFlat({ type: 'OR', children: [C_('A 1'), C_('B 2')] }) === true);
  check('isFlat: level constraint',
    isFlat({ type: 'LEVEL_MIN', subject: 'MATH', min_level: 300 }) === true);
  check('isFlat: nested tree falls back to the full tree renderer',
    isFlat({
      type: 'AND',
      children: [C_('A 1'), { type: 'OR', children: [C_('B 2'), C_('C 3')] }],
    }) === false);
  check('isFlat: nothing', isFlat(null) === false);
}

console.log('printable outline has the structure the tree guides need');
{
  // MATH 115 has a deep chain (115 -> 100/114/117/... -> high-school courses),
  // which is exactly the case where indentation alone stops being readable.
  await type(container.querySelector('input[aria-label="Search courses"]'), 'MATH 115');
  await click((b) => b.textContent.includes('MATH 115'));

  const outline = container.querySelector('.print-outline');
  check('print outline is rendered', Boolean(outline));

  const trees = outline.querySelectorAll('.print-tree');
  check('prerequisite tree is wrapped for guide styling', trees.length >= 1);

  // The guides are drawn on `ul ul > li`, so nesting must be real <ul> nesting.
  const nested = outline.querySelectorAll('.print-tree ul ul > li');
  check('nested list items exist for guides to attach to', nested.length > 0);

  // "which itself needs:" is a caption, not a requirement -- if it were an <li>
  // it would draw its own elbow and read as a prerequisite.
  const captions = outline.querySelectorAll('.print-caption');
  check('sub-tree captions are present', captions.length > 0);
  check('no caption is a list item',
    [...captions].every((c) => c.tagName !== 'LI'), true);
  check('captions sit outside the nested list',
    [...captions].every((c) => c.parentElement.tagName !== 'UL'), true);

  // The tree rules set list-style:none; the plain lists must keep their bullets.
  const discLists = outline.querySelectorAll('ul.list-disc');
  check('plain bulleted lists are outside .print-tree',
    [...discLists].every((u) => !u.closest('.print-tree')), true);
}

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
