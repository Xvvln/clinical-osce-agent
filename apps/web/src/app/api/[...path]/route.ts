import { NextRequest, NextResponse } from "next/server";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const HOP_BY_HOP_HEADERS = [
  "host",
  "connection",
  "content-length",
  "transfer-encoding",
  "accept-encoding",
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
  const requestBody = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();

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
  return headers;
}

function buildDownstreamHeaders(response: Response): Headers {
  const headers = new Headers(response.headers);
  headers.delete("content-encoding");
  headers.delete("content-length");
  headers.delete("transfer-encoding");
  return headers;
}
