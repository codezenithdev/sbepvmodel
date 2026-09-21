const DEFAULT_RENDER_ORIGIN = "https://sbepvmodel.onrender.com";

const REQUEST_HEADERS = [
  "accept",
  "content-type",
  "if-modified-since",
  "if-none-match",
  "if-range",
  "range",
] as const;
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
  "vary",
] as const;

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function jsonError(detail: string, status: number): Response {
  return Response.json({ detail }, {
    status,
    headers: { "Cache-Control": "private, no-store" },
  });
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
  const isSafeId = (value: string) => /^[a-zA-Z0-9_-]+$/.test(value);
  const isCollectionId = (value: string) => /^collect_[a-f0-9]{24}$/.test(value);
  if (path.length === 1) {
    return ["session", "current-calibration", "run", "annual-run", "chat",
      "calibration-reviews", "data-collections", "saved-results", "analysis-library",
    ].includes(path[0]);
  }
  if (path.length === 2) {
    return (path[0] === "status" && isSafeId(path[1])) ||
      (path[0] === "data-collections" && isCollectionId(path[1])) ||
      (path[0] === "agent" && path[1] === "state") ||
      (path[0] === "saved-results" && isSafeId(path[1])) ||
      (path[0] === "technoeconomic" && ["sources", "jobs", "cost-year-indices"].includes(path[1]));
  }
  if (path.length === 3) {
    return (path[0] === "technoeconomic" && path[1] === "presets" &&
      ["thursday-2026-09-17-v1", "user-cost-basis-2026-v1"].includes(path[2])) ||
      (path[0] === "jobs" && isSafeId(path[1]) &&
      ["cancel", "delete", "promote", "retry"].includes(path[2])) ||
      (path[0] === "calibration-reviews" && isSafeId(path[1]) && ["run", "rows"].includes(path[2])) ||
      (path[0] === "data-collections" && isCollectionId(path[1]) && ["download", "download-xlsx", "cancel"].includes(path[2])) ||
      (path[0] === "technoeconomic" && path[1] === "jobs" && isSafeId(path[2]));
  }
  if (path.length === 4) {
    return (path[0] === "data-collections" && isCollectionId(path[1]) && path[2] === "plots" &&
      ["measured-ac-power", "cumulative-energy"].includes(path[3])) ||
      (path[0] === "agent" && isSafeId(path[2]) &&
        ((path[1] === "proposals" && ["confirm", "edit", "dismiss"].includes(path[3])) ||
        (path[1] === "sweeps" && path[3] === "confirm"))) ||
      (path[0] === "technoeconomic" && path[1] === "jobs" && isSafeId(path[2]) &&
        ["cancel", "retry"].includes(path[3]));
  }
  if (path.length === 5) {
    return path[0] === "technoeconomic" && path[1] === "jobs" && isSafeId(path[2]) &&
      ((path[3] === "exports" && ["csv", "xlsx", "pdf", "docx"].includes(path[4])) ||
       (path[3] === "artifacts" && ["cdf_plot", "sensitivity_plot", "convergence_plot"].includes(path[4])));
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
  const method = request.method.toUpperCase();
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

  const init: RequestInit = {
    method,
    headers,
    redirect: "follow",
  };
  if (prefix === "api") init.cache = "no-store";
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
  if (prefix === "api") responseHeaders.set("Cache-Control", "private, no-store");

  return new Response(method === "HEAD" ? null : upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders,
  });
}
