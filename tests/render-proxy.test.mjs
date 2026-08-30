import assert from "node:assert/strict";
import test from "node:test";

import { isAllowedApiPath } from "../lib/render-proxy.ts";

const allowedAutonomyRoutes = [
  ["autonomy", "cases"],
  ["autonomy", "sources"],
  ["autonomy", "cases", "case_abc123"],
  ["autonomy", "cases", "case_abc123", "events"],
  ["autonomy", "cases", "case_abc123", "messages"],
  ["autonomy", "cases", "case_abc123", "scenarios"],
  ["autonomy", "cases", "case_abc123", "scenarios", "compare"],
  ["autonomy", "cases", "case_abc123", "scenarios", "confirm"],
  ["autonomy", "cases", "case_abc123", "scenarios", "dsc_abc123", "revisions"],
  ["autonomy", "cases", "case_abc123", "scenarios", "dsc_abc123", "validate"],
  ["autonomy", "cases", "case_abc123", "scenarios", "dsc_abc123", "expire"],
  ["autonomy", "cases", "case_abc123", "execution"],
  ["autonomy", "cases", "case_abc123", "comparison-bundles"],
  ["autonomy", "cases", "case_abc123", "comparison-bundles", "dcmp_abc123"],
  ["autonomy", "cases", "case_abc123", "decision-briefs"],
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dbr_abc123"],
  ["autonomy", "cases", "case_abc123", "execution", "tea_abc-123", "cancel"],
  ["autonomy", "cases", "case_abc123", "execution", "tea_abc-123", "retry"],
  ["autonomy", "cases", "case_abc123", "readiness", "evaluate"],
  ["autonomy", "cases", "case_abc123", "message-stream", "turn_abc123"],
  ["autonomy", "cases", "case_abc123", "message-stream", "dturn_abc123"],
  ["autonomy", "cases", "case_abc123", "evidence"],
  ["autonomy", "cases", "case_abc123", "evidence", "evi_abc123"],
  ["autonomy", "cases", "case_abc123", "evidence", "evi_abc123", "download"],
  [
    "autonomy",
    "cases",
    "case_abc123",
    "evidence",
    "evi_abc123",
    "candidates",
    "evc_abc123",
    "review",
  ],
];

const rejectedAutonomyRoutes = [
  ["autonomy", "sources", "extra"],
  ["autonomy", ".."],
  ["autonomy", "cases", ".."],
  ["autonomy", "cases", "case_abc123", "confirm"],
  ["autonomy", "cases", "case_abc123", "signoff"],
  ["autonomy", "cases", "case_abc123", "reports"],
  ["autonomy", "cases", "case_abc123", "comparison-bundles", "dcmp_bad-id"],
  ["autonomy", "cases", "case_abc123", "comparison-bundles", "dbr_abc123"],
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dbr_bad-id"],
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dcmp_abc123"],
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dbr_abc123", "signoff"],
  ["autonomy", "cases", "case_abc123", "scenarios", "confirm", "extra"],
  ["autonomy", "cases", "case_abc123", "scenarios", "dsc_bad-id", "validate"],
  ["autonomy", "cases", "case_abc123", "scenarios", "..", "expire"],
  ["autonomy", "cases", "case_abc123", "execution", "job_abc123", "cancel"],
  ["autonomy", "cases", "case_abc123", "execution", "tea_abc123", "delete"],
  ["autonomy", "cases", "case_abc123", "message-stream", "unsafe"],
  ["autonomy", "cases", "case_abc123", "evidence", "..", "download"],
  [
    "autonomy",
    "cases",
    "case_abc123",
    "evidence",
    "evi_abc123",
    "candidates",
    "..",
    "review",
  ],
];

test("allows only the Autonomy evidence, scenario, execution, comparison, and brief routes", () => {
  for (const path of allowedAutonomyRoutes) {
    assert.equal(isAllowedApiPath(path), true, `expected allowed: ${path.join("/")}`);
  }
  for (const path of rejectedAutonomyRoutes) {
    assert.equal(isAllowedApiPath(path), false, `expected rejected: ${path.join("/")}`);
  }
});
