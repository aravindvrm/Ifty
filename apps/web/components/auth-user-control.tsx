"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bookmark, LogOut, Settings, ShieldAlert } from "lucide-react";
import type { User } from "@supabase/supabase-js";

import { getSupabaseBrowserClient } from "@/lib/supabase/client";

function metadataValue(user: User | null, keys: string[]): string | null {
  if (!user?.user_metadata) return null;
  for (const key of keys) {
    const value = user.user_metadata[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

function profileName(user: User | null): string | null {
  const explicit = metadataValue(user, ["nickname", "nick_name", "preferred_username", "name", "full_name", "user_name"]);
  if (explicit) return explicit;
  const email = user?.email?.trim();
  if (!email) return null;
  const local = email.split("@")[0]?.trim();
  return local || email;
}

function profileAvatar(user: User | null): string | null {
  return metadataValue(user, ["avatar_url", "picture"]);
}

function initialsFromName(name: string | null): string {
  if (!name) return "U";
  const parts = name.trim().split(/\s+/).slice(0, 2);
  const initials = parts.map((x) => x[0]?.toUpperCase() || "").join("");
  return initials || "U";
}

export function AuthUserControl() {
  const router = useRouter();
  const supabase = useMemo(() => getSupabaseBrowserClient(), []);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const [user, setUser] = useState<User | null>(null);
  const [menuPinned, setMenuPinned] = useState(false);
  const [menuHovered, setMenuHovered] = useState(false);
  const [isSigningOut, setIsSigningOut] = useState(false);
  const [avatarLoadError, setAvatarLoadError] = useState(false);

  const displayName = useMemo(() => profileName(user), [user]);
  const avatarUrl = useMemo(() => profileAvatar(user), [user]);
  const initials = useMemo(() => initialsFromName(displayName), [displayName]);
  const menuOpen = menuPinned || menuHovered;

  useEffect(() => {
    if (!supabase) return;

    let mounted = true;
    supabase.auth.getUser().then(({ data }) => {
      if (!mounted) return;
      setUser(data.user ?? null);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [supabase]);

  useEffect(() => {
    setAvatarLoadError(false);
  }, [avatarUrl]);

  useEffect(() => {
    if (!menuOpen) return;
    const onPointerDown = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (target && rootRef.current && !rootRef.current.contains(target)) {
        setMenuHovered(false);
        setMenuPinned(false);
      }
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [menuOpen]);

  if (!supabase) {
    return (
      <div className="inline-flex items-center gap-2 px-2 text-xs text-amber-300/90">
        <ShieldAlert className="h-3.5 w-3.5" />
        <span>Auth unavailable</span>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="inline-flex items-center gap-2">
        <Link
          href="/login"
          className="inline-flex h-9 items-center justify-center rounded-full border border-line/80 bg-card/60 px-3.5 text-xs font-medium text-slate-200 transition hover:border-accentBlue/70 hover:text-white"
        >
          Sign in
        </Link>
        <Link
          href="/signup"
          className="inline-flex h-9 items-center justify-center rounded-full border border-accentBlue/55 bg-accentBlue/15 px-3.5 text-xs font-medium text-slate-100 transition hover:bg-accentBlue/25"
        >
          Sign up
        </Link>
      </div>
    );
  }

  return (
    <div
      ref={rootRef}
      className="relative"
      onMouseEnter={() => setMenuHovered(true)}
      onMouseLeave={() => setMenuHovered(false)}
    >
      <button
        type="button"
        aria-haspopup="menu"
        aria-label="Account menu"
        aria-expanded={menuOpen}
        onClick={() => setMenuPinned((value) => !value)}
        className="sidebar-circle inline-flex h-9 w-9 shrink-0 appearance-none items-center justify-center overflow-hidden rounded-full border border-line/80 bg-card/60 p-0 text-slate-200 transition hover:border-accentBlue/70 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accentBlue/70"
      >
        {avatarUrl && !avatarLoadError ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={avatarUrl}
            alt={`${displayName ?? "User"} avatar`}
            className="sidebar-circle-media block h-full w-full object-cover object-center"
            referrerPolicy="no-referrer"
            onError={() => setAvatarLoadError(true)}
          />
        ) : (
          <span className="text-xs font-semibold tracking-wide">{initials}</span>
        )}
      </button>

      <div
        role="menu"
        className={`absolute right-0 top-full z-50 min-w-[240px] pt-2 transition duration-150 ${
          menuOpen ? "pointer-events-auto translate-y-0 opacity-100" : "pointer-events-none translate-y-1 opacity-0"
        }`}
      >
        <div className="border border-line/80 bg-[#04070f]/95 p-2 shadow-[0_12px_28px_rgba(0,0,0,0.45)]">
          <div className="border-b border-line/70 px-2 pb-2 pt-1">
            <p className="truncate text-sm text-slate-200">{displayName ?? "Signed in"}</p>
          </div>

          <div className="space-y-1 px-1 py-2">
            <Link
              href="/account"
              role="menuitem"
              onClick={() => {
                setMenuHovered(false);
                setMenuPinned(false);
              }}
              className="inline-flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-300 transition hover:bg-white/[0.04] hover:text-white"
            >
              <Settings className="h-3.5 w-3.5" />
              <span>Account settings</span>
            </Link>

            <Link
              href="/watchlists"
              role="menuitem"
              onClick={() => {
                setMenuHovered(false);
                setMenuPinned(false);
              }}
              className="inline-flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-300 transition hover:bg-white/[0.04] hover:text-white"
            >
              <Bookmark className="h-3.5 w-3.5" />
              <span>Watchlists</span>
            </Link>

            <button
              type="button"
              role="menuitem"
              onClick={async () => {
                setIsSigningOut(true);
                await supabase.auth.signOut();
                setIsSigningOut(false);
                setMenuHovered(false);
                setMenuPinned(false);
                router.push("/explore");
              }}
              className="inline-flex w-full items-center gap-2 px-2 py-1.5 text-left text-xs text-slate-300 transition hover:bg-white/[0.04] hover:text-white disabled:opacity-50"
              disabled={isSigningOut}
            >
              <LogOut className="h-3.5 w-3.5" />
              <span>{isSigningOut ? "Signing out..." : "Sign out"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
