import { proxyRenderRequest } from "@/lib/render-proxy";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function proxy(request: Request, context: RouteContext): Promise<Response> {
  return proxyRenderRequest(request, context, "api");
}

export const GET = proxy;
export const POST = proxy;
export const HEAD = proxy;
