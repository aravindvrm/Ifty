import { normalizeNextPath } from "@/lib/auth";

function trimSlashes(value: string): string {
  return value.replace(/\/+$/, "");
}

function isLocalHostname(hostname: string): boolean {
  const value = hostname.trim().toLowerCase();
  return value === "localhost" || value === "127.0.0.1" || value === "::1";
}

function resolveAuthOrigin(): string {
  if (typeof window !== "undefined" && window.location?.origin) {
    // Always prefer the active browser origin for client-initiated OAuth.
    // This prevents stale env vars from forcing redirects to old domains.
    return trimSlashes(window.location.origin);
  }

  const explicit = String(process.env.NEXT_PUBLIC_AUTH_REDIRECT_BASE_URL ?? "").trim();
  if (explicit) return trimSlashes(explicit);

  return "http://localhost:3000";
}

export function buildAuthCallbackUrl(nextPath: string | null | undefined): string {
  const origin = resolveAuthOrigin();
  const callbackUrl = new URL("/auth/callback", origin);
  callbackUrl.searchParams.set("next", normalizeNextPath(nextPath));
  return callbackUrl.toString();
}
