/**
 * Tailwind 4 uses the @tailwindcss/postcss plugin.
 * No tailwind.config.js — Tailwind 4 is config-less; theme tokens live in
 * `app/globals.css` under a `@theme` block.
 */
export default {
  plugins: {
    '@tailwindcss/postcss': {},
  },
};
