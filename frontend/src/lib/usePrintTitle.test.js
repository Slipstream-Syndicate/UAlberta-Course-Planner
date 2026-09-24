/**
 * Phase 4 guard: the print filename must track the course being viewed.
 *
 * CLAUDE.md names the exact failure to test for -- viewing a second course in
 * this SPA silently keeping the first course's filename, "genuinely producing
 * CMPUT229_Graph.pdf for every course afterwards". So this views two courses
 * back-to-back and asserts the print title changes both times.
 *
 *     node frontend/src/lib/usePrintTitle.test.js
 */

import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

import {
  installPrintTitle,
  printFilenameFor,
  normalTitleFor,
  APP_TITLE,
} from './usePrintTitle.js';

const HERE = dirname(fileURLToPath(import.meta.url));

let passed = 0;
let failed = 0;

function check(name, actual, expected) {
  if (JSON.stringify(actual) === JSON.stringify(expected)) {
    passed += 1;
    console.log('  ok   ' + name);
  } else {
    failed += 1;
    console.log('  FAIL ' + name);
    console.log('       expected: ' + JSON.stringify(expected));
    console.log('       actual:   ' + JSON.stringify(actual));
  }
}

/** Minimal stand-ins for document/window. */
function makeEnv() {
  const listeners = {};
  return {
    doc: { title: '' },
    win: {
      addEventListener: (t, fn) => {
        (listeners[t] = listeners[t] || []).push(fn);
      },
      removeEventListener: (t, fn) => {
        listeners[t] = (listeners[t] || []).filter((f) => f !== fn);
      },
    },
    fire: (t) => (listeners[t] || []).forEach((fn) => fn()),
    countFor: (t) => (listeners[t] || []).length,
  };
}

console.log('filename derivation');
{
  check('space is stripped', printFilenameFor('CMPUT 229'), 'CMPUT229_Graph');
  check('multi-token subject collapses', printFilenameFor('E E 380'), 'EE380_Graph');
  check('letter suffix survives', printFilenameFor('CMPUT 174A'), 'CMPUT174A_Graph');
}

console.log('viewing two courses back-to-back updates the print title both times');
{
  const env = makeEnv();

  // First course mounts.
  let cleanup = installPrintTitle('CMPUT 229', env.doc, env.win);
  check('on-screen title is the first course', env.doc.title, normalTitleFor('CMPUT 229'));
  env.fire('beforeprint');
  check('print title is CMPUT229_Graph', env.doc.title, 'CMPUT229_Graph');
  env.fire('afterprint');
  check('title restored after printing', env.doc.title, normalTitleFor('CMPUT 229'));

  // Client-side navigation to a second course: effect re-runs.
  cleanup();
  cleanup = installPrintTitle('CMPUT 415', env.doc, env.win);
  check('on-screen title followed the navigation', env.doc.title, normalTitleFor('CMPUT 415'));
  env.fire('beforeprint');
  check(
    'print title is CMPUT415_Graph, NOT the first course',
    env.doc.title,
    'CMPUT415_Graph'
  );
  env.fire('afterprint');
  check('second course title restored', env.doc.title, normalTitleFor('CMPUT 415'));

  cleanup();
  check('cleanup removes both listeners',
    [env.countFor('beforeprint'), env.countFor('afterprint')], [0, 0]);
  check('cleanup restores the app title', env.doc.title, APP_TITLE);
}

console.log('the hook actually depends on `code`');
{
  // The back-to-back test above proves the effect BODY is correct, but it
  // supplies the re-run itself. The bug CLAUDE.md describes lives in the
  // dependency array, which only React can trigger -- so assert it directly.
  const src = readFileSync(resolve(HERE, 'usePrintTitle.js'), 'utf8');
  const m = src.match(/useEffect\([\s\S]*,\s*\[([^\]]*)\]\s*\)\s*;/);
  check('useEffect has a dependency array', Boolean(m), true);
  check('dependency array contains `code`', m && m[1].includes('code'), true);
}

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
