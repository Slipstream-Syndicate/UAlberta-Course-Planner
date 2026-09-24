import { useEffect } from 'react';

/**
 * Drive the document title, including the filename the browser suggests in its
 * "Save as PDF" dialog (CLAUDE.md "Export / printable view").
 *
 * There is no filesystem API behind a print dialog. The mechanism is that
 * browsers derive the suggested filename from `document.title` at print time,
 * so we swap the title on `beforeprint` and restore it on `afterprint`. That
 * is implementation behaviour, well supported in Chrome/Edge and generally
 * respected by Firefox -- a solid default, not a spec guarantee.
 *
 * THE BUG THIS IS SHAPED TO AVOID
 * -------------------------------
 * This is a client-side-routed SPA, so moving from one course to another does
 * NOT re-run title-setting code the way a full page load would. With no
 * dependency array (or one missing `code`), this effect would fire once for
 * whichever course mounted first and then stay stuck -- genuinely producing
 * CMPUT229_Graph.pdf for every course viewed afterwards.
 *
 * So `code` is an explicit dependency, and both the on-screen title and the
 * print filename are derived from the SAME `course.code` the page header
 * renders. One source of truth: editing one cannot drift from the other.
 */
export const APP_TITLE = 'CMPUT Prerequisite Explorer';

/** The one place the print filename is computed, from the same course.code
 *  that drives the on-page header. */
export function printFilenameFor(code) {
  return code.replace(/\s+/g, '') + '_Graph';
}

export function normalTitleFor(code) {
  return code + ' prerequisites — ' + APP_TITLE;
}

/**
 * The effect body, extracted so it can be exercised back-to-back for two
 * courses in a plain-node test with no browser and no React renderer.
 * Returns its own cleanup, exactly as the hook does.
 */
export function installPrintTitle(code, doc = document, win = window) {
  if (!code) {
    doc.title = APP_TITLE;
    return () => {};
  }

  const normalTitle = normalTitleFor(code);
  const printTitle = printFilenameFor(code);
  doc.title = normalTitle;

  const onBeforePrint = () => {
    doc.title = printTitle;
  };
  const onAfterPrint = () => {
    doc.title = normalTitle;
  };

  win.addEventListener('beforeprint', onBeforePrint);
  win.addEventListener('afterprint', onAfterPrint);

  return () => {
    win.removeEventListener('beforeprint', onBeforePrint);
    win.removeEventListener('afterprint', onAfterPrint);
    doc.title = APP_TITLE;
  };
}

export function usePrintTitle(code) {
  // The dependency array MUST contain `code`. test_print_title asserts this
  // literally against the source text, because an empty array here is silent
  // at runtime and only shows up as every course exporting the first course's
  // filename.
  useEffect(() => installPrintTitle(code), [code]);
}
