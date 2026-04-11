import { type NextRequest, NextResponse } from "next/server";

const PUBLIC_PATH_PREFIXES = ["/login", "/signup", "/auth/callback", "/icon", "/explore", "/activity", "/institution"];
const PROTECTED_PATH_PREFIXES = ["/ops"];
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

function getSupabaseProjectRef(url: string): string | null {
  try {
    const host = new URL(url).hostname.trim().toLowerCase();
    if (!host) return null;
    const first = host.split(".")[0] ?? "";
    return first || null;
  } catch {
    return null;
  }
}

function hasSupabaseSessionCookie(request: NextRequest, projectRef: string | null): boolean {
  const cookies = request.cookies.getAll();
  if (cookies.length === 0) return false;

  const exactPrefix = projectRef ? `sb-${projectRef}-auth-token` : null;
  return cookies.some((cookie) => {
    const name = String(cookie.name ?? "").toLowerCase();
    if (!name) return false;
    if (exactPrefix && name.startsWith(exactPrefix)) return true;
    if (name.startsWith("sb-") && name.includes("-auth-token")) return true;
    if (name.includes("supabase-auth-token")) return true;
    return false;
  });
}

function normalizeNextPathForRedirect(input: string | null | undefined): string {
  const value = String(input ?? "").trim();
  if (!value) return DEFAULT_POST_LOGIN_PATH;
  if (!value.startsWith("/")) return DEFAULT_POST_LOGIN_PATH;
  if (value.startsWith("//")) return DEFAULT_POST_LOGIN_PATH;
  return value;
}

function isPublicPath(pathname: string): boolean {
  if (pathname === "/") return true;
  if (pathname.startsWith("/_next/")) return true;
  if (PUBLIC_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix))) return true;
  return STATIC_FILE_EXTENSIONS.some((ext) => pathname.endsWith(ext));
}

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PATH_PREFIXES.some((prefix) => pathname.startsWith(prefix));
}

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (isPublicPath(pathname)) {
    return NextResponse.next();
  }

  if (!isProtectedPath(pathname)) {
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

  const projectRef = getSupabaseProjectRef(env.url);
  if (!hasSupabaseSessionCookie(request, projectRef)) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/login";
    redirectUrl.searchParams.set("next", normalizeNextPathForRedirect(`${pathname}${request.nextUrl.search}`));
    redirectUrl.searchParams.set("error", "auth_session_required");
    return NextResponse.redirect(redirectUrl);
  }

  return NextResponse.next({
    request,
  });
}

export const config = {
  matcher: ["/:path*"],
};
