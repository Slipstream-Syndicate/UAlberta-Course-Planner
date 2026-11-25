import { describeRequirement, levelLabel } from '../lib/evalEngine.js';
import { isFlat } from './CoreqLine.jsx';

/** "MATH 209 or MATH 214", with the same [x]/[ ] convention as the outline. */
function flatToSentence(node) {
  const leaf = (n) => {
    const mark = n.satisfied ? '[x] ' : '[ ] ';
    if (n.type === 'LEVEL_MIN') {
      return mark + 'any ' + n.min_level + '-level ' + levelLabel(n) + ' course';
    }
    return mark + n.code + (n.external ? ' (not tracked here)' : '');
  };
  if (node.type === 'COURSE' || node.type === 'LEVEL_MIN') return leaf(node);
  return node.children.map(leaf).join(node.type === 'OR' ? '  or  ' : '  and  ');
}

/**
 * The print-only view (DESIGN.md "Export / printable view").
 *
 * An indented text outline, not the node-and-edge graph: outlines paginate,
 * graphs do not. Carries the same honesty the live page shows -- confidence
 * flag, raw prerequisite text whenever the parse is not clean, and the "not
 * official advising" line -- because on paper the reader has lost the ability
 * to glance at the app and judge for themselves.
 */

function OutlineNode({ node, unparsed = false }) {
  if (!node || node.type === 'EMPTY') {
    // On paper the reader cannot check the live app, so the difference between
    // "none" and "unreadable" matters even more here than on screen.
    return <li>{unparsed ? 'Could not be parsed — see the calendar text above.' : 'No prerequisites.'}</li>;
  }
  if (node.error) {
    return <li>[error] {node.error}</li>;
  }
  if (node.type === 'COURSE') {
    return (
      <li>
        {node.satisfied ? '[x] ' : '[ ] '}
        {node.code}
        {node.external ? ' — not tracked in this dataset; verify yourself' : ''}
        {node.cycle ? ' — loops back to a course already on this path; not a usable route here' : ''}
        {node.chain && !node.satisfied && (
          <>
            {/* Kept OUTSIDE the nested <ul> on purpose: it is a caption, not a
                requirement, so it should not get a tree elbow of its own. */}
            <div className="print-caption">which itself needs:</div>
            <ul>
              <OutlineNode node={node.chain} />
            </ul>
          </>
        )}
      </li>
    );
  }
  if (node.type === 'LEVEL_MIN') {
    return (
      <li>
        {node.satisfied ? '[x] ' : '[ ] '}
        any {node.min_level}-level {levelLabel(node)} course
      </li>
    );
  }
  return (
    <li>
      {node.type === 'AND' ? 'ALL of the following:' : 'ANY ONE of the following:'}
      <ul>
        {node.children.map((c, i) => (
          <OutlineNode key={i} node={c} />
        ))}
      </ul>
    </li>
  );
}

export default function PrintOutline({ result }) {
  const { course, prerequisite, corequisite, remaining, conflicts, blocked } = result;
  // The engine already defaults these; the printout must not crash on a
  // record that lacks them either.
  const notes = result.notes || course.notes || [];

  return (
    <div className="print-only print-outline">
      <h1 className="text-xl font-bold">
        {course.code} — {course.title}
      </h1>
      <p className="text-sm">
        {course.credits_text} · Source: {course.source_url}
      </p>

      {course.parse_status !== 'parsed' && (
        <div className="mt-2 border-2 border-black p-2 text-sm">
          <p>
            <strong>Confidence: {course.parse_status}.</strong>{' '}
            {course.parse_status === 'unparsed'
              ? 'This course’s prerequisites could not be read automatically, so no outline is shown below. That is a limitation of this tool — it does NOT mean the course has no prerequisites.'
              : 'This course’s prerequisites were only partly machine-readable. The calendar’s exact wording is reproduced below — trust it over the outline.'}
          </p>

          {(course.unrepresented_requirements || []).length > 0 && (
            <p className="mt-1">
              <strong>Not represented in the outline:</strong>{' '}
              {course.unrepresented_requirements.map((m) => '“' + m + '”').join('; ')}
            </p>
          )}

          {/* A printed page cannot be clicked, so the URL is spelled out in
              full rather than hidden behind link text. */}
          <p className="mt-1">
            <strong>Read the official entry:</strong> {course.source_url}
          </p>
        </div>
      )}

      <p className="mt-2 text-sm">
        <strong>Calendar text:</strong>{' '}
        {course.prerequisites_text || 'No prerequisite listed.'}
      </p>

      {blocked && (
        <p className="mt-2 text-sm">
          <strong>Credit restriction:</strong> you reported completing{' '}
          {conflicts.join(', ')}, which cannot be combined with {course.code}.
        </p>
      )}

      <h2 className="mt-4 font-semibold">Prerequisite outline</h2>
      <div className="print-tree">
        <ul>
          <OutlineNode node={prerequisite} unparsed={course.parse_status === 'unparsed'} />
        </ul>
      </div>

      {corequisite && (
        <>
          <h2 className="mt-4 font-semibold">Corequisites (take alongside, not before)</h2>
          {/* Same reasoning as on screen: corequisites are almost always a
              single course or a two-way choice, so a one-line sentence beats a
              nested outline. Only a genuinely nested one gets the tree. */}
          {isFlat(corequisite) ? (
            <p className="text-sm">{flatToSentence(corequisite)}</p>
          ) : (
            <div className="print-tree">
              <ul>
                <OutlineNode node={corequisite} />
              </ul>
            </div>
          )}
        </>
      )}

      {remaining.length > 0 && (
        <>
          <h2 className="mt-4 font-semibold">Shortest remaining path</h2>
          <ul className="ml-5 list-disc">
            {remaining.map((r, i) => (
              <li key={i}>{describeRequirement(r)}</li>
            ))}
          </ul>
        </>
      )}

      {notes.length > 0 && (
        <>
          <h2 className="mt-4 font-semibold">Notes not modelled in the diagram</h2>
          <ul className="ml-5 list-disc">
            {notes.map((n, i) => (
              <li key={i}>{n}</li>
            ))}
          </ul>
        </>
      )}

      <p className="mt-6 border-t border-black pt-2 text-xs">
        <strong>This is not official academic advising.</strong> It is a planning aid
        built from a scrape of the UAlberta course catalogue; parsing errors and stale
        data are possible. Term availability is not covered here at all. Verify against
        the official calendar and speak to an advisor before registering.
      </p>
    </div>
  );
}
