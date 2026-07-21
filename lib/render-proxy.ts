const DEFAULT_RENDER_ORIGIN = "https://sbepvmodel.onrender.com";

const REQUEST_HEADERS = ["accept", "content-type", "range"] as const;
const RESPONSE_HEADERS = [
  "accept-ranges",
  "cache-control",
  "content-disposition",
  "content-range",
  "content-type",
  "etag",
  "last-modified",
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

function isAllowedApiPath(path: string[]): boolean {
  if (path.length === 1) {
    return ["session", "run", "annual-run", "chat"].includes(path[0]);
  }

  const isSafeId = (value: string) => /^[a-zA-Z0-9_-]+$/.test(value);
  if (path.length === 2) {
    return (
      (path[0] === "status" && isSafeId(path[1])) ||
      (path[0] === "agent" && path[1] === "state")
    );
  }

  if (path.length === 3) {
    return (
      path[0] === "jobs" &&
      isSafeId(path[1]) &&
      ["cancel", "promote", "retry"].includes(path[2])
    );
  }

  return (
    path.length === 4 &&
    path[0] === "agent" &&
    path[1] === "proposals" &&
    isSafeId(path[2]) &&
    ["confirm", "edit", "dismiss"].includes(path[3])
  );
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
