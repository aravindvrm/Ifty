"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { getDefaultPostLoginPath, normalizeNextPath } from "@/lib/auth";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export default function SignupPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const supabase = useMemo(() => getSupabaseBrowserClient(), []);
  const nextPath = normalizeNextPath(searchParams.get("next"));

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
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    setError(null);
    setNotice(null);
    try {
      const redirectTo = `${window.location.origin}/auth/callback?next=${encodeURIComponent(nextPath)}`;
      const { data, error: signUpError } = await supabase.auth.signUp({
        email: normalizedEmail,
        password,
        options: {
          emailRedirectTo: redirectTo,
        },
      });
      if (signUpError) throw signUpError;

      if (data.session) {
        router.replace(nextPath || getDefaultPostLoginPath());
        return;
      }
      setNotice("Account created. Check your email to verify, then sign in.");
    } catch (submitError) {
      setError(String(submitError));
    } finally {
      setSubmitting(false);
    }
  }

  if (!supabase) {
    return (
      <section className="mx-auto w-full max-w-md rounded-xl border border-line/80 bg-card/60 p-6">
        <h1 className="text-xl font-semibold text-slate-100">Sign up unavailable</h1>
        <p className="mt-3 text-sm text-slate-400">
          Supabase env vars are missing. Set <code>NEXT_PUBLIC_SUPABASE_URL</code> and <code>NEXT_PUBLIC_SUPABASE_ANON_KEY</code> in <code>apps/web/.env.local</code>.
        </p>
      </section>
    );
  }

  return (
    <section className="mx-auto w-full max-w-md rounded-xl border border-line/80 bg-card/70 p-6 shadow-panel">
      <h1 className="text-xl font-semibold text-slate-100">Create account</h1>
      <p className="mt-2 text-sm text-slate-400">Use email and password to create your account.</p>

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
          disabled={submitting}
        />

        <label className="block text-xs uppercase tracking-wide text-slate-500" htmlFor="password">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="At least 8 characters"
          className="w-full rounded-xl border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70"
          disabled={submitting}
        />

        <label className="block text-xs uppercase tracking-wide text-slate-500" htmlFor="confirm-password">
          Confirm password
        </label>
        <input
          id="confirm-password"
          type="password"
          autoComplete="new-password"
          value={confirmPassword}
          onChange={(event) => setConfirmPassword(event.target.value)}
          placeholder="Re-enter password"
          className="w-full rounded-xl border border-line/80 bg-card/70 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-accentBlue/70"
          disabled={submitting}
        />

        <button
          type="submit"
          className="w-full rounded-xl border border-accentBlue/60 bg-accentBlue/15 px-3 py-2 text-sm text-slate-100 transition hover:bg-accentBlue/25 disabled:opacity-60"
          disabled={submitting}
        >
          {submitting ? "Creating account..." : "Sign up"}
        </button>
      </form>

      {error ? <p className="mt-3 text-sm text-rose-300">{error}</p> : null}
      {notice ? <p className="mt-3 text-sm text-emerald-300">{notice}</p> : null}

      <p className="mt-5 text-sm text-slate-400">
        Already have an account?{" "}
        <Link href={`/login?next=${encodeURIComponent(nextPath)}`} className="text-slate-100 underline decoration-line/80 underline-offset-4">
          Sign in
        </Link>
      </p>
    </section>
  );
}

