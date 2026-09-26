// Lint rules that carry spec rules: R3 (text-only rendering) and R2 (read-only, one HTTP module).
import js from "@eslint/js";
import globals from "globals";
import react from "eslint-plugin-react";
import reactHooks from "eslint-plugin-react-hooks";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["node_modules", "test-results", "playwright-report", ".tmp"] },
  js.configs.recommended,
  ...tseslint.configs.strictTypeChecked,
  {
    languageOptions: {
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
      globals: { ...globals.browser },
    },
  },
  {
    files: ["src/**/*.{ts,tsx}", "tests/**/*.{ts,tsx}"],
    plugins: { react, "react-hooks": reactHooks },
    settings: { react: { version: "19" } },
    rules: {
      ...react.configs.recommended.rules,
      ...react.configs["jsx-runtime"].rules,
      ...reactHooks.configs.recommended.rules,
      // R3: no HTML sinks anywhere in the app.
      "react/no-danger": "error",
      "react/no-danger-with-children": "error",
      "no-restricted-syntax": [
        "error",
        { selector: "MemberExpression[property.name=/^(innerHTML|outerHTML)$/]", message: "R3: render text, never HTML." },
        { selector: "CallExpression[callee.property.name='insertAdjacentHTML']", message: "R3: render text, never HTML." },
        { selector: "CallExpression[callee.property.name='write'][callee.object.name='document']", message: "R3: render text, never HTML." },
      ],
    },
  },
  {
    // R2: only src/fhir/http.ts may touch the network, and it only issues GET.
    files: ["src/**/*.{ts,tsx}"],
    ignores: ["src/fhir/http.ts"],
    rules: {
      "no-restricted-globals": [
        "error",
        { name: "fetch", message: "R2: go through src/fhir/http.ts (GET only)." },
        { name: "XMLHttpRequest", message: "R2: go through src/fhir/http.ts (GET only)." },
      ],
    },
  },
  {
    files: ["e2e/**/*.ts", "*.config.{ts,js}"],
    languageOptions: { globals: { ...globals.node } },
  },
  {
    files: ["eslint.config.js", "**/*.mjs"],
    extends: [tseslint.configs.disableTypeChecked],
    languageOptions: { globals: { ...globals.node } },
  },
);
