import type { Plugin } from 'vite'

/** Move Radix Select's static scrollbar stylesheet into our self-hosted CSS.
 * No primitive behavior is changed. Fail closed if an upstream update changes
 * the expected injector, so CSP compatibility must be reviewed on upgrades.
 */
export function radixCsp(): Plugin {
  return {
    name: 'radix-select-external-css',
    enforce: 'pre',
    transform(source, id) {
      if (!id.replaceAll('\\', '/').endsWith('/@radix-ui/react-select/dist/index.mjs')) return
      const start = source.indexOf('/* @__PURE__ */ jsx(\n        "style",')
      const end = source.indexOf('/* @__PURE__ */ jsx(Collection.Slot', start)
      if (start < 0 || end < 0 || !source.slice(start, end).includes('[data-radix-select-viewport]')) {
        throw new Error('Radix Select changed: review its CSP stylesheet adapter before building.')
      }
      return { code: source.slice(0, start) + 'null,\n      ' + source.slice(end), map: null }
    },
  }
}
