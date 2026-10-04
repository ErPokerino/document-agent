// The API behind the frontend's own origin, for deployments built with
// NEXT_PUBLIC_API_URL="/". The browser then talks to one address, so the
// sign-in cookie reaches every request — fetches, PDF previews, downloads —
// and the API itself need not be reachable from outside. DOCUFLOW_API_URL is
// where this server finds it (http://127.0.0.1:8000 beside it in one Cloud
// Run service, http://backend:8000 in compose). Unset, there is no proxy: on
// a developer machine the browser calls the API directly.

export const dynamic = "force-dynamic";

// Headers that describe one hop, or that fetch has already undone (it
// decompresses, so the original encoding and length no longer apply).
const HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "transfer-encoding",
  "upgrade",
  "host",
  "content-encoding",
  "content-length",
]);

function forwardable(headers: Headers): Headers {
  const result = new Headers();
  headers.forEach((value, key) => {
    if (!HOP_HEADERS.has(key.toLowerCase()) && key.toLowerCase() !== "set-cookie") result.append(key, value);
  });
  return result;
}

async function proxy(request: Request): Promise<Response> {
  const upstream = process.env.DOCUFLOW_API_URL;
  if (!upstream) {
    return Response.json({ detail: "This server does not forward /api; the API is called directly." }, { status: 404 });
  }
  const incoming = new URL(request.url);
  const target = `${upstream.replace(/\/+$/, "")}${incoming.pathname}${incoming.search}`;
  const headers = forwardable(request.headers);
  headers.set("x-forwarded-proto", request.headers.get("x-forwarded-proto") ?? incoming.protocol.replace(":", ""));
  const client = request.headers.get("x-forwarded-for");
  if (client) headers.set("x-forwarded-for", client);
  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  let answer: Response;
  try {
    answer = await fetch(target, {
      method: request.method,
      headers,
      body: hasBody ? request.body : undefined,
      redirect: "manual",
      // Streams the upload rather than buffering a dataset archive in memory.
      ...(hasBody ? { duplex: "half" } : {}),
    } as RequestInit);
  } catch {
    return Response.json({ detail: "The DocuFlow API is not reachable from the frontend server." }, { status: 502 });
  }
  const responseHeaders = forwardable(answer.headers);
  for (const cookie of answer.headers.getSetCookie()) responseHeaders.append("set-cookie", cookie);
  return new Response(answer.body, { status: answer.status, statusText: answer.statusText, headers: responseHeaders });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
