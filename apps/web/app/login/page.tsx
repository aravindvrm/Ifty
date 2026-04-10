"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { getDefaultPostLoginPath, normalizeNextPath } from "@/lib/auth";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const supabase = useMemo(() => getSupabaseBrowserClient(), []);
  const nextPath = normalizeNextPath(searchParams.get("next"));
  const authError = String(searchParams.get("error") ?? "").trim();

  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getUser().then(({ data }) => {
      if (data.user) {
        router.replace(nextPath || getDefaultPostLoginPath());
      }
    });
  }, [nextPath, router, supabase]);

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!supabase) return;
    const normalizedEmail = email.trim();
    if (!normalizedEmail) {
      setError("Email is required.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`;
      const { error: signInError } = await supabase.auth.signInWithOtp({
        email: normalizedEmail,
        options: {
          emailRedirectTo: redirectTo,
        },
      });
      if (signInError) throw signInError;
      setNotice("Magic link sent. Check your inbox to continue.");
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setSubmitting(false);
    }
  }

  async function skipToApp() {
    router.push(getDefaultPostLoginPath());
  }

  if (!supabase) {
    return (
      <section className="mx-auto w-full max-w-md rounded-none border border-line/80 bg-card/60 p-6">
        <h1 className="text-xl font-semibold text-slate-100">Sign in unavailable</h1>
        <p className="mt-3 text-sm text-slate-400">
          Supabase env vars are missing. Set <code>NEXT_PUBLIC_SUPABASE_URL</code> and <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in <code>apps/web/.env.local</code>.
        </p>
        <button
          type="button"
          onClick={skipToApp}
          className="mt-5 rounded-none border border-line/80 px-3 py-2 text-sm text-slate-300 transition hover:text-slate-100"
        >
          Continue without auth
        </button>
      </section>
    );
  }

  return (
    <section className="mx-auto w-full max-w-md rounded-none border border-line/80 bg-card/60 p-6">
      <h1 className="text-xl font-semibold text-slate-100">Sign in</h1>
      <p className="mt-2 text-sm text-slate-400">Use your email to receive a secure sign-in link.</p>
      {authError === "auth_callback_failed" ? (
        <p className="mt-2 text-sm text-rose-300">Sign-in callback failed. Please request a new magic link.</p>
      ) : authError === "auth_env_missing" ? (
        <p className="mt-2 text-sm text-rose-300">Auth env vars are missing on the server. Please contact the admin.</p>
      ) : authError === "auth_middleware_failed" ? (
        <p className="mt-2 text-sm text-rose-300">Auth middleware failed. Please try signing in again.</p>
      ) : authError === "auth_session_required" ? (
        <p className="mt-2 text-sm text-slate-300">Please sign in to continue.</p>
      ) : null}

      <form className="mt-5 space-y-3" onSubmit={onSubmit}>
        <label className="block text-xs uppercase tracking-wide text-slate-500" htmlFor="email">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="you@example.com"
          className="w-full rounded-none border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70"
          disabled={submitting}
        />
        <button
          type="submit"
          className="w-full rounded-none border border-accentBlue/60 bg-accentBlue/15 px-3 py-2 text-sm text-slate-100 transition hover:bg-accentBlue/25 disabled:opacity-60"
          disabled={submitting}
        >
          {submitting ? "Sending..." : "Send magic link"}
        </button>
      </form>

      {error ? <p className="mt-3 text-sm text-rose-300">{error}</p> : null}
      {notice ? <p className="mt-3 text-sm text-emerald-300">{notice}</p> : null}

      <p className="mt-5 text-xs text-slate-500">Google sign-in can be added next via Supabase OAuth provider config.</p>
    </section>
  );
}
