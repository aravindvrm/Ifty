"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { ChevronDown, ChevronUp, Plus, Trash2, X } from "lucide-react";

import {
  createWatchlist,
  deleteWatchlist,
  deleteWatchlistItem,
  getWebhookSubscriptions,
  getWatchlists,
  updateWebhookSubscription,
  type WebhookSubscription,
  type Watchlist,
  type WatchlistItem,
  type WatchlistItemType,
  type WatchlistType,
  upsertWatchlistItem,
} from "@/lib/api";
import { EntitySearchInput, type EntitySuggestionItem } from "@/components/entity-search-input";
import { LottieLoader } from "@/components/lottie-loader";
import { getSupabaseBrowserClient } from "@/lib/supabase/client";
import { getAuthSnapshot } from "@/lib/supabase/session";

type DraftWatchItem = {
  item_type: WatchlistItemType;
  item_key: string;
  item_label: string;
  item_subtitle?: string | null;
};

type WatchlistAlertDraft = {
  include13dg: boolean;
  includeInsider: boolean;
  isActive: boolean;
};

function normalizeBooleanish(value: unknown, fallback: boolean): boolean {
  if (value === null || value === undefined) return fallback;
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  const raw = String(value).trim().toLowerCase();
  if (!raw) return fallback;
  if (["0", "false", "no", "off"].includes(raw)) return false;
  if (["1", "true", "yes", "on"].includes(raw)) return true;
  return fallback;
}

function getItemAlertPrefs(item: WatchlistItem): { include13dg: boolean; includeInsider: boolean } {
  const metadata = item.metadata;
  const alerts =
    metadata && typeof metadata === "object" && !Array.isArray(metadata)
      ? (metadata as Record<string, unknown>).alerts
      : null;
  const alertRecord =
    alerts && typeof alerts === "object" && !Array.isArray(alerts)
      ? (alerts as Record<string, unknown>)
      : null;
  return {
    include13dg: normalizeBooleanish(alertRecord?.include_13dg, true),
    includeInsider: item.item_type === "SECURITY" ? normalizeBooleanish(alertRecord?.include_insider, true) : false,
  };
}

function buildItemAlertMetadata(
  item: WatchlistItem,
  prefs: { include13dg: boolean; includeInsider: boolean }
): Record<string, unknown> {
  const base =
    item.metadata && typeof item.metadata === "object" && !Array.isArray(item.metadata)
      ? ({ ...item.metadata } as Record<string, unknown>)
      : {};
  const existingAlerts =
    base.alerts && typeof base.alerts === "object" && !Array.isArray(base.alerts)
      ? ({ ...(base.alerts as Record<string, unknown>) } as Record<string, unknown>)
      : {};
  existingAlerts.include_13dg = prefs.include13dg;
  existingAlerts.include_insider = item.item_type === "SECURITY" ? prefs.includeInsider : false;
  base.alerts = existingAlerts;
  return base;
}

function itemToken(itemType: WatchlistItemType, itemKey: string): string {
  return `${itemType}:${itemKey}`;
}

function itemHref(itemType: string, itemKey: string): string {
  if (itemType === "SECURITY") {
    return `/explore?type=security&key=${encodeURIComponent(itemKey)}`;
  }
  return `/explore?type=institution&key=${encodeURIComponent(itemKey)}`;
}

function toDraftItem(suggestion: EntitySuggestionItem, draftType: WatchlistType): DraftWatchItem | null {
  if (draftType === "SECURITY") {
    if (suggestion.kind !== "security") return null;
    const key = (suggestion.ticker ?? suggestion.primary ?? "").trim().toUpperCase();
    if (!key) return null;
    return {
      item_type: "SECURITY",
      item_key: key,
      item_label: suggestion.ticker ?? suggestion.primary,
      item_subtitle: suggestion.secondary,
    };
  }

  if (suggestion.kind !== "institution") return null;
  const managerId = String(suggestion.managerId ?? "").trim();
  if (!managerId) return null;
  return {
    item_type: "INSTITUTION",
    item_key: managerId,
    item_label: suggestion.primary,
    item_subtitle: suggestion.secondary,
  };
}

