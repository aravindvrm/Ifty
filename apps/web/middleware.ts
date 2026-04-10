import { createServerClient } from "@supabase/ssr";
import { type NextRequest, NextResponse } from "next/server";

import { normalizeNextPath } from "@/lib/auth";
import { getSupabaseEnv } from "@/lib/supabase/env";

const PUBLIC_PATH_PREFIXES = ["/login", "/auth/callback", "/icon"];
const STATIC_FILE_EXTENSIONS = [".svg", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".css", ".js", ".map", ".txt", ".woff", ".woff2", ".webmanifest"];

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

  const env = getSupabaseEnv();
  if (!env) {
    return NextResponse.next();
  }

  let response = NextResponse.next({
    request,
  });

  const supabase = createServerClient(env.url, env.anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({
          request,
        });
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });

  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    const redirectUrl = request.nextUrl.clone();
    redirectUrl.pathname = "/login";
    redirectUrl.searchParams.set("next", normalizeNextPath(`${pathname}${request.nextUrl.search}`));
    return NextResponse.redirect(redirectUrl);
  }

  return response;
}

export const config = {
  matcher: ["/:path*"],
};
