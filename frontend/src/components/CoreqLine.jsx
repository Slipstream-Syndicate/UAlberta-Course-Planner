import React from 'react';
import PrereqTree, { Chip } from './PrereqTree.jsx';

/**
 * Corequisites, rendered on one horizontal line.
 *
 * Prerequisites genuinely need a tree -- they nest several levels and mix AND
 * with OR. Corequisites do not: across the scraped dataset, 16 of the 19
 * courses that have any are either a single course or a straight two-way
 * choice, and none nest at all. Stacking "ANY ONE of these" above a
 * single-item list spends a whole block of vertical space restating what
 * "MATH 447" already says.
 *
 * So a flat corequisite renders inline -- "MATH 209 or MATH 214" -- and only a
 * genuinely nested one falls back to the full tree. The fallback is not
 * currently reachable with real data; it exists because the catalogue is free
 * to get more complicated next term, and silently mis-rendering it would be
 * worse than an occasional tall block.
 */

/** True when the tree is one level deep, so it reads as a single sentence. */
export function isFlat(node) {
  if (!node) return false;
  if (node.type === 'COURSE' || node.type === 'LEVEL_MIN') return true;
  if (node.type === 'AND' || node.type === 'OR') {
    return node.children.every(
      (c) => c.type === 'COURSE' || c.type === 'LEVEL_MIN'
    );
  }
  return false;
}

function Leaf({ node, onSelect }) {
  if (node.type === 'LEVEL_MIN') {
    return (
      <Chip tone={node.satisfied ? 'done' : 'todo'}>
        {node.satisfied ? '✓ ' : ''}
        any {node.min_level}-level {node.subject} course
      </Chip>
    );
  }

  const tone = node.satisfied ? 'done' : node.external ? 'external' : 'todo';
  const label = (
    <Chip tone={tone}>
      {node.satisfied ? '✓ ' : ''}
      {node.code}
    </Chip>
  );

  // External courses are not in the dataset, so there is nothing to navigate to.
  if (node.external) {
    return (
      <span className="inline-flex items-center gap-1.5">
        {label}
        <span className="text-xs text-amber-800">(not tracked here)</span>
      </span>
    );
  }

  return (
    <button
      type="button"
      onClick={() => onSelect(node.code)}
      className="rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
      title={'View ' + node.code}
    >
      {label}
    </button>
  );
}

export default function CoreqLine({ node, onSelect }) {
  if (!node || node.type === 'EMPTY') return null;

  if (!isFlat(node)) {
    return <PrereqTree node={node} onSelect={onSelect} />;
  }

  if (node.type === 'COURSE' || node.type === 'LEVEL_MIN') {
    return (
      <div className="flex flex-wrap items-center gap-2">
        <Leaf node={node} onSelect={onSelect} />
      </div>
    );
  }

  // The joining word carries the whole logic here, so it is spelled out rather
  // than left to a header the reader has to scroll back to.
  const joiner = node.type === 'OR' ? 'or' : 'and';

  return (
    <div className="flex flex-wrap items-center gap-2">
      {node.children.map((child, i) => (
        <React.Fragment key={i}>
          {i > 0 && (
            <span className="text-sm font-medium text-blue-900">{joiner}</span>
          )}
          <Leaf node={child} onSelect={onSelect} />
        </React.Fragment>
      ))}
    </div>
  );
}
