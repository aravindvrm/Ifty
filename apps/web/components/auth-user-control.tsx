"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CircleUserRound, LogIn, LogOut, Settings, ShieldAlert } from "lucide-react";

import { getSupabaseBrowserClient } from "@/lib/supabase/client";

export function AuthUserControl() {
  const router = useRouter();
  const supabase = useMemo(() => getSupabaseBrowserClient(), []);
  const [email, setEmail] = useState<string | null>(null);
  const [isSigningOut, setIsSigningOut] = useState(false);

  useEffect(() => {
    if (!supabase) return;

    let mounted = true;
    supabase.auth.getUser().then(({ data }) => {
      if (!mounted) return;
      setEmail(data.user?.email ?? null);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setEmail(session?.user?.email ?? null);
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [supabase]);

  return (
    <div className="group relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-label="Account menu"
        className="sidebar-circle inline-flex h-9 w-9 items-center justify-center rounded-full border border-line/80 bg-card/60 text-slate-300 transition hover:border-accentBlue/70 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accentBlue/70"
      >
        <CircleUserRound className="h-5 w-5" />
      </button>

      <div
        role="menu"
        className="pointer-events-none absolute right-0 top-[calc(100%+8px)] z-50 min-w-[240px] translate-y-1 border border-line/80 bg-[#04070f]/95 p-2 opacity-0 shadow-[0_12px_28px_rgba(0,0,0,0.45)] transition duration-150 group-hover:pointer-events-auto group-hover:translate-y-0 group-hover:opacity-100 group-focus-within:pointer-events-auto group-focus-within:translate-y-0 group-focus-within:opacity-100"
      >
        <div className="border-b border-line/70 px-2 pb-2 pt-1">
          <p className="text-[11px] uppercase tracking-wide text-slate-500">Account</p>
          <p className="mt-1 truncate text-xs text-slate-300">{email ?? "Not signed in"}</p>
        </div>

        <div className="space-y-1 px-1 py-2">
          {!supabase ? (
            <div className="inline-flex w-full items-center gap-2 px-2 py-1.5 text-xs text-amber-300/90">
              <ShieldAlert className="h-3.5 w-3.5" />
              <span>Supabase auth not configured</span>
            </div>
          ) : null}

          {!email ? (
            <button
              type="button"
              role="menuitem"
              onClick={() => router.push("/login")}
              className="inline-flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-300 transition hover:bg-white/[0.04] hover:text-white"
            >
              <LogIn className="h-3.5 w-3.5" />
              <span>Sign in</span>
            </button>
          ) : null}

          {email ? (
            <button
              type="button"
              role="menuitem"
              className="inline-flex w-full cursor-default items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-500"
              disabled
            >
              <Settings className="h-3.5 w-3.5" />
              <span>Profile settings (soon)</span>
            </button>
          ) : null}

          {email ? (
            <button
              type="button"
              role="menuitem"
              onClick={async () => {
                if (!supabase) return;
                setIsSigningOut(true);
                await supabase.auth.signOut();
                setIsSigningOut(false);
                router.push("/login");
              }}
              className="inline-flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-300 transition hover:bg-white/[0.04] hover:text-white disabled:opacity-50"
              disabled={isSigningOut}
            >
              <LogOut className="h-3.5 w-3.5" />
              <span>{isSigningOut ? "Signing out..." : "Sign out"}</span>
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
