const DEFAULT_RENDER_ORIGIN = "https://sbepvmodel.onrender.com";

const REQUEST_HEADERS = ["accept", "content-type", "last-event-id", "range"] as const;
const RESPONSE_HEADERS = [
  "accept-ranges",
  "cache-control",
  "content-disposition",
  "content-length",
  "content-range",
  "content-type",
  "etag",
  "last-modified",
  "retry-after",
] as const;

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function jsonError(detail: string, status: number): Response {
  return Response.json({ detail }, { status });
}

function basicAuthorization(): string | null {
  const username = process.env.RENDER_BASIC_USER;
  const password = process.env.RENDER_BASIC_PASSWORD;
  if (!username || !password) return null;
  return `Basic ${Buffer.from(`${username}:${password}`, "utf8").toString("base64")}`;
}

function upstreamOrigin(): string {
  return (process.env.RENDER_BACKEND_ORIGIN || DEFAULT_RENDER_ORIGIN).replace(
    /\/$/,
    "",
  );
}

function safePath(path: string[]): string {
  return path.map((segment) => encodeURIComponent(segment)).join("/");
}

export function isAllowedApiPath(path: string[]): boolean {
  if (path.length === 1) {
    return [
      "session",
      "current-calibration",
      "run",
      "annual-run",
      "chat",
      "calibration-reviews",
      "saved-results",
    ].includes(path[0]);
  }

  const isSafeId = (value: string) => /^[a-zA-Z0-9_-]+$/.test(value);
  const isCaseId = (value: string) => /^case_[a-zA-Z0-9_-]+$/.test(value);
  const isEvidenceId = (value: string) => /^evi_[a-zA-Z0-9_-]+$/.test(value);
  const isScenarioId = (value: string) => /^dsc_[a-zA-Z0-9]+$/.test(value);
  const isTeaJobId = (value: string) => /^tea_[a-zA-Z0-9_-]+$/.test(value);
  const isTurnId = (value: string) => /^(?:turn_|dturn_)[a-zA-Z0-9_-]+$/.test(value);
  const isComparisonBundleId = (value: string) => /^dcmp_[a-zA-Z0-9]+$/.test(value);
  const isDecisionBriefRevisionId = (value: string) => /^dbr_[a-zA-Z0-9]+$/.test(value);
  if (path.length === 2) {
    return (
      (path[0] === "status" && isSafeId(path[1])) ||
      (path[0] === "agent" && path[1] === "state") ||
      (path[0] === "saved-results" && isSafeId(path[1])) ||
      (
        path[0] === "technoeconomic" &&
        ["sources", "jobs"].includes(path[1])
      ) ||
      (path[0] === "autonomy" && ["cases", "sources"].includes(path[1]))
    );
  }

  if (path.length === 3) {
    return (
      (
        path[0] === "jobs" &&
        isSafeId(path[1]) &&
        ["cancel", "delete", "promote", "retry"].includes(path[2])
      ) ||
      (
        path[0] === "calibration-reviews" &&
        isSafeId(path[1]) &&
        ["run", "rows"].includes(path[2])
      ) ||
      (
        path[0] === "technoeconomic" &&
        path[1] === "jobs" &&
        isSafeId(path[2])
      ) ||
      (
        path[0] === "autonomy" &&
        path[1] === "cases" &&
        isCaseId(path[2])
      )
    );
  }

  if (path.length === 4) {
    return (
      (
        path[0] === "agent" &&
        isSafeId(path[2]) &&
        (
          (
            path[1] === "proposals" &&
            ["confirm", "edit", "dismiss"].includes(path[3])
          ) ||
          (path[1] === "sweeps" && path[3] === "confirm")
        )
      ) ||
      (
        path[0] === "technoeconomic" &&
        path[1] === "jobs" &&
        isSafeId(path[2]) &&
        ["cancel", "retry"].includes(path[3])
      ) ||
      (
        path[0] === "autonomy" &&
        path[1] === "cases" &&
        isCaseId(path[2]) &&
        [
          "events",
          "messages",
          "evidence",
          "scenarios",
          "execution",
          "comparison-bundles",
          "decision-briefs",
        ].includes(path[3])
      )
    );
  }

  if (path.length === 5) {
    return (
      path[0] === "technoeconomic" &&
      path[1] === "jobs" &&
      isSafeId(path[2]) &&
      (
        (
          path[3] === "exports" &&
          ["csv", "xlsx"].includes(path[4])
        ) ||
        (
          path[3] === "artifacts" &&
          [
            "cdf_plot",
            "sensitivity_plot",
            "convergence_plot",
          ].includes(path[4])
        )
      )
    ) || (
      path[0] === "autonomy" &&
      path[1] === "cases" &&
      isCaseId(path[2]) &&
      (
        (path[3] === "readiness" && path[4] === "evaluate") ||
        (path[3] === "message-stream" && isTurnId(path[4])) ||
        (path[3] === "evidence" && isEvidenceId(path[4])) ||
        (path[3] === "scenarios" && ["compare", "confirm"].includes(path[4])) ||
        (path[3] === "comparison-bundles" && isComparisonBundleId(path[4])) ||
        (path[3] === "decision-briefs" && isDecisionBriefRevisionId(path[4]))
      )
    );
  }

  if (path.length === 6) {
    return (
      path[0] === "autonomy" &&
      path[1] === "cases" &&
      isCaseId(path[2]) &&
      (
        (
          path[3] === "evidence" &&
          isEvidenceId(path[4]) &&
          path[5] === "download"
        ) ||
        (
          path[3] === "scenarios" &&
          isScenarioId(path[4]) &&
          ["revisions", "validate", "expire"].includes(path[5])
        ) ||
        (
          path[3] === "execution" &&
          isTeaJobId(path[4]) &&
          ["cancel", "retry"].includes(path[5])
        )
      )
    );
  }

  if (path.length === 8) {
    return (
      path[0] === "autonomy" &&
      path[1] === "cases" &&
      isCaseId(path[2]) &&
      path[3] === "evidence" &&
      isEvidenceId(path[4]) &&
      path[5] === "candidates" &&
      isSafeId(path[6]) &&
      path[7] === "review"
    );
  }

  return false;
}

export async function proxyRenderRequest(
  request: Request,
  context: RouteContext,
  prefix: "api" | "outputs",
): Promise<Response> {
  const authorization = basicAuthorization();
  if (!authorization) {
    return jsonError("The dashboard connection is not configured yet.", 503);
  }

  const { path } = await context.params;
  if (prefix === "api" && !isAllowedApiPath(path || [])) {
    return jsonError("Unknown dashboard endpoint.", 404);
  }
  const incomingUrl = new URL(request.url);
  const targetUrl = new URL(
    `/${prefix}/${safePath(path || [])}${incomingUrl.search}`,
    `${upstreamOrigin()}/`,
  );

  const headers = new Headers();
  for (const name of REQUEST_HEADERS) {
    const value = request.headers.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("authorization", authorization);

  const method = request.method.toUpperCase();
  const init: RequestInit = {
    method,
    headers,
    redirect: "follow",
  };
  if (method !== "GET" && method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  let upstream: Response;
  try {
    upstream = await fetch(targetUrl, init);
  } catch {
    return jsonError("The dashboard backend is temporarily unavailable.", 502);
  }

  if (upstream.status === 401) {
    return jsonError("The dashboard backend rejected the configured connection.", 502);
  }

  const responseHeaders = new Headers();
  for (const name of RESPONSE_HEADERS) {
    const value = upstream.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  responseHeaders.set("X-Content-Type-Options", "nosniff");

  return new Response(method === "HEAD" ? null : upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}
