import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    include: ['tests/js/**/*.test.js'],
    setupFiles: ['tests/js/setup.js'],
    coverage: {
      provider: 'v8',
      include: ['assets/**/*.js'],
      reporter: ['text', 'lcov'],
      // Coverage is a gate, matching the Python side. CI fails below these and
      // the Pages deploy is gated on CI.
      thresholds: {
        statements: 90,
        branches: 85,
        functions: 90,
        lines: 90,
      },
    },
  },
});
