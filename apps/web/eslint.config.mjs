import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const config = [
  { ignores: [".next/**", "node_modules/**", "next-env.d.ts"] },
  ...nextCoreWebVitals,
  {
    rules: {
      // docs/design-system.md §10 — mechanised design rules. Raw HTML injection
      // is how the legacy prototype smuggled 4,000-character CSS strings into
      // components; this platform never does.
      "react/no-danger": "error",
    },
  },
];

export default config;
