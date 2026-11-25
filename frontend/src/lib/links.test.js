/**
 * Tests for links.js -- plain node, no install:  node src/lib/links.test.js
 */
import { safeHref, codeFromHash, hashForCode } from './links.js';

let passed = 0;
let failed = 0;
function check(name, actual, expected) {
  if (JSON.stringify(actual) === JSON.stringify(expected)) {
    passed += 1;
    console.log('  ok   ' + name);
  } else {
    failed += 1;
    console.log('  FAIL ' + name + '\n       expected: ' + JSON.stringify(expected) +
      '\n       actual:   ' + JSON.stringify(actual));
  }
}

console.log('safeHref only lets https through');
check('catalogue URL kept', safeHref('https://apps.ualberta.ca/catalogue/course/cmput/301'),
  'https://apps.ualberta.ca/catalogue/course/cmput/301');
check('javascript: dropped', safeHref('javascript:alert(1)'), undefined);
check('JaVaScRiPt: with whitespace dropped', safeHref('  JaVaScRiPt:alert(1)'), undefined);
check('data: dropped', safeHref('data:text/html,<script>1</script>'), undefined);
check('plain http dropped', safeHref('http://apps.ualberta.ca/'), undefined);
check('garbage dropped', safeHref('not a url'), undefined);
check('missing dropped', safeHref(undefined), undefined);

console.log('hash route round-trips course codes');
for (const code of ['CMPUT 301', 'E E 380', 'MA PH 351', 'CMPUT 296A', 'MATH 30-1']) {
  check('round trip ' + code, codeFromHash(hashForCode(code)), code);
}
check('no hash', codeFromHash(''), null);
check('unrelated hash', codeFromHash('#top'), null);
check('malformed escape does not throw', codeFromHash('#/course/%E0%A4%A'), null);
check('empty code has no hash', hashForCode(null), '');

console.log('\n' + passed + ' passed, ' + failed + ' failed');
process.exit(failed ? 1 : 0);
