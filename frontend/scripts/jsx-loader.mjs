// Node ESM loader: compiles .jsx on import so the render test can mount the
// real App components without a bundler step. Node has no built-in .jsx
// handling, so both hooks are needed -- `resolve` to claim the extension as an
// ES module, `load` to read and transform it before Node tries to.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { transformSync } from 'esbuild';

export async function resolve(specifier, context, nextResolve) {
  const resolved = await nextResolve(specifier, context);
  if (resolved.url.endsWith('.jsx')) {
    return { ...resolved, format: 'module', shortCircuit: true };
  }
  return resolved;
}

export async function load(url, context, nextLoad) {
  if (url.endsWith('.jsx')) {
    const source = readFileSync(fileURLToPath(url), 'utf8');
    const { code } = transformSync(source, {
      loader: 'jsx',
      format: 'esm',
      jsx: 'automatic',
    });
    return { format: 'module', source: code, shortCircuit: true };
  }
  return nextLoad(url, context);
}
