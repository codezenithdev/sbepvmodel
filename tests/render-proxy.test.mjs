import assert from "node:assert/strict";
import test from "node:test";

import { isAllowedApiPath } from "../lib/render-proxy.ts";

const allowedAutonomyRoutes = [
  ["autonomy", "cases"],
  ["autonomy", "sources"],
  ["autonomy", "cases", "case_abc123"],
  ["autonomy", "cases", "case_abc123", "events"],
  ["autonomy", "cases", "case_abc123", "messages"],
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
  ["autonomy", "cases", "case_abc123", "scenarios"],
  ["autonomy", "cases", "case_abc123", "confirm"],
  ["autonomy", "cases", "case_abc123", "signoff"],
  ["autonomy", "cases", "case_abc123", "reports"],
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

test("allows only the Autonomy case, readiness, message, and evidence phase", () => {
  for (const path of allowedAutonomyRoutes) {
    assert.equal(isAllowedApiPath(path), true, `expected allowed: ${path.join("/")}`);
  }
  for (const path of rejectedAutonomyRoutes) {
    assert.equal(isAllowedApiPath(path), false, `expected rejected: ${path.join("/")}`);
  }
});
