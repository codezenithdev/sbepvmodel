import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

export default defineConfig([
  ...nextVitals,
  ...nextTs,
  {
    // These files are concatenated into one classic script in filename order.
    // Treat their top-level declarations as shared globals while continuing to
    // report unused locals inside functions and other meaningful lint issues.
    files: ["frontend/js/**/*.js"],
    languageOptions: {
      sourceType: "script",
      parserOptions: {
        sourceType: "script",
      },
    },
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "warn",
        {
          vars: "local",
          args: "after-used",
          argsIgnorePattern: "^_",
          caughtErrors: "all",
          caughtErrorsIgnorePattern: "^_",
          destructuredArrayIgnorePattern: "^_",
          ignoreRestSiblings: true,
        },
      ],
    },
  },
  globalIgnores([
    ".next/**",
    "dist/**",
    "node_modules/**",
    "next-env.d.ts",
  ]),
]);
