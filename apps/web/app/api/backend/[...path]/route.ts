import { NextRequest, NextResponse } from "next/server";

const API_BASE = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

function buildTargetUrl(pathParts: string[], search: string): string {
  const base = API_BASE.replace(/\/+$/, "");
  const path = pathParts.map((part) => encodeURIComponent(part)).join("/");
  return `${base}/${path}${search}`;
}

function buildForwardHeaders(req: NextRequest): Headers {
  const headers = new Headers();
  const allowList = ["accept", "authorization", "content-type"];
  for (const key of allowList) {
    const value = req.headers.get(key);
    if (value) headers.set(key, value);
  }
  return headers;
}

type RouteCtx = { params: Promise<{ path: string[] }> };

async function proxy(req: NextRequest, ctx: RouteCtx): Promise<Response> {
  const params = await ctx.params;
  const pathParts = params.path ?? [];
  if (!pathParts.length) {
    return NextResponse.json({ error: "Missing upstream path" }, { status: 400 });
  }

  const targetUrl = buildTargetUrl(pathParts, req.nextUrl.search);
  const body =
    req.method === "GET" || req.method === "HEAD"
      ? undefined
      : (() => req.arrayBuffer())();

  let upstream: Response;
  try {
    upstream = await fetch(targetUrl, {
      method: req.method,
      headers: buildForwardHeaders(req),
      body: body ? await body : undefined,
      cache: "no-store",
      redirect: "manual",
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: `Backend unreachable: ${error instanceof Error ? error.message : String(error)}`,
      },
      { status: 502 }
    );
  }

  const responseHeaders = new Headers();
  const passthrough = ["content-type", "cache-control"];
  for (const key of passthrough) {
    const value = upstream.headers.get(key);
    if (value) responseHeaders.set(key, value);
  }
  if (!responseHeaders.has("cache-control")) {
    responseHeaders.set("cache-control", "no-store");
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export async function GET(req: NextRequest, ctx: RouteCtx) {
  return proxy(req, ctx);
}

export async function POST(req: NextRequest, ctx: RouteCtx) {
  return proxy(req, ctx);
}

export async function PUT(req: NextRequest, ctx: RouteCtx) {
  return proxy(req, ctx);
}

export async function PATCH(req: NextRequest, ctx: RouteCtx) {
  return proxy(req, ctx);
}

export async function DELETE(req: NextRequest, ctx: RouteCtx) {
  return proxy(req, ctx);
}
