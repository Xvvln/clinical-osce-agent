import { NextRequest, NextResponse } from "next/server";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const MAX_API_PROXY_REQUEST_BYTES = 12 * 1024 * 1024;
const HOP_BY_HOP_HEADERS = [
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
];

type ApiProxyContext = {
  params: Promise<{
    path?: string[];
  }>;
};

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, context: ApiProxyContext): Promise<NextResponse> {
  return proxyApiRequest(request, context);
}

export async function POST(request: NextRequest, context: ApiProxyContext): Promise<NextResponse> {
  return proxyApiRequest(request, context);
}

export async function PUT(request: NextRequest, context: ApiProxyContext): Promise<NextResponse> {
  return proxyApiRequest(request, context);
}

export async function PATCH(request: NextRequest, context: ApiProxyContext): Promise<NextResponse> {
  return proxyApiRequest(request, context);
}

export async function DELETE(request: NextRequest, context: ApiProxyContext): Promise<NextResponse> {
  return proxyApiRequest(request, context);
}

export async function HEAD(request: NextRequest, context: ApiProxyContext): Promise<NextResponse> {
  return proxyApiRequest(request, context);
}

export async function OPTIONS(request: NextRequest, context: ApiProxyContext): Promise<NextResponse> {
  return proxyApiRequest(request, context);
}

async function proxyApiRequest(request: NextRequest, context: ApiProxyContext): Promise<NextResponse> {
  const { path = [] } = await context.params;
  const upstreamUrl = buildUpstreamUrl(path, request.nextUrl.search);
  const method = request.method.toUpperCase();
  const boundedRequestBody = await readBoundedRequestBody(request);
  if (boundedRequestBody instanceof NextResponse) {
    return boundedRequestBody;
  }
  const requestBody =
    method === "GET" || method === "HEAD" ? undefined : boundedRequestBody;

  const upstreamResponse = await fetch(upstreamUrl, {
    method,
    headers: buildUpstreamHeaders(request),
    body: requestBody,
    cache: "no-store",
    redirect: "manual",
  });

  return new NextResponse(method === "HEAD" ? null : upstreamResponse.body, {
    status: upstreamResponse.status,
    statusText: upstreamResponse.statusText,
    headers: buildDownstreamHeaders(upstreamResponse),
  });
}

async function readBoundedRequestBody(request: NextRequest): Promise<ArrayBuffer | NextResponse> {
  const declaredLength = declaredContentLength(request.headers.get("content-length"));
  if (declaredLength !== null && declaredLength > MAX_API_PROXY_REQUEST_BYTES) {
    await request.body?.cancel("request body is too large").catch(() => undefined);
    return proxyPayloadTooLargeResponse();
  }
  if (request.body === null) {
    return new ArrayBuffer(0);
  }

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let totalBytes = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      totalBytes += value.byteLength;
      if (totalBytes > MAX_API_PROXY_REQUEST_BYTES) {
        await reader.cancel("request body is too large").catch(() => undefined);
        return proxyPayloadTooLargeResponse();
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }

  const body = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body.buffer;
}

function declaredContentLength(rawValue: string | null): number | null {
  const normalizedValue = rawValue?.trim() ?? "";
  if (!/^\d+$/.test(normalizedValue)) {
    return null;
  }
  const parsedValue = Number(normalizedValue);
  return Number.isSafeInteger(parsedValue) ? parsedValue : Number.POSITIVE_INFINITY;
}

function proxyPayloadTooLargeResponse(): NextResponse {
  return NextResponse.json(
    { detail: "request body is too large" },
    {
      status: 413,
      headers: {
        "Cache-Control": "private, no-store, max-age=0",
        Expires: "0",
        Pragma: "no-cache",
      },
    },
  );
}

function buildUpstreamUrl(pathSegments: readonly string[], search: string): string {
  const encodedPath = pathSegments.map((segment) => encodeURIComponent(segment)).join("/");
  return `${backendApiBaseUrl()}/api/${encodedPath}${search}`;
}

function backendApiBaseUrl(): string {
  return (process.env.CLINICAL_OSCE_WEB_API_URL ?? DEFAULT_API_BASE_URL).replace(/\/+$/, "");
}

function buildUpstreamHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  for (const headerName of HOP_BY_HOP_HEADERS) {
    headers.delete(headerName);
  }
  headers.delete("accept-encoding");
  headers.delete("content-length");
  headers.delete("host");
  return headers;
}

function buildDownstreamHeaders(response: Response): Headers {
  const headers = new Headers(response.headers);
  for (const headerName of HOP_BY_HOP_HEADERS) {
    headers.delete(headerName);
  }
  headers.delete("content-encoding");
  headers.delete("content-length");
  headers.delete("server");
  headers.delete("x-powered-by");
  headers.set("cache-control", "private, no-store, max-age=0");
  headers.set("pragma", "no-cache");
  headers.set("expires", "0");
  return headers;
}
