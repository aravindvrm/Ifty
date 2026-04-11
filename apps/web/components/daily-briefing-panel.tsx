"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { RefreshCw } from "lucide-react";

import { LottieLoader } from "@/components/lottie-loader";
import { getDailyBriefing, type DailyBriefingResponse } from "@/lib/api";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { getAuthSnapshot } from "@/lib/supabase/session";

export function DailyBriefingPanel() {
  const supabase = useMemo(() => getSupabaseBrowserClient(), []);
  const [loading, setLoading] = useState(true);
  const [userId, setUserId] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [briefing, setBriefing] = useState<DailyBriefingResponse | null>(null);
  const [statusText, setStatusText] = useState("");
  const [busy, setBusy] = useState(false);

  async function refreshBriefing(token: string) {
    setBusy(true);
    setStatusText("");
    try {
      const response = await getDailyBriefing(token, { days: 1, maxEvents: 40 });
      setBriefing(response);
    } catch (error) {
      setStatusText(`Failed to load daily briefing: ${String(error)}`);
      setBriefing(null);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return;
    }
    const supabaseClient = supabase;
    let mounted = true;

    async function load() {
      setLoading(true);
      const snapshot = await getAuthSnapshot(supabaseClient);
      if (!mounted) return;
      const id = snapshot.user?.id ?? null;
      const token = snapshot.session?.access_token ?? null;
      setUserId(id);
      setAccessToken(token);
      if (token) {
        await refreshBriefing(token);
      } else {
        setBriefing(null);
        if (snapshot.recoveredInvalidRefreshToken) {
          setStatusText("Session expired. Please sign in again.");
        }
      }
      if (mounted) setLoading(false);
    }

    void load();
    const {
      data: { subscription },
    } = supabaseClient.auth.onAuthStateChange(async (_event, session) => {
      const id = session?.user?.id ?? null;
      const token = session?.access_token ?? null;
      setUserId(id);
      setAccessToken(token);
      if (token) {
        await refreshBriefing(token);
      } else {
        setBriefing(null);
      }
    });
    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [supabase]);

  return (
    <section>
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-100">Daily AI Briefing</h2>
        {accessToken ? (
          <button
            type="button"
            disabled={busy || loading}
            onClick={() => void (accessToken ? refreshBriefing(accessToken) : Promise.resolve())}
            className="inline-flex h-8 items-center gap-1.5 border border-line/80 px-2.5 text-xs text-slate-300 transition hover:text-white disabled:opacity-50"
          >
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </button>
        ) : null}
      </div>

      <article className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
        {!supabase ? (
          <p className="text-sm text-amber-300">Supabase auth is not configured.</p>
        ) : loading ? (
          <div className="grid place-items-center py-2">
            <LottieLoader size={84} />
          </div>
        ) : !userId || !accessToken ? (
          <p className="text-sm text-slate-400">
            Sign in to see watchlist briefing.{" "}
            <Link href="/login?next=%2Fexplore" className="text-accentBlue hover:text-white">
              Go to sign in
            </Link>
          </p>
        ) : !briefing ? (
          <p className="text-sm text-slate-500">No briefing available yet.</p>
        ) : (
          <div className="space-y-4">
            <p className="text-sm leading-6 text-slate-200">{briefing.summary}</p>
            <div className="text-xs text-slate-500">
              Events: {briefing.counts.events} · 13D/G {briefing.counts.by_source?.["13DG"] ?? 0} · Insider{" "}
              {briefing.counts.by_source?.["INSIDER"] ?? 0}
            </div>

            <div className="grid gap-3 md:grid-cols-2">
              <div className="border border-line/70 bg-black/20 p-3">
                <p className="text-[11px] uppercase tracking-wide text-slate-500">Highlights</p>
                <div className="mt-2 space-y-2">
                  {(briefing.highlights ?? []).slice(0, 4).map((row, idx) => (
                    <div key={`${row.title}-${idx}`} className="text-xs">
                      <div className="text-slate-200">{row.title}</div>
                      <div className="mt-0.5 text-slate-500">{row.summary}</div>
                    </div>
                  ))}
                  {(briefing.highlights ?? []).length === 0 ? (
                    <p className="text-xs text-slate-500">No highlights in this window.</p>
                  ) : null}
                </div>
              </div>

              <div className="border border-line/70 bg-black/20 p-3">
                <p className="text-[11px] uppercase tracking-wide text-slate-500">Sources</p>
                <div className="mt-2 space-y-1.5">
                  {(briefing.sources ?? []).slice(0, 6).map((src, idx) => {
                    const label = src.label || `Source ${idx + 1}`;
                    const href = src.path || src.url || "";
                    if (!href) {
                      return (
                        <p key={`${label}-${idx}`} className="text-xs text-slate-400">
                          {label}
                        </p>
                      );
                    }
                    const external = href.startsWith("http://") || href.startsWith("https://");
                    return (
                      <Link
                        key={`${label}-${idx}`}
                        href={href}
                        prefetch={false}
                        target={external ? "_blank" : undefined}
                        rel={external ? "noreferrer" : undefined}
                        className="block truncate text-xs text-accentBlue hover:text-white"
                      >
                        {label}
                      </Link>
                    );
                  })}
                  {(briefing.sources ?? []).length === 0 ? (
                    <p className="text-xs text-slate-500">No sources available.</p>
                  ) : null}
                </div>
              </div>
            </div>
          </div>
        )}
      </article>
      {statusText ? <p className="mt-2 text-sm text-slate-400">{statusText}</p> : null}
    </section>
  );
}
