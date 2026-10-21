import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  globalIgnores([
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "public/**",
  ]),
  {
    rules: {
      // ── Enforced (error) ────────────────────────────────────────────
      // Hooks must follow rules — incorrect use causes subtle runtime bugs
      "react-hooks/rules-of-hooks": "error",

      // ── Warnings — fix these, don't add new violations ──────────────
      // No console.log in production code (console.error/warn allowed for real errors)
      "no-console": ["warn", { allow: ["error", "warn"] }],

      // No explicit `any` — use unknown or a typed interface
      "@typescript-eslint/no-explicit-any": "warn",

      // Exhaustive deps — missing deps cause stale closure bugs
      "react-hooks/exhaustive-deps": "warn",

      // Unused variables are dead code
      "@typescript-eslint/no-unused-vars": ["warn", {
        argsIgnorePattern: "^_",
        varsIgnorePattern: "^_",
        ignoreRestSiblings: true,
      }],

      // ── Disabled — tracked in refactor backlog, not actionable yet ──
      "react/no-unescaped-entities": "off",
      "@next/next/no-html-link-for-pages": "off",
      "react/display-name": "off",
      "@next/next/no-img-element": "off",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/static-components": "off",
    },
  },
  // Scripts can use console freely
  {
    files: ["scripts/**/*.ts", "scripts/**/*.js"],
    rules: {
      "no-console": "off",
    },
  },
]);

export default eslintConfig;
