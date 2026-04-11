"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import type { User } from "@supabase/supabase-js";

import { LottieLoader } from "@/components/lottie-loader";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { getAuthSnapshot } from "@/lib/supabase/session";

function metadataString(user: User | null, keys: string[]): string {
  if (!user?.user_metadata) return "";
  for (const key of keys) {
    const value = user.user_metadata[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

export default function AccountPage() {
  const supabase = useMemo(() => getSupabaseBrowserClient(), []);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [user, setUser] = useState<User | null>(null);
  const [displayName, setDisplayName] = useState("");
  const [avatarUrl, setAvatarUrl] = useState("");
  const [statusText, setStatusText] = useState("");

  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return;
    }
    const supabaseClient = supabase;
    let mounted = true;
    getAuthSnapshot(supabaseClient).then((snapshot) => {
      if (!mounted) return;
      const nextUser = snapshot.user ?? null;
      setUser(nextUser);
      setDisplayName(metadataString(nextUser, ["nickname", "name", "full_name", "preferred_username"]));
      setAvatarUrl(metadataString(nextUser, ["avatar_url", "picture"]));
      if (snapshot.recoveredInvalidRefreshToken) {
        setStatusText("Session expired. Please sign in again.");
      }
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabaseClient.auth.onAuthStateChange((_event, session) => {
      const nextUser = session?.user ?? null;
      setUser(nextUser);
      setDisplayName(metadataString(nextUser, ["nickname", "name", "full_name", "preferred_username"]));
      setAvatarUrl(metadataString(nextUser, ["avatar_url", "picture"]));
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [supabase]);

  if (!supabase) {
    return (
      <section className="rounded-none border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold text-slate-100">Account Settings</h1>
        <p className="mt-3 text-sm text-amber-300">Supabase auth is not configured.</p>
      </section>
    );
  }

  if (loading) {
    return (
      <section className="rounded-none border border-line/80 bg-card/80 p-6 shadow-panel">
        <div className="grid place-items-center py-2">
          <LottieLoader size={96} />
        </div>
      </section>
    );
  }

  if (!user) {
    return (
      <section className="rounded-none border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold text-slate-100">Account Settings</h1>
        <p className="mt-3 text-sm text-slate-400">
          You are signed out. {" "}
          <Link href="/login?next=%2Faccount" className="text-accentBlue hover:text-white">
            Sign in
          </Link>{" "}
          to manage your profile.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <section className="rounded-none p-6 shadow-panel">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Account Settings</h1>
        <p className="mt-2 text-sm text-slate-400">Basic profile settings for your Ifty account.</p>
      </section>

      <section className="rounded-none border border-line/80 bg-card/80 p-6 shadow-panel">
        <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_220px]">
          <form
            className="space-y-4"
            onSubmit={async (event) => {
              event.preventDefault();
              setSaving(true);
              setStatusText("");
              try {
                const trimmedName = displayName.trim();
                const trimmedAvatar = avatarUrl.trim();
                const { error } = await supabase.auth.updateUser({
                  data: {
                    nickname: trimmedName || null,
                    avatar_url: trimmedAvatar || null,
                  },
                });
                if (error) throw error;
                setStatusText("Saved profile settings.");
              } catch (error) {
                setStatusText(`Failed to save: ${String(error)}`);
              } finally {
                setSaving(false);
              }
            }}
          >
            <div>
              <label className="mb-1 block text-xs uppercase tracking-wide text-slate-500">Email</label>
              <input
                type="text"
                value={user.email ?? ""}
                disabled
                className="w-full border border-line/80 bg-black/20 px-3 py-2 text-sm text-slate-400"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs uppercase tracking-wide text-slate-500">Display Name</label>
              <input
                type="text"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
                placeholder="How your name appears in the UI"
                className="search-pill w-full border border-line/80 bg-card/80 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-accentBlue/60"
              />
            </div>

            <div>
              <label className="mb-1 block text-xs uppercase tracking-wide text-slate-500">Avatar URL</label>
              <input
                type="url"
                value={avatarUrl}
                onChange={(event) => setAvatarUrl(event.target.value)}
                placeholder="https://..."
                className="search-pill w-full border border-line/80 bg-card/80 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-accentBlue/60"
              />
            </div>

            <div className="pt-1">
              <button
                type="submit"
                disabled={saving}
                className="inline-flex h-9 items-center border border-accentBlue/55 bg-accentBlue/15 px-4 text-sm font-medium text-slate-100 transition hover:bg-accentBlue/25 disabled:opacity-50"
              >
                {saving ? "Saving..." : "Save Changes"}
              </button>
            </div>

            {statusText ? <p className="text-sm text-slate-400">{statusText}</p> : null}
          </form>

          <div className="border border-line/80 bg-black/20 p-4">
            <p className="text-xs uppercase tracking-wide text-slate-500">Preview</p>
            <div className="mt-3 flex items-center gap-3">
              <div className="sidebar-circle h-12 w-12 overflow-hidden border border-line/80 bg-card/70">
                {avatarUrl.trim() ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={avatarUrl.trim()}
                    alt="Avatar preview"
                    className="sidebar-circle-media h-full w-full object-cover"
                    referrerPolicy="no-referrer"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center text-sm font-semibold text-slate-300">
                    {(displayName.trim() || user.email || "U").slice(0, 1).toUpperCase()}
                  </div>
                )}
              </div>
              <div>
                <div className="text-sm font-medium text-slate-100">{displayName.trim() || "No display name"}</div>
                <div className="max-w-[130px] truncate text-xs text-slate-500">{user.email}</div>
              </div>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
