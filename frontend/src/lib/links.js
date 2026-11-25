/**
 * URL helpers: safe outbound links and the course-in-the-URL hash route.
 *
 * Hash routing (`#/course/CMPUT%20301`) rather than path routing, because the
 * site is a static bundle served from any subpath (vite `base: './'`, GitHub
 * Pages) -- a hash never reaches the server, so no rewrite rule is needed and
 * a shared link or a browser refresh lands on the same course. It also makes
 * the back button move between viewed courses.
 */

/**
 * Only https links leave the page. Every href rendered from data goes through
 * this: the URLs come from the scrape, and a `javascript:` URL in a tampered
 * courses.json would otherwise execute on click (React warns about those but
 * does not block them).
 */
export function safeHref(url) {
  try {
    const u = new URL(String(url));
    return u.protocol === 'https:' ? u.href : undefined;
  } catch {
    return undefined;
  }
}

const HASH_RE = /^#\/course\/(.+)$/;

export function codeFromHash(hash) {
  const m = HASH_RE.exec(hash || '');
  if (!m) return null;
  try {
    return decodeURIComponent(m[1]);
  } catch {
    return null; // malformed escape: ignore rather than crash
  }
}

export function hashForCode(code) {
  return code ? '#/course/' + encodeURIComponent(code) : '';
}
