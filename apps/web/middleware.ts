import { type NextRequest, NextResponse } from "next/server";

const PUBLIC_PATH_PREFIXES = ["/login", "/auth/callback", "/icon"];
const STATIC_FILE_EXTENSIONS = [".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".css", ".js", ".map", ".txt", ".woff", ".woff2", ".webmanifest"];
const DEFAULT_POST_LOGIN_PATH = "/explore";
const AUTH_MIDDLEWARE_ENABLED = String(process.env.AUTH_MIDDLEWARE_ENABLED ?? "true").trim().toLowerCase() !== "false";

function toTrimmed(value: string | undefined): string {
  return String(value ?? "").trim();
}

function getSupabaseEnvFromRuntime(): { url: string; anonKey: string } | null {
  const url = toTrimmed(process.env.NEXT_PUBLIC_SUPABASE_URL);
  const anonKey = toTrimmed(process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
  if (!url || !anonKey) return null;
  try {
    const parsed = new URL(url);
    if (!/^https?:$/.test(parsed.protocol)) return null;
  } catch {
    return null;
  }
  return { url, anonKey };
}

function normalizeNextPathForRedirect(input: string | null | undefined): string {
  const value = String(input ?? "").trim();
  if (!value) return DEFAULT_POST_LOGIN_PATH;
  if (!value.startsWith("/")) return DEFAULT_POST_LOGIN_PATH;
  if (value.startsWith("//")) return DEFAULT_POST_LOGIN_PATH;
  return value;
}

function isPublicPath(pathname: string): boolean {
  if (pathname.startsWith("/_next/")) return true;
  if (PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))) return true;
  return STATIC_FILE_EXTENSIONS.some((ext) => pathname.endsWith(ext));
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  if (!AUTH_MIDDLEWARE_ENABLED) {
    return NextResponse.next();
  }

  const env = getSupabaseEnvFromRuntime();
  if (!env) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/login";
    redirectUrl.searchParams.set("next", normalizeNextPathForRedirect(`${pathname}${request.nextUrl.search}`));
    redirectUrl.searchParams.set("error", "auth_env_missing");
    return NextResponse.redirect(redirectUrl);
  }

  let response = NextResponse.next({
    request,
  });

  let user: { id: string } | null = null;
  try {
    const { createServerClient } = await import("@supabase/ssr");
    const supabase = createServerClient(env.url, env.anonKey, {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet) {
          response = NextResponse.next({
            request,
          });
          cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
        },
      },
    });

    const result = await supabase.auth.getUser();
    user = result.data.user;
  } catch {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/login";
    redirectUrl.searchParams.set("next", normalizeNextPathForRedirect(`${pathname}${request.nextUrl.search}`));
    redirectUrl.searchParams.set("error", "auth_middleware_failed");
    return NextResponse.redirect(redirectUrl);
  }

  if (!user) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/login";
    redirectUrl.searchParams.set("next", normalizeNextPathForRedirect(`${pathname}${request.nextUrl.search}`));
    return NextResponse.redirect(redirectUrl);
  }

  return response;
}

export const config = {
  matcher: ["/:path*"],
};
