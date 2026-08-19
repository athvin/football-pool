/**
 * jsdom does not implement `window.matchMedia`, which every real browser has.
 * The site module self-initialises on import, so the stub has to exist before
 * any test file imports it.
 *
 * Tests that care about media queries pass their own fake window to `init()`;
 * this only keeps the import-time bootstrap from throwing.
 */
/**
 * jsdom has no canvas either, and its stub logs a page of "not implemented"
 * to stderr every time the field asks for a context. Returning null is what a
 * browser without canvas would do, and it is the branch the site is written
 * to survive — so this makes the intended path quiet instead of noisy.
 *
 * The drawing itself is tested directly against a recording context; nothing
 * here is standing in for that.
 */
if (typeof HTMLCanvasElement !== 'undefined') {
  HTMLCanvasElement.prototype.getContext = () => null;
}

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
