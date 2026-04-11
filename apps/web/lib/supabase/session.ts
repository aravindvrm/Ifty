"use client";

import type { Session, SupabaseClient, User } from "@supabase/supabase-js";

export type AuthSnapshot = {
  session: Session | null;
  user: User | null;
  recoveredInvalidRefreshToken: boolean;
  error: Error | null;
};

let inflightSnapshot: Promise<AuthSnapshot> | null = null;
let cachedSnapshot: AuthSnapshot | null = null;
let cachedAtMs = 0;
const CACHE_TTL_MS = 750;

function toError(error: unknown): Error {
  if (error instanceof Error) return error;
  return new Error(String(error));
}

function isInvalidRefreshTokenError(error: unknown): boolean {
  const message = String((error as { message?: unknown } | null)?.message ?? error ?? "")
    .trim()
    .toLowerCase();
  return (
    message.includes("invalid refresh token") ||
    message.includes("refresh token not found") ||
    message.includes("invalid_grant")
  );
}

function clearSupabaseAuthStorage(): void {
  if (typeof window === "undefined") return;
  const shouldClear = (key: string): boolean => {
    const lower = key.toLowerCase();
    if (lower.includes("supabase.auth.token")) return true;
    if (lower.startsWith("sb-") && lower.includes("-auth-token")) return true;
    return false;
  };

  try {
    const keys: string[] = [];
    for (let i = 0; i < window.localStorage.length; i += 1) {
      const key = window.localStorage.key(i);
      if (key) keys.push(key);
    }
    for (const key of keys) {
      if (shouldClear(key)) {
        window.localStorage.removeItem(key);
      }
    }
  } catch {
    // no-op
  }

  try {
    const keys: string[] = [];
    for (let i = 0; i < window.sessionStorage.length; i += 1) {
      const key = window.sessionStorage.key(i);
      if (key) keys.push(key);
    }
    for (const key of keys) {
      if (shouldClear(key)) {
        window.sessionStorage.removeItem(key);
      }
    }
  } catch {
    // no-op
  }
}

async function readSnapshot(supabase: SupabaseClient): Promise<AuthSnapshot> {
  const { data, error } = await supabase.auth.getSession();
  if (!error) {
    return {
      session: data.session ?? null,
      user: data.session?.user ?? null,
      recoveredInvalidRefreshToken: false,
      error: null,
    };
  }

  if (isInvalidRefreshTokenError(error)) {
    try {
      await supabase.auth.signOut({ scope: "local" });
    } catch {
      // no-op
    }
    clearSupabaseAuthStorage();
    return {
      session: null,
      user: null,
      recoveredInvalidRefreshToken: true,
      error: null,
    };
  }

  return {
    session: null,
    user: null,
    recoveredInvalidRefreshToken: false,
    error: toError(error),
  };
}

export async function getAuthSnapshot(supabase: SupabaseClient): Promise<AuthSnapshot> {
  const now = Date.now();
  if (cachedSnapshot && now - cachedAtMs < CACHE_TTL_MS) {
    return cachedSnapshot;
  }
  if (inflightSnapshot) {
    return inflightSnapshot;
  }
  inflightSnapshot = readSnapshot(supabase)
    .then((snapshot) => {
      cachedSnapshot = snapshot;
      cachedAtMs = Date.now();
      return snapshot;
    })
    .finally(() => {
      inflightSnapshot = null;
    });
  return inflightSnapshot;
}

