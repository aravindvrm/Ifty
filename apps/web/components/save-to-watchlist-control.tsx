"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { Plus, X } from "lucide-react";

import {
  createWatchlist,
  getWatchlists,
  type Watchlist,
  type WatchlistItemType,
  upsertWatchlistItem,
} from "@/lib/api";
import { LottieLoader } from "@/components/lottie-loader";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { getAuthSnapshot } from "@/lib/supabase/session";

export function SaveToWatchlistControl({
  itemType,
  itemKey,
  itemLabel,
  itemSubtitle,
  compact = false,
  highlight = false,
}: {
  itemType: WatchlistItemType;
  itemKey: string;
  itemLabel: string;
  itemSubtitle?: string | null;
  compact?: boolean;
  highlight?: boolean;
}) {
  const supabase = useMemo(() => getSupabaseBrowserClient(), []);

  const [open, setOpen] = useState(false);
  const [ownerUserId, setOwnerUserId] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [lists, setLists] = useState<Watchlist[]>([]);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [statusText, setStatusText] = useState("");
  const [newListName, setNewListName] = useState("");
  const [createExpanded, setCreateExpanded] = useState(false);

  const eligibleLists = useMemo(() => {
    return lists.filter((list) => list.watchlist_type === itemType);
  }, [itemType, lists]);

  useEffect(() => {
    if (!open || !supabase) return;
    const supabaseClient = supabase;
    let cancelled = false;

    async function load() {
      setLoading(true);
      setStatusText("");
      try {
        const snapshot = await getAuthSnapshot(supabaseClient);
        if (cancelled) return;
        const userId = snapshot.user?.id ?? null;
        const token = snapshot.session?.access_token ?? null;
        setOwnerUserId(userId);
        setAccessToken(token);
        if (!userId || !token) {
          setLists([]);
          if (snapshot.recoveredInvalidRefreshToken) {
            setStatusText("Session expired. Please sign in again.");
          }
          return;
        }
        const response = await getWatchlists(token);
        if (cancelled) return;
        setLists(response.rows ?? []);
      } catch (error) {
        if (!cancelled) {
          setStatusText(`Failed to load watchlists: ${String(error)}`);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [open, supabase]);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  useEffect(() => {
    if (open) return;
    setCreateExpanded(false);
    setNewListName("");
  }, [open]);

  async function addToExisting(watchlist: Watchlist) {
    if (!ownerUserId || !accessToken) return;
    setBusy(true);
    setStatusText("");
    try {
      await upsertWatchlistItem(watchlist.watchlist_id, {
        item_type: itemType,
        item_key: itemKey,
        item_label: itemLabel,
        item_subtitle: itemSubtitle ?? null,
        metadata: {
          source: "explore_entity_view",
        },
      }, accessToken);
      setStatusText(`Added to ${watchlist.name}`);
    } catch (error) {
      setStatusText(`Watch failed: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function createAndWatch() {
    if (!ownerUserId || !accessToken) return;
    const name = newListName.trim();
    if (!name) {
      setStatusText("Enter a watchlist name");
      return;
    }
    setBusy(true);
    setStatusText("");
    try {
      const created = await createWatchlist({
        name,
        watchlist_type: itemType,
      }, accessToken);
      await upsertWatchlistItem(created.watchlist_id, {
        item_type: itemType,
        item_key: itemKey,
        item_label: itemLabel,
        item_subtitle: itemSubtitle ?? null,
        metadata: {
          source: "explore_entity_view",
        },
      }, accessToken);
      const refreshed = await getWatchlists(accessToken);
      setLists(refreshed.rows ?? []);
      setNewListName("");
      setCreateExpanded(false);
      setStatusText(`Created ${created.name} and added`);
    } catch (error) {
      setStatusText(`Create failed: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={[
          "inline-flex items-center justify-center gap-2 rounded-none border text-xs font-medium text-violet-200 transition hover:border-violet-300 hover:bg-violet-500/20 hover:text-white",
          compact ? "h-8 w-8 p-0" : "h-9 px-3",
          highlight ? "border-violet-300/70 bg-violet-500/20" : "border-violet-400/60 bg-violet-500/14",
        ].join(" ")}
        title="Watch"
        aria-label="Watch"
      >
        <Plus className="h-3.5 w-3.5" />
        {compact ? null : <span className="hidden md:inline">Watch</span>}
      </button>

      {open ? (
        <div className="fixed inset-0 z-[90] flex items-center justify-center px-4" role="dialog" aria-modal="true">
          <button
            type="button"
            aria-label="Close watch modal"
            className="absolute inset-0 bg-black/70 backdrop-blur-[1px]"
            onClick={() => setOpen(false)}
          />

          <div className="relative z-10 w-full max-w-md border border-line/80 bg-[#04070f]/95 p-4 pt-3 shadow-[0_24px_50px_rgba(0,0,0,0.55)]">
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="absolute right-1 top-1 inline-flex h-8 w-8 items-center justify-center border border-rose-400/55 bg-rose-500/12 text-rose-200 transition hover:bg-rose-500/22 hover:text-rose-100"
              aria-label="Close"
            >
              <X className="h-5 w-5" />
            </button>

            <div className="flex items-start justify-between gap-2 pb-2 pr-9">
              <div className="min-w-0">
                <p className="text-sm text-slate-300 truncate">
                  {itemType === "SECURITY" ? "Security" : "Institution"}: {itemLabel}
                </p>
              </div>
            </div>

            {!supabase ? (
              <p className="pt-3 text-xs text-amber-300">Supabase auth is not configured.</p>
            ) : loading ? (
              <div className="grid place-items-center py-2">
                <LottieLoader size={88} />
              </div>
            ) : !ownerUserId ? (
              <div className="pt-3 text-xs text-slate-400">
                <span>Sign in to watch this item. </span>
                <Link href="/login?next=%2Fexplore" className="text-accentBlue hover:text-white">
                  Go to sign in
                </Link>
              </div>
            ) : (
              <div className="space-y-3 pt-3">
                {eligibleLists.length > 0 ? (
                  <div className="space-y-2">
                    <p className="text-[11px] uppercase tracking-wide text-slate-500">Existing watchlists</p>
                    <div className="max-h-44 space-y-1 overflow-y-auto pr-1">
                      {eligibleLists.map((list) => (
                        <button
                          key={list.watchlist_id}
                          type="button"
                          disabled={busy}
                          onClick={() => addToExisting(list)}
                          className="flex w-full items-center justify-between gap-2 border border-line/70 bg-black/20 px-2 py-1.5 text-left text-xs text-slate-200 transition hover:border-accentBlue/60 hover:text-white disabled:opacity-50"
                        >
                          <span className="truncate">{list.name}</span>
                          <span className="text-slate-500">{list.item_count}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}

                <div className="space-y-2 pt-2">
                  {!createExpanded ? (
                    <div className="flex justify-end">
                      <button
                        type="button"
                        onClick={() => setCreateExpanded(true)}
                        disabled={busy}
                        className="inline-flex h-8 items-center border border-line/70 bg-black/20 px-2.5 text-xs text-slate-200 transition hover:border-accentBlue/60 hover:text-white disabled:opacity-50"
                      >
                        <span>New watchlist</span>
                      </button>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="flex items-center gap-2">
                        <input
                          type="text"
                          value={newListName}
                          onChange={(event) => setNewListName(event.target.value)}
                          placeholder="Watchlist name"
                          className="w-full border border-line/80 bg-card/80 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-accentBlue/60"
                        />
                        <button
                          type="button"
                          onClick={createAndWatch}
                          disabled={busy}
                          className="inline-flex h-9 shrink-0 items-center border border-accentBlue/55 bg-accentBlue/15 px-3 text-xs text-slate-100 transition hover:bg-accentBlue/25 disabled:opacity-50"
                        >
                          <span>{busy ? "Working..." : "Create"}</span>
                        </button>
                      </div>
                      <div className="flex justify-end">
                        <button
                          type="button"
                          onClick={() => {
                            setCreateExpanded(false);
                            setNewListName("");
                          }}
                          className="text-xs text-slate-500 transition hover:text-slate-300"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            )}

            {statusText ? <p className="pt-2 text-xs text-slate-400">{statusText}</p> : null}
          </div>
        </div>
      ) : null}
    </>
  );
}
