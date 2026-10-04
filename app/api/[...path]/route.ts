// The API behind the frontend's own origin, for deployments built with
// NEXT_PUBLIC_API_URL="/". The browser then talks to one address, so the
// sign-in cookie reaches every request — fetches, PDF previews, downloads —
// and the API itself need not be reachable from outside. DOCUFLOW_API_URL is
// where this server finds it (http://127.0.0.1:8000 beside it in one Cloud
// Run service, http://backend:8000 in compose). Unset, there is no proxy: on
// a developer machine the browser calls the API directly.
//
// node:http rather than fetch: fetch gives up on an answer that takes more
// than five minutes to start, and loading a large model on the model server
// legitimately takes longer than that.

import http from "node:http";
import { Readable } from "node:stream";

export const dynamic = "force-dynamic";

// Headers that describe one hop, not the request or the answer.
const HOP_HEADERS = new Set(["connection", "keep-alive", "transfer-encoding", "upgrade", "host", "content-length"]);

function forwardedHeaders(request: Request, incoming: URL): Record<string, string> {
  const headers: Record<string, string> = {};
  request.headers.forEach((value, key) => {
    if (!HOP_HEADERS.has(key.toLowerCase())) headers[key] = value;
  });
  headers["x-forwarded-proto"] = request.headers.get("x-forwarded-proto") ?? incoming.protocol.replace(":", "");
  return headers;
}

async function proxy(request: Request): Promise<Response> {
  const upstream = process.env.DOCUFLOW_API_URL;
  if (!upstream) {
    return Response.json({ detail: "This server does not forward /api; the API is called directly." }, { status: 404 });
  }
  const incoming = new URL(request.url);
  const target = new URL(`${incoming.pathname}${incoming.search}`, upstream);
  const hasBody = request.method !== "GET" && request.method !== "HEAD" && request.body !== null;

  return new Promise<Response>((resolve) => {
    const outgoing = http.request(target, { method: request.method, headers: forwardedHeaders(request, incoming) }, (answer) => {
      const headers = new Headers();
      for (const [key, value] of Object.entries(answer.headers)) {
        if (value === undefined || HOP_HEADERS.has(key.toLowerCase())) continue;
        for (const item of Array.isArray(value) ? value : [value]) headers.append(key, item);
      }
      const status = answer.statusCode ?? 502;
      const empty = request.method === "HEAD" || status === 204 || status === 304;
      if (empty) answer.resume();
      resolve(new Response(empty ? null : (Readable.toWeb(answer) as ReadableStream), { status, headers }));
    });
    // No idle limit: the API decides how long its work takes.
    outgoing.setTimeout(0);
    outgoing.on("error", () => {
      resolve(Response.json({ detail: "The DocuFlow API is not reachable from the frontend server." }, { status: 502 }));
    });
    if (hasBody) {
      Readable.fromWeb(request.body as import("node:stream/web").ReadableStream).pipe(outgoing);
    } else {
      outgoing.end();
    }
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
