import { createServerClient } from "@supabase/ssr";
import { NextRequest, NextResponse } from "next/server";

import { getDefaultPostLoginPath, normalizeNextPath } from "@/lib/auth";
import { getSupabaseEnv } from "@/lib/supabase/env";

function isLocalHostname(hostname: string): boolean {
  const value = hostname.trim().toLowerCase();
  return value === "localhost" || value === "127.0.0.1" || value === "::1";
}

export async function GET(request: NextRequest) {
  const requestUrl = new URL(request.url);
  const code = requestUrl.searchParams.get("code");
  const nextPath = normalizeNextPath(requestUrl.searchParams.get("next"));
  const localHost = isLocalHostname(requestUrl.hostname);

  const env = getSupabaseEnv();
  if (!env || !code) {
    return NextResponse.redirect(new URL(nextPath || getDefaultPostLoginPath(), requestUrl.origin));
  }

  let response = NextResponse.redirect(new URL(nextPath || getDefaultPostLoginPath(), requestUrl.origin));

  const supabase = createServerClient(env.url, env.anonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value, options }) =>
          response.cookies.set(name, value, {
            ...options,
            secure: localHost ? false : options?.secure,
          })
        );
      },
    },
  });

  const { error } = await supabase.auth.exchangeCodeForSession(code);
  if (error) {
    const loginUrl = new URL("/login", requestUrl.origin);
    loginUrl.searchParams.set("next", nextPath || getDefaultPostLoginPath());
    loginUrl.searchParams.set("error", "auth_callback_failed");
    return NextResponse.redirect(loginUrl);
  }

  return response;
}
