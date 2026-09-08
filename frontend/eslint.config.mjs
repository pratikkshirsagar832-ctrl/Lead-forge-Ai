import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    rules: {
      // Legacy codebase: hundreds of `any` uses predate strict typing. Treat
      // them as warnings (lint stays actionable & CI-green) rather than errors;
      // new code should still prefer real types.
      "@typescript-eslint/no-explicit-any": "warn",
      // Next 16 ships the new React Compiler-era rules (react-hooks v6) as
      // errors. On this pre-existing codebase they fire on ordinary
      // fetch-on-mount patterns (set-state-in-effect) and common ref-mirror
      // idioms (refs), which are intentional here. Downgrade to warnings so
      // `npm run lint` stays usable; fix them as code is modernized.
      "react-hooks/set-state-in-effect": "warn",
      "react-hooks/refs": "warn",
    },
  },
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
  ]),
]);

export default eslintConfig;
