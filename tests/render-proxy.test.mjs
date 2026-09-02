import assert from "node:assert/strict";
import test from "node:test";

import { isAllowedApiPath, proxyRenderRequest } from "../lib/render-proxy.ts";

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
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dbr_abc123", "signoffs"],
  ["autonomy", "cases", "case_abc123", "reports"],
  ["autonomy", "cases", "case_abc123", "reports", "drpt_abc123"],
  ["autonomy", "cases", "case_abc123", "reports", "drpt_abc123", "verify"],
  ["autonomy", "cases", "case_abc123", "reports", "drpt_abc123", "download"],
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
  ["autonomy", "cases", "case_abc123", "signoffs"],
  ["autonomy", "cases", "case_abc123", "comparison-bundles", "dcmp_bad-id"],
  ["autonomy", "cases", "case_abc123", "comparison-bundles", "dbr_abc123"],
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dbr_bad-id"],
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dcmp_abc123"],
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dbr_abc123", "signoff"],
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dbr_bad-id", "signoffs"],
  ["autonomy", "cases", "case_abc123", "decision-briefs", "dbr_abc123", "signoffs", "extra"],
  ["autonomy", "cases", "case_abc123", "reports", "drpt_bad-id"],
  ["autonomy", "cases", "case_abc123", "reports", "dsgn_abc123"],
  ["autonomy", "cases", "case_abc123", "reports", "drpt_abc123", "delete"],
  ["autonomy", "cases", "case_abc123", "reports", "..", "download"],
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

test("allows only the exact Autonomy evidence, execution, decision, sign-off, and report routes", () => {
  for (const path of allowedAutonomyRoutes) {
    assert.equal(isAllowedApiPath(path), true, `expected allowed: ${path.join("/")}`);
  }
  for (const path of rejectedAutonomyRoutes) {
    assert.equal(isAllowedApiPath(path), false, `expected rejected: ${path.join("/")}`);
  }
});

test("allows only exact standalone data collection routes", () => {
  const collectionId = "collect_0123456789abcdef01234567";
  for (const path of [
    ["data-collections"],
    ["data-collections", collectionId],
    ["data-collections", collectionId, "download"],
  ]) {
    assert.equal(isAllowedApiPath(path), true, `expected allowed: ${path.join("/")}`);
  }
  for (const path of [
    ["data-collections", "unsafe"],
    ["data-collections", collectionId, "delete"],
    ["data-collections", collectionId, "download", "extra"],
    ["data-collections", "collect_0123456789ABCDEF01234567"],
  ]) {
    assert.equal(isAllowedApiPath(path), false, `expected rejected: ${path.join("/")}`);
  }
});

test("proxy service credentials cannot authorize human sign-off", async () => {
  const originalFetch = globalThis.fetch;
  const originalUser = process.env.RENDER_BASIC_USER;
  const originalPassword = process.env.RENDER_BASIC_PASSWORD;
  let upstreamCalled = false;
  try {
    process.env.RENDER_BASIC_USER = "proxy-test-user";
    process.env.RENDER_BASIC_PASSWORD = "proxy-test-password";
    globalThis.fetch = async () => {
      upstreamCalled = true;
      return new Response("{}", { status: 201, headers: { "content-type": "application/json" } });
    };
    const request = new Request(
      "https://dashboard.test/api/autonomy/cases/case_abc123/decision-briefs/dbr_abc123/signoffs",
      {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "x-autonomy-human-action": "1",
          "x-untrusted-forward-me": "no",
        },
        body: "{}",
      },
    );
    const response = await proxyRenderRequest(
      request,
      { params: Promise.resolve({ path: ["autonomy", "cases", "case_abc123", "decision-briefs", "dbr_abc123", "signoffs"] }) },
      "api",
    );
    assert.equal(response.status, 403);
    assert.equal(upstreamCalled, false);
    assert.match(await response.text(), /directly authenticated backend/i);
  } finally {
    globalThis.fetch = originalFetch;
    if (originalUser === undefined) delete process.env.RENDER_BASIC_USER;
    else process.env.RENDER_BASIC_USER = originalUser;
    if (originalPassword === undefined) delete process.env.RENDER_BASIC_PASSWORD;
    else process.env.RENDER_BASIC_PASSWORD = originalPassword;
  }
});
