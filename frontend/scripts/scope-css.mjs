import { readFile, writeFile } from 'node:fs/promises'
import postcss from 'postcss'
import prefixSelector from 'postcss-prefix-selector'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

// The Vite output is modern, flattened CSS. Keep both Tailwind's reset and its
// utilities inside React roots; the existing Bootstrap pages must be unaffected.
export async function scopeCss(destination = new URL('../../app/core/static/react/orders.css', import.meta.url)) {
  const file = destination instanceof URL ? destination : pathToFileURL(resolve(destination))
  const root = postcss.parse(await readFile(file, 'utf8'))
  root.walkAtRules('layer', rule => {
    if (rule.nodes) rule.replaceWith(rule.nodes)
    else rule.remove()
  })
  const result = await postcss([prefixSelector({
    prefix: '.lx-react',
    transform(prefix, selector, prefixedSelector) {
      if (selector === ':root' || selector === ':host' || selector === 'html' || selector === 'body') return prefix
      if (selector.startsWith('.lx-react')) return selector
      if (selector.startsWith('.lx-foundation')) return selector.replace(/^\.lx-foundation/, '.lx-react.lx-foundation')
      return prefixedSelector
    },
  })]).process(root, { from: file.pathname, map: false })
  await writeFile(file, result.css)
  console.log('Tailwind CSS scoped to React roots and Radix portals')
}

// Keep existing preview/CLI callers working; Vite can reuse this in-process.
if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  await scopeCss(process.argv[2])
}
