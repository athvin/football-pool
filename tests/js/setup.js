/**
 * jsdom does not implement `window.matchMedia`, which every real browser has.
 * The site module self-initialises on import, so the stub has to exist before
 * any test file imports it.
 *
 * Tests that care about media queries pass their own fake window to `init()`;
 * this only keeps the import-time bootstrap from throwing.
 */
if (typeof window !== 'undefined' && !window.matchMedia) {
  window.matchMedia = (query) => ({
    media: query,
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
    dispatchEvent: () => false,
  });
}
