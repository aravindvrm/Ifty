"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { getDefaultPostLoginPath, normalizeNextPath } from "@/lib/auth";
import { buildAuthCallbackUrl } from "@/lib/auth-redirect";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [magicSubmitting, setMagicSubmitting] = useState(false);
  const [oauthSubmitting, setOauthSubmitting] = useState(false);
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
    if (!password.trim()) {
      setError("Password is required.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const { error: signInError } = await supabase.auth.signInWithPassword({
        email: normalizedEmail,
        password,
      });
      if (signInError) throw signInError;
      router.replace(nextPath || getDefaultPostLoginPath());
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setSubmitting(false);
    }
  }

  async function onMagicLink() {
    if (!supabase) return;
    const normalizedEmail = email.trim();
    if (!normalizedEmail) {
      setError("Enter your email first to request a magic link.");
      return;
    }

    setMagicSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const redirectTo = buildAuthCallbackUrl(nextPath);
      const { error: magicError } = await supabase.auth.signInWithOtp({
        email: normalizedEmail,
        options: {
          emailRedirectTo: redirectTo,
        },
      });
      if (magicError) throw magicError;
      setNotice("Magic link sent. Check your inbox to continue.");
    } catch (magicLinkError) {
      setError(String(magicLinkError));
    } finally {
      setMagicSubmitting(false);
    }
  }

  async function onGoogleSignIn() {
    if (!supabase) return;
    setOauthSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const redirectTo = buildAuthCallbackUrl(nextPath);
      const { error: oauthError } = await supabase.auth.signInWithOAuth({
        provider: "google",
        options: { redirectTo },
      });
      if (oauthError) throw oauthError;
    } catch (oauthSignInError) {
      setError(String(oauthSignInError));
      setOauthSubmitting(false);
    }
  }

  const isBusy = submitting || magicSubmitting || oauthSubmitting;

  if (!supabase) {
    return (
      <section className="mx-auto w-full max-w-md rounded-xl border border-line/80 bg-card/60 p-6">
        <h1 className="text-xl font-semibold text-slate-100">Sign in unavailable</h1>
        <p className="mt-3 text-sm text-slate-400">
          Supabase env vars are missing. Set <code>NEXT_PUBLIC_SUPABASE_URL</code> and <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in <code>apps/web/.env.local</code>.
        </p>
      </section>
    );
  }

  return (
    <section className="mx-auto w-full max-w-md rounded-xl border border-line/80 bg-card/70 p-6 shadow-panel">
      <h1 className="text-xl font-semibold text-slate-100">Sign in</h1>
      <p className="mt-2 text-sm text-slate-400">Sign in with email and password.</p>
      <button
        type="button"
        onClick={onGoogleSignIn}
        className="mt-5 inline-flex w-full items-center justify-center gap-2 rounded-xl border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 transition hover:border-accentBlue/70 hover:bg-accentBlue/10 disabled:opacity-60"
        disabled={isBusy}
      >
        <span className="inline-flex h-4 w-4 items-center justify-center rounded-full bg-white text-[10px] font-semibold text-black">G</span>
        <span>{oauthSubmitting ? "Redirecting..." : "Continue with Google"}</span>
      </button>

      <div className="relative my-4 flex items-center">
        <div className="h-px w-full bg-line/70" />
        <span className="absolute left-1/2 -translate-x-1/2 bg-card/70 px-2 text-[11px] uppercase tracking-wide text-slate-500">or</span>
      </div>

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
          className="w-full rounded-xl border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70"
          disabled={isBusy}
        />
        <label className="block text-xs uppercase tracking-wide text-slate-500" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Your password"
          className="w-full rounded-xl border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70"
          disabled={isBusy}
        />
        <button
          type="submit"
          className="w-full rounded-xl border border-accentBlue/60 bg-accentBlue/15 px-3 py-2 text-sm text-slate-100 transition hover:bg-accentBlue/25 disabled:opacity-60"
          disabled={isBusy}
        >
          {submitting ? "Signing in..." : "Sign in"}
        </button>
      </form>

      <button
        type="button"
        onClick={onMagicLink}
        className="mt-3 w-full rounded-xl border border-line/70 bg-black/25 px-3 py-2 text-sm text-slate-300 transition hover:border-line hover:text-white disabled:opacity-60"
        disabled={isBusy}
      >
        {magicSubmitting ? "Sending link..." : "Use magic link instead"}
      </button>

      {error ? <p className="mt-3 text-sm text-rose-300">{error}</p> : null}
      {notice ? <p className="mt-3 text-sm text-emerald-300">{notice}</p> : null}

      <p className="mt-5 text-sm text-slate-400">
        No account yet?{" "}
        <Link href={`/signup?next=${encodeURIComponent(nextPath)}`} className="text-slate-100 underline decoration-line/80 underline-offset-4">
          Create one
        </Link>
      </p>
    </section>
  );
}