export default function WatchlistsPage() {
  const supabase = useMemo(() => getSupabaseBrowserClient(), []);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [userId, setUserId] = useState<string | null>(null);
  const [accessToken, setAccessToken] = useState<string | null>(null);
  const [watchlists, setWatchlists] = useState<Watchlist[]>([]);
  const [subscriptions, setSubscriptions] = useState<WebhookSubscription[]>([]);
  const [alertDraftByWatchlist, setAlertDraftByWatchlist] = useState<Record<string, WatchlistAlertDraft>>({});
  const [alertBusyByWatchlist, setAlertBusyByWatchlist] = useState<Record<string, boolean>>({});
  const [itemAlertBusyToken, setItemAlertBusyToken] = useState<string | null>(null);
  const [openWatchlistById, setOpenWatchlistById] = useState<Record<string, boolean>>({});
  const [statusText, setStatusText] = useState("");
  const [selectedItemsByWatchlist, setSelectedItemsByWatchlist] = useState<Record<string, string[]>>({});

  const [createOpen, setCreateOpen] = useState(false);
  const [draftName, setDraftName] = useState("");
  const [draftType, setDraftType] = useState<WatchlistType>("SECURITY");
  const [draftItems, setDraftItems] = useState<DraftWatchItem[]>([]);

  const subscriptionsByWatchlist = useMemo(() => {
    const grouped: Record<string, WebhookSubscription[]> = {};
    for (const subscription of subscriptions) {
      grouped[subscription.watchlist_id] = grouped[subscription.watchlist_id]
        ? [...grouped[subscription.watchlist_id], subscription]
        : [subscription];
    }
    return grouped;
  }, [subscriptions]);

  const primarySubscriptionByWatchlist = useMemo(() => {
    const map: Record<string, WebhookSubscription | null> = {};
    for (const watchlist of watchlists) {
      map[watchlist.watchlist_id] = subscriptionsByWatchlist[watchlist.watchlist_id]?.[0] ?? null;
    }
    return map;
  }, [watchlists, subscriptionsByWatchlist]);

  async function refresh(accessTokenValue: string) {
    const [watchlistResponse, subscriptionResponse] = await Promise.all([
      getWatchlists(accessTokenValue),
      getWebhookSubscriptions(accessTokenValue),
    ]);
    setWatchlists(watchlistResponse.rows ?? []);
    setSubscriptions(subscriptionResponse.rows ?? []);
    setOpenWatchlistById((prev) => {
      const rows = watchlistResponse.rows ?? [];
      const valid = new Set(rows.map((row) => row.watchlist_id));
      const next: Record<string, boolean> = {};
      let hasOpen = false;
      Object.entries(prev).forEach(([watchlistId, isOpen]) => {
        if (!valid.has(watchlistId)) return;
        if (!isOpen) return;
        next[watchlistId] = true;
        hasOpen = true;
      });
      if (!hasOpen && rows[0]?.watchlist_id) {
        next[rows[0].watchlist_id] = true;
      }
      return next;
    });
    setSelectedItemsByWatchlist((prev) => {
      const valid = new Set((watchlistResponse.rows ?? []).map((row) => row.watchlist_id));
      const next: Record<string, string[]> = {};
      Object.entries(prev).forEach(([watchlistId, tokens]) => {
        if (!valid.has(watchlistId)) return;
        if (tokens.length > 0) next[watchlistId] = tokens;
      });
      return next;
    });
  }

  function resetCreateState(nextType: WatchlistType = "SECURITY") {
    setDraftName("");
    setDraftType(nextType);
    setDraftItems([]);
  }

  useEffect(() => {
    setAlertDraftByWatchlist((prev) => {
      const next: Record<string, WatchlistAlertDraft> = {};
      for (const watchlist of watchlists) {
        const subscription = primarySubscriptionByWatchlist[watchlist.watchlist_id];
        const prior = prev[watchlist.watchlist_id];
        const items = watchlist.items ?? [];
        const hasItems = items.length > 0;
        const securityItems = items.filter((item) => item.item_type === "SECURITY");

        const include13dg = hasItems
          ? items.every((item) => getItemAlertPrefs(item).include13dg)
          : (subscription ? Boolean(subscription.include_13dg) : (prior?.include13dg ?? true));

        const includeInsider = watchlist.watchlist_type === "SECURITY"
          ? (
            securityItems.length > 0
              ? securityItems.every((item) => getItemAlertPrefs(item).includeInsider)
              : (subscription ? Boolean(subscription.include_insider) : (prior?.includeInsider ?? true))
          )
          : false;

        next[watchlist.watchlist_id] = {
          include13dg,
          includeInsider,
          isActive: subscription ? Boolean(subscription.is_active) : (prior?.isActive ?? true),
        };
      }
      return next;
    });
  }, [watchlists, primarySubscriptionByWatchlist]);

  useEffect(() => {
    if (!supabase) {
      setLoading(false);
      return;
    }
    const supabaseClient = supabase;
    let mounted = true;

    async function load() {
      setLoading(true);
      setStatusText("");
      try {
        const snapshot = await getAuthSnapshot(supabaseClient);
        if (!mounted) return;
        const id = snapshot.user?.id ?? null;
        const token = snapshot.session?.access_token ?? null;
        setUserId(id);
        setAccessToken(token);
        if (!id || !token) {
          setWatchlists([]);
          setSubscriptions([]);
          setAlertDraftByWatchlist({});
          setOpenWatchlistById({});
          if (snapshot.recoveredInvalidRefreshToken) {
            setStatusText("Session expired. Please sign in again.");
          }
          return;
        }
        await refresh(token);
      } catch (error) {
        if (mounted) setStatusText(`Failed to load watchlists: ${String(error)}`);
      } finally {
        if (mounted) setLoading(false);
      }
    }

    void load();

    const {
      data: { subscription },
    } = supabaseClient.auth.onAuthStateChange(async (_event, session) => {
      const id = session?.user?.id ?? null;
      const token = session?.access_token ?? null;
      setUserId(id);
      setAccessToken(token);
      if (!id || !token) {
        setWatchlists([]);
        setSubscriptions([]);
        setAlertDraftByWatchlist({});
        setOpenWatchlistById({});
        return;
      }
      try {
        await refresh(token);
      } catch {
        // ignore transient refresh errors
      }
    });

    return () => {
      mounted = false;
      subscription.unsubscribe();
    };
  }, [supabase]);

  useEffect(() => {
    if (!createOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setCreateOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [createOpen]);

  async function applyWatchlistAlertPatch(
    watchlist: Watchlist,
    patch: Partial<Pick<WatchlistAlertDraft, "include13dg" | "includeInsider">>
  ) {
    if (!accessToken) {
      setStatusText("Sign in to manage alerts.");
      return;
    }
    const watchlistId = watchlist.watchlist_id;
    const currentDraft = alertDraftByWatchlist[watchlistId] ?? {
      include13dg: true,
      includeInsider: true,
      isActive: true,
    };
    const nextDraft = {
      ...currentDraft,
      ...patch,
    };
    const current = primarySubscriptionByWatchlist[watchlistId];
    setAlertDraftByWatchlist((prev) => ({
      ...prev,
      [watchlistId]: nextDraft,
    }));
    setAlertBusyByWatchlist((prev) => ({ ...prev, [watchlistId]: true }));
    setStatusText("");
    try {
      await Promise.all(
        watchlist.items.map((item) => {
          const currentItemPrefs = getItemAlertPrefs(item);
          const nextItemPrefs = {
            include13dg: patch.include13dg ?? currentItemPrefs.include13dg,
            includeInsider:
              item.item_type === "SECURITY"
                ? (patch.includeInsider ?? currentItemPrefs.includeInsider)
                : false,
          };
          const changed =
            nextItemPrefs.include13dg !== currentItemPrefs.include13dg ||
            nextItemPrefs.includeInsider !== currentItemPrefs.includeInsider;
          if (!changed) return Promise.resolve();
          return upsertWatchlistItem(
            watchlist.watchlist_id,
            {
              item_type: item.item_type,
              item_key: item.item_key,
              item_label: item.item_label ?? item.item_key,
              item_subtitle: item.item_subtitle ?? null,
              metadata: buildItemAlertMetadata(item, nextItemPrefs),
            },
            accessToken
          );
        })
      );

      if (current) {
        await updateWebhookSubscription(accessToken, current.webhook_subscription_id, {
          include_13dg: nextDraft.include13dg ? 1 : 0,
          include_insider: nextDraft.includeInsider ? 1 : 0,
          is_active: nextDraft.isActive ? 1 : 0,
        });
      }
      await refresh(accessToken);
      if (current) {
        setStatusText(`Global alerts updated for "${watchlist.name}".`);
      } else {
        setStatusText(`Global alert defaults updated for "${watchlist.name}".`);
      }
    } catch (error) {
      setAlertDraftByWatchlist((prev) => ({
        ...prev,
        [watchlistId]: currentDraft,
      }));
      setStatusText(`Alert update failed: ${String(error)}`);
    } finally {
      setAlertBusyByWatchlist((prev) => ({ ...prev, [watchlistId]: false }));
    }
  }

  async function updateItemAlertPrefs(
    watchlist: Watchlist,
    item: WatchlistItem,
    patch: Partial<{ include13dg: boolean; includeInsider: boolean }>
  ) {
    if (!accessToken) return;
    const current = getItemAlertPrefs(item);
    const next = {
      include13dg: patch.include13dg ?? current.include13dg,
      includeInsider: patch.includeInsider ?? current.includeInsider,
    };
    const token = `${watchlist.watchlist_id}:${item.item_type}:${item.item_key}`;
    setItemAlertBusyToken(token);
    setStatusText("");
    try {
      await upsertWatchlistItem(
        watchlist.watchlist_id,
        {
          item_type: item.item_type,
          item_key: item.item_key,
          item_label: item.item_label ?? item.item_key,
          item_subtitle: item.item_subtitle ?? null,
          metadata: buildItemAlertMetadata(item, next),
        },
        accessToken
      );
      await refresh(accessToken);
      setStatusText(`Alert preferences updated for ${item.item_label ?? item.item_key}.`);
    } catch (error) {
      setStatusText(`Item alert update failed: ${String(error)}`);
    } finally {
      setItemAlertBusyToken(null);
    }
  }

  if (!supabase) {
    return (
      <section className="rounded-none border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold text-slate-100">Watchlists</h1>
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

  if (!userId || !accessToken) {
    return (
      <section className="rounded-none border border-line/80 bg-card/80 p-6 shadow-panel">
        <h1 className="text-2xl font-semibold text-slate-100">Watchlists</h1>
        <p className="mt-3 text-sm text-slate-400">
          You are signed out. {" "}
          <Link href="/login?next=%2Fwatchlists" className="text-accentBlue hover:text-white">
            Sign in
          </Link>{" "}
          to create and manage watchlists.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <section>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-slate-100">Watchlists</h1>
            <p className="mt-2 text-sm text-slate-400">Track securities and institutions in dedicated watchlists.</p>
          </div>
          <button
            type="button"
            onClick={() => {
              resetCreateState("SECURITY");
              setCreateOpen(true);
            }}
            className="inline-flex h-9 items-center gap-1.5 border border-accentBlue/55 bg-accentBlue/15 px-3 text-sm font-medium text-slate-100 transition hover:bg-accentBlue/25"
          >
            <Plus className="h-4 w-4" />
            <span>Create</span>
          </button>
        </div>
      </section>

      <section className="space-y-3">
        {watchlists.length === 0 ? (
          <div className="rounded-none border border-line/80 bg-card/80 p-5 text-sm text-slate-500 shadow-panel">
            No watchlists yet. Click Create to start a security or institution watchlist.
          </div>
        ) : (
          watchlists.map((watchlist) => {
            const isOpen = Boolean(openWatchlistById[watchlist.watchlist_id]);
            const alertDraft = alertDraftByWatchlist[watchlist.watchlist_id] ?? {
              include13dg: true,
              includeInsider: true,
              isActive: true,
            };
            const alertBusy = Boolean(alertBusyByWatchlist[watchlist.watchlist_id]);
            const isSecurityWatchlist = watchlist.watchlist_type === "SECURITY";
            const insiderEnabledDisplay = isSecurityWatchlist ? alertDraft.includeInsider : false;
            return (
              <article key={watchlist.watchlist_id} className="rounded-none">
                <header className="border border-line/70 bg-[var(--bg-soft)] px-4 py-3">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setOpenWatchlistById((prev) => ({
                            ...prev,
                            [watchlist.watchlist_id]: !prev[watchlist.watchlist_id],
                          }))
                        }
                        className="inline-flex min-w-0 items-center gap-2 border-0 bg-transparent px-0 py-0 text-left"
                      >
                        <span className="truncate text-base font-semibold text-slate-100">{watchlist.name}</span>
                        <span className="text-xs text-slate-500">{watchlist.item_count} items</span>
                        {isOpen ? (
                          <ChevronUp className="h-4 w-4 text-slate-500" />
                        ) : (
                          <ChevronDown className="h-4 w-4 text-slate-500" />
                        )}
                      </button>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        disabled={alertBusy || busy}
                        onClick={() =>
                          void applyWatchlistAlertPatch(watchlist, {
                            include13dg: !alertDraft.include13dg,
                          })
                        }
                        className="inline-flex items-center gap-2 border-0 bg-transparent px-0 py-0 text-slate-300 transition hover:text-white disabled:opacity-50"
                        aria-label={`Toggle 13D/G alerts for ${watchlist.name}`}
                      >
                        <span className="text-[11px] font-medium tracking-wide">13D/G</span>
                        <span
                          className={[
                            "relative inline-flex h-5 w-9 items-center rounded-full transition",
                            alertDraft.include13dg
                              ? "bg-emerald-400/25"
                              : "bg-black/30",
                          ].join(" ")}
                        >
                          <span
                            className={[
                              "h-3.5 w-3.5 rounded-full bg-slate-100 transition-transform duration-200",
                              alertDraft.include13dg ? "translate-x-[18px]" : "translate-x-[2px]",
                            ].join(" ")}
                          />
                        </span>
                      </button>
                      <button
                        type="button"
                        disabled={alertBusy || busy || !isSecurityWatchlist}
                        title={!isSecurityWatchlist ? "Insider alerts apply to security watchlists." : undefined}
                        onClick={() =>
                          void applyWatchlistAlertPatch(watchlist, {
                            includeInsider: !alertDraft.includeInsider,
                          })
                        }
                        className="inline-flex items-center gap-2 border-0 bg-transparent px-0 py-0 text-slate-300 transition hover:text-white disabled:opacity-50"
                        aria-label={`Toggle insider alerts for ${watchlist.name}`}
                      >
                        <span className="text-[11px] font-medium tracking-wide">Insider</span>
                        <span
                          className={[
                            "relative inline-flex h-5 w-9 items-center rounded-full transition",
                            insiderEnabledDisplay
                              ? "bg-emerald-400/25"
                              : "bg-black/30",
                          ].join(" ")}
                        >
                          <span
                            className={[
                              "h-3.5 w-3.5 rounded-full bg-slate-100 transition-transform duration-200",
                              insiderEnabledDisplay ? "translate-x-[18px]" : "translate-x-[2px]",
                            ].join(" ")}
                          />
                        </span>
                      </button>
                      <button
                        type="button"
                        onClick={async () => {
                          if (!confirm(`Delete watchlist \"${watchlist.name}\"?`)) return;
                          if (!accessToken) return;
                          setBusy(true);
                          setStatusText("");
                          try {
                            await deleteWatchlist(watchlist.watchlist_id, accessToken);
                            await refresh(accessToken);
                            setStatusText("Watchlist deleted.");
                          } catch (error) {
                            setStatusText(`Delete failed: ${String(error)}`);
                          } finally {
                            setBusy(false);
                          }
                        }}
                        className="inline-flex h-8 w-8 items-center justify-center border border-rose-400/50 bg-rose-400/10 text-rose-300 transition hover:bg-rose-400/20"
                        aria-label={`Delete watchlist ${watchlist.name}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                </header>

                {isOpen ? (
                  <div className="space-y-4 p-4">
                    {watchlist.items.length === 0 ? (
                      <p className="text-sm text-slate-500">No items watched yet.</p>
                    ) : (
                      <div className="space-y-2">
                        <div className="flex items-center justify-end gap-2">
                          {(() => {
                            const selectedCount = (selectedItemsByWatchlist[watchlist.watchlist_id] ?? []).length;
                            if (!selectedCount) return null;
                            return (
                              <button
                                type="button"
                                disabled={busy}
                                onClick={async () => {
                                  const selected = selectedItemsByWatchlist[watchlist.watchlist_id] ?? [];
                                  if (!selected.length) return;
                                  if (!confirm(`Remove ${selected.length} selected item${selected.length === 1 ? "" : "s"} from "${watchlist.name}"?`)) {
                                    return;
                                  }
                                  if (!accessToken) return;
                                  setBusy(true);
                                  setStatusText("");
                                  try {
                                    await Promise.all(
                                      selected.map((token) => {
                                        const [itemTypeRaw, ...keyParts] = token.split(":");
                                        const itemKey = keyParts.join(":");
                                        return deleteWatchlistItem(watchlist.watchlist_id, {
                                          item_type: itemTypeRaw as WatchlistItemType,
                                          item_key: itemKey,
                                        }, accessToken);
                                      })
                                    );
                                    await refresh(accessToken);
                                    setSelectedItemsByWatchlist((prev) => ({
                                      ...prev,
                                      [watchlist.watchlist_id]: [],
                                    }));
                                    setStatusText(`${selected.length} item${selected.length === 1 ? "" : "s"} removed.`);
                                  } catch (error) {
                                    setStatusText(`Remove failed: ${String(error)}`);
                                  } finally {
                                    setBusy(false);
                                  }
                                }}
                                className="inline-flex h-8 items-center border border-rose-400/50 bg-rose-400/10 px-2.5 text-xs text-rose-300 transition hover:bg-rose-400/20 disabled:opacity-50"
                              >
                                Remove selected ({selectedCount})
                              </button>
                            );
                          })()}
                        </div>

                        <div className="overflow-x-auto border border-line/70">
                          <table className="min-w-full divide-y divide-line/60 text-sm">
                            <thead>
                              <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                                <th className="px-3 py-2">Type</th>
                                <th className="px-3 py-2">Item</th>
                                <th className="px-3 py-2">Key</th>
                                <th className="px-3 py-2 text-center">13D/G</th>
                                <th className="px-3 py-2 text-center">Insider</th>
                                <th className="px-3 py-2">Added</th>
                                <th className="px-3 py-2 text-right">Remove</th>
                              </tr>
                            </thead>
                            <tbody className="divide-y divide-line/50 text-slate-300">
                              {watchlist.items.map((item) => (
                                <tr key={item.watchlist_item_id}>
                                  <td className="px-3 py-2 text-xs text-slate-500">{item.item_type}</td>
                                  <td className="px-3 py-2">
                                    <Link
                                      prefetch={false}
                                      href={itemHref(item.item_type, item.item_key)}
                                      className="text-accentBlue hover:text-white"
                                    >
                                      {item.item_label || item.item_key}
                                    </Link>
                                    {item.item_subtitle ? <div className="text-xs text-slate-500">{item.item_subtitle}</div> : null}
                                  </td>
                                  <td className="px-3 py-2 text-xs text-slate-400">{item.item_key}</td>
                                  <td className="px-3 py-2 text-center">
                                    {(() => {
                                      const prefs = getItemAlertPrefs(item);
                                      const busyToken = `${watchlist.watchlist_id}:${item.item_type}:${item.item_key}`;
                                      return (
                                        <button
                                          type="button"
                                          disabled={itemAlertBusyToken === busyToken}
                                          onClick={() =>
                                            void updateItemAlertPrefs(watchlist, item, {
                                              include13dg: !prefs.include13dg,
                                            })
                                          }
                                          className={[
                                            "inline-flex h-7 min-w-[44px] items-center justify-center border px-2 text-[11px] transition disabled:opacity-50",
                                            prefs.include13dg
                                              ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-300"
                                              : "border-line/70 text-slate-400 hover:border-slate-400/70",
                                          ].join(" ")}
                                        >
                                          {prefs.include13dg ? "On" : "Off"}
                                        </button>
                                      );
                                    })()}
                                  </td>
                                  <td className="px-3 py-2 text-center">
                                    {item.item_type === "SECURITY" ? (
                                      (() => {
                                        const prefs = getItemAlertPrefs(item);
                                        const busyToken = `${watchlist.watchlist_id}:${item.item_type}:${item.item_key}`;
                                        return (
                                          <button
                                            type="button"
                                            disabled={itemAlertBusyToken === busyToken}
                                            onClick={() =>
                                              void updateItemAlertPrefs(watchlist, item, {
                                                includeInsider: !prefs.includeInsider,
                                              })
                                            }
                                            className={[
                                              "inline-flex h-7 min-w-[44px] items-center justify-center border px-2 text-[11px] transition disabled:opacity-50",
                                              prefs.includeInsider
                                                ? "border-emerald-400/50 bg-emerald-400/10 text-emerald-300"
                                                : "border-line/70 text-slate-400 hover:border-slate-400/70",
                                            ].join(" ")}
                                          >
                                            {prefs.includeInsider ? "On" : "Off"}
                                          </button>
                                        );
                                      })()
                                    ) : (
                                      <span className="text-xs text-slate-600">-</span>
                                    )}
                                  </td>
                                  <td className="px-3 py-2 text-xs text-slate-500">{item.added_at ?? "-"}</td>
                                  <td className="px-3 py-2 text-right">
                                    {(() => {
                                      const token = itemToken(item.item_type, item.item_key);
                                      const selected = (selectedItemsByWatchlist[watchlist.watchlist_id] ?? []).includes(token);
                                      return (
                                        <button
                                          type="button"
                                          onClick={() => {
                                            setSelectedItemsByWatchlist((prev) => {
                                              const prior = prev[watchlist.watchlist_id] ?? [];
                                              const exists = prior.includes(token);
                                              const next = exists
                                                ? prior.filter((x) => x !== token)
                                                : [...prior, token];
                                              return {
                                                ...prev,
                                                [watchlist.watchlist_id]: next,
                                              };
                                            });
                                          }}
                                          className={[
                                            "inline-flex h-7 w-7 items-center justify-center border text-xs transition",
                                            selected
                                              ? "border-rose-300/70 bg-rose-500/20 text-rose-200"
                                              : "border-line/70 text-slate-300 hover:border-rose-400/60 hover:text-rose-200",
                                          ].join(" ")}
                                          aria-label={selected ? "Unselect item for removal" : "Select item for removal"}
                                        >
                                          -
                                        </button>
                                      );
                                    })()}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </div>
                    )}
                  </div>
                ) : null}
              </article>
            );
          })
        )}
      </section>

      {createOpen ? (
        <div className="fixed inset-0 z-[95] flex items-center justify-center px-4" role="dialog" aria-modal="true">
          <button
            type="button"
            className="absolute inset-0 bg-black/70 backdrop-blur-[1px]"
            onClick={() => setCreateOpen(false)}
            aria-label="Close create watchlist modal"
          />

          <div className="relative z-10 w-full max-w-2xl border border-line/80 bg-[#04070f]/96 p-4 shadow-[0_24px_50px_rgba(0,0,0,0.55)]">
            <div className="flex items-start justify-between gap-2 border-b border-line/70 pb-2">
              <div>
                <h2 className="text-base font-semibold text-slate-100">Create Watchlist</h2>
                <p className="mt-1 text-xs text-slate-500">Name it, pick type, then add items before creating.</p>
              </div>
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                className="inline-flex h-7 w-7 items-center justify-center border border-line/70 text-slate-400 transition hover:text-white"
                aria-label="Close"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>

            <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_170px]">
              <input
                type="text"
                value={draftName}
                onChange={(event) => setDraftName(event.target.value)}
                placeholder="Watchlist name"
                className="search-pill border border-line/80 bg-card/80 px-3 py-2 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-accentBlue/60"
              />
              <select
                value={draftType}
                onChange={(event) => {
                  const nextType = event.target.value as WatchlistType;
                  setDraftType(nextType);
                  setDraftItems([]);
                }}
                className="search-pill border border-line/80 bg-card/80 px-3 py-2 text-sm text-slate-200 outline-none focus:border-accentBlue/60"
              >
                <option value="SECURITY">Security</option>
                <option value="INSTITUTION">Institution</option>
              </select>
            </div>

            <div className="mt-3">
              <EntitySearchInput
                key={`watchlist-builder-${draftType}`}
                placeholder={draftType === "SECURITY" ? "Search securities to add..." : "Search institutions to add..."}
                showIcon
                includeSecurities={draftType === "SECURITY"}
                includeInstitutions={draftType === "INSTITUTION"}
                navigateOnSelect={false}
                securityLimit={12}
                institutionLimit={12}
                className="relative"
                inputClassName="search-pill w-full border border-line/80 bg-card/80 py-2.5 pl-10 pr-3 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-accentBlue/60"
                dropdownClassName="absolute left-0 right-0 top-[calc(100%+8px)] z-40 overflow-hidden border border-line/80 bg-[#02050c]"
                onSelectSuggestion={(suggestion) => {
                  const next = toDraftItem(suggestion, draftType);
                  if (!next) return;
                  setDraftItems((prev) => {
                    const exists = prev.some((item) => item.item_type === next.item_type && item.item_key === next.item_key);
                    if (exists) return prev;
                    return [...prev, next];
                  });
                }}
              />
            </div>

            <div className="mt-3 border border-line/70 bg-black/20 p-2">
              <p className="text-[11px] uppercase tracking-wide text-slate-500">Items to add ({draftItems.length})</p>
              {draftItems.length === 0 ? (
                <p className="mt-2 text-xs text-slate-500">Use search above to add items.</p>
              ) : (
                <div className="mt-2 max-h-44 space-y-1 overflow-y-auto pr-1">
                  {draftItems.map((item) => (
                    <div key={`${item.item_type}:${item.item_key}`} className="flex items-center justify-between gap-2 border border-line/70 px-2 py-1.5 text-xs text-slate-200">
                      <div className="min-w-0">
                        <p className="truncate">{item.item_label}</p>
                        {item.item_subtitle ? <p className="truncate text-slate-500">{item.item_subtitle}</p> : null}
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setDraftItems((prev) => prev.filter((x) => !(x.item_type === item.item_type && x.item_key === item.item_key)));
                        }}
                        className="inline-flex h-6 w-6 items-center justify-center border border-line/70 text-slate-400 transition hover:text-rose-300"
                        aria-label="Remove item"
                      >
                        <X className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="mt-4 flex items-center gap-2">
              <button
                type="button"
                onClick={async () => {
                  const name = draftName.trim();
                  if (!name) {
                    setStatusText("Enter a watchlist name.");
                    return;
                  }
                  if (!accessToken) {
                    setStatusText("Sign in to create watchlists.");
                    return;
                  }
                  setBusy(true);
                  setStatusText("");
                  try {
                    const created = await createWatchlist({
                      name,
                      watchlist_type: draftType,
                    }, accessToken);
                    for (const item of draftItems) {
                      await upsertWatchlistItem(created.watchlist_id, {
                        item_type: item.item_type,
                        item_key: item.item_key,
                        item_label: item.item_label,
                        item_subtitle: item.item_subtitle ?? null,
                        metadata: {
                          source: "watchlist_create_modal",
                        },
                      }, accessToken);
                    }
                    await refresh(accessToken);
                    setCreateOpen(false);
                    resetCreateState(draftType);
                    setStatusText("Watchlist created.");
                  } catch (error) {
                    setStatusText(`Create failed: ${String(error)}`);
                  } finally {
                    setBusy(false);
                  }
                }}
                disabled={busy}
                className="inline-flex h-9 items-center gap-1.5 border border-accentBlue/55 bg-accentBlue/15 px-3 text-sm text-slate-100 transition hover:bg-accentBlue/25 disabled:opacity-50"
              >
                <Plus className="h-4 w-4" />
                <span>{busy ? "Creating..." : "Create Watchlist"}</span>
              </button>
              <button
                type="button"
                onClick={() => setCreateOpen(false)}
                className="inline-flex h-9 items-center border border-line/70 px-3 text-sm text-slate-300 transition hover:text-white"
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      ) : null}

      {statusText ? <p className="text-sm text-slate-400">{statusText}</p> : null}
    </div>
  );
}
