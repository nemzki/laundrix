import { readdir, readFile, writeFile } from 'node:fs/promises'
import postcss from 'postcss'
import prefixSelector from 'postcss-prefix-selector'
import { compile } from 'tailwindcss'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

// The Vite output is modern, flattened CSS. Keep both Tailwind's reset and its
// utilities inside React roots and keep the server-rendered styles isolated.
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

export async function buildFlaskCss() {
  const app = new URL('../../app/', import.meta.url)
  const files = await readdir(app, { recursive: true, withFileTypes: true })
  const sources = files.filter(file => file.isFile() && (
    file.name.endsWith('.html') ||
    (file.name.endsWith('.js') && /[\\/]static[\\/]js$/.test(file.parentPath))
  ))
  const contents = await Promise.all(sources.map(file =>
    readFile(resolve(file.parentPath, file.name), 'utf8'),
  ))
  const utilities = contents.flatMap(source => source.match(/\btw:[^\s"'<>]+/g) ?? [])
  const compiler = await compile(`
    @layer theme {
      @theme prefix(tw) {
        --spacing: .25rem;
        --text-xl: 1.25rem;
      }
    }
    @tailwind utilities;
  `)
  const css = compiler.build([...new Set(utilities)].sort())
  await writeFile(new URL('core/static/css/tailwind.css', app), css)
}

// Keep existing preview/CLI callers working; Vite can reuse this in-process.
if (process.argv[1] && fileURLToPath(import.meta.url) === resolve(process.argv[1])) {
  if (process.argv[2] === '--flask') await buildFlaskCss()
  else await scopeCss(process.argv[2])
}
