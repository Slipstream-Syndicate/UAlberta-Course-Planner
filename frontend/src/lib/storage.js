/**
 * Remembering the visitor's completed-courses list between visits.
 *
 * CLAUDE.md: no accounts, but localStorage buys the one convenience a login
 * would have -- and nothing leaves the browser. Every access is wrapped
 * because localStorage throws outright in some contexts (private windows with
 * site data blocked, embedded views), and a planning tool that white-screens
 * because storage is unavailable is worse than one that simply forgets.
 */

const KEY = 'cmput-prereq-explorer:completed';

export function loadCompleted() {
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.filter((c) => typeof c === 'string') : [];
  } catch {
    return [];
  }
}

export function saveCompleted(codes) {
  try {
    window.localStorage.setItem(KEY, JSON.stringify(codes));
  } catch {
    /* storage unavailable -- the app still works, it just forgets. */
  }
}
