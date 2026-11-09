import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";

export default defineConfig([
  ...nextVitals,
  // Keep existing server-state synchronization visible while migrating the UI.
  // These React Compiler advisories do not change the established runtime behavior.
  { rules: { "react-hooks/set-state-in-effect": "warn", "react-hooks/purity": "warn" } },
  globalIgnores([".next/**", "out/**", "build/**", "next-env.d.ts"]),
]);
