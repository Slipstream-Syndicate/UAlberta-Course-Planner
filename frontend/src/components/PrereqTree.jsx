import React from 'react';

/**
 * The on-screen prerequisite tree.
 *
 * Rendered from the ANNOTATED tree the eval engine returns, so satisfied and
 * unsatisfied branches are styled from real evaluation rather than re-derived
 * here. With an empty completed list nothing is green and the whole chain
 * shows -- which is exactly the "here is the full chain from scratch" view a
 * prospective student wants (CLAUDE.md "Audience & access").
 *
 * Everything rendered here is plain text through JSX, which React escapes.
 * No dangerouslySetInnerHTML anywhere on scraped fields (CLAUDE.md security).
 */

const JOIN_LABEL = {
  AND: 'ALL of these',
  OR: 'ANY ONE of these',
};

export function Chip({ tone, children }) {
  const tones = {
    done: 'bg-emerald-100 text-emerald-900 border-emerald-300',
    todo: 'bg-white text-slate-800 border-slate-300',
    external: 'bg-amber-50 text-amber-900 border-amber-300',
    error: 'bg-rose-100 text-rose-900 border-rose-300',
  };
  return (
    <span className={'inline-flex items-center gap-1.5 rounded-md border px-2 py-1 text-sm font-medium ' + tones[tone]}>
      {children}
    </span>
  );
}

function Node({ node, onSelect, depth = 0, unparsed = false }) {
  if (!node || node.type === 'EMPTY') {
    // "No prerequisites" and "we could not read the prerequisites" are opposite
    // claims. Saying the first when the second is true tells a student a gated
    // course is wide open -- so the caller passes `unparsed` and we say which.
    return unparsed ? (
      <p className="text-sm text-amber-800">
        These prerequisites could not be read automatically. Use the calendar text above.
      </p>
    ) : (
      <p className="text-sm text-slate-600">No prerequisites.</p>
    );
  }

  if (node.error) {
    return (
      <Chip tone="error">
        <span aria-hidden="true">!</span>
        {node.code || node.type} — {node.error}
      </Chip>
    );
  }

  if (node.type === 'COURSE') {
    const external = node.external;
    const tone = node.satisfied ? 'done' : external ? 'external' : 'todo';
    return (
      <div>
        <span className="inline-flex flex-wrap items-center gap-2">
          {external ? (
            <Chip tone={tone}>
              {node.satisfied ? '✓ ' : ''}
              {node.code}
            </Chip>
          ) : (
            <button
              type="button"
              onClick={() => onSelect(node.code)}
              className="rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
              title={'View ' + node.code}
            >
              <Chip tone={tone}>
                {node.satisfied ? '✓ ' : ''}
                {node.code}
              </Chip>
            </button>
          )}
          {external && (
            <span className="text-xs text-amber-800">
              not tracked in this dataset — verify eligibility yourself
            </span>
          )}
          {node.parseStatus && node.parseStatus !== 'parsed' && (
            <span className="text-xs text-amber-800">
              ({node.parseStatus} parse — check its raw text)
            </span>
          )}
        </span>

        {/* The deeper chain: what it would take to unlock this course too. */}
        {node.chain && !node.satisfied && (
          <div className="mt-2 border-l-2 border-slate-200 pl-4">
            <p className="mb-1 text-xs uppercase tracking-wide text-slate-500">
              which itself needs
            </p>
            <Node node={node.chain} onSelect={onSelect} depth={depth + 1} />
          </div>
        )}
      </div>
    );
  }

  if (node.type === 'LEVEL_MIN') {
    return (
      <Chip tone={node.satisfied ? 'done' : 'todo'}>
        {node.satisfied ? '✓ ' : ''}
        any {node.min_level}-level {node.subject} course
        {node.satisfiedBy ? ' (' + node.satisfiedBy + ')' : ''}
      </Chip>
    );
  }

  return (
    <div>
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
        {JOIN_LABEL[node.type]}
        {node.satisfied && <span className="ml-2 text-emerald-700">satisfied</span>}
      </p>
      <ul className="space-y-2 border-l-2 border-slate-200 pl-4">
        {node.children.map((child, i) => (
          <li key={i}>
            <Node node={child} onSelect={onSelect} depth={depth + 1} />
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function PrereqTree({ node, onSelect, unparsed = false }) {
  return <Node node={node} onSelect={onSelect} unparsed={unparsed} />;
}
