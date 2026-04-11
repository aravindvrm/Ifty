"use client";

import { useEffect, useMemo, useState } from "react";
import { RefreshCw, Send, TestTube2, Trash2 } from "lucide-react";

import { LottieLoader } from "@/components/lottie-loader";
import {
  createWebhookSubscription,
  deleteWebhookSubscription,
  dispatchWebhookAlerts,
  getWebhookDeliveries,
  getWebhookSubscriptions,
  testWebhookSubscription,
  type Watchlist,
  type WebhookDeliveriesResponse,
  type WebhookSubscriptionsResponse,
} from "@/lib/api";

type Props = {
  accessToken: string;
  watchlists: Watchlist[];
};

type DeliveryRow = WebhookDeliveriesResponse["rows"][number];
type SubscriptionRow = WebhookSubscriptionsResponse["rows"][number];

function toStatusClass(status: string): string {
  const value = String(status || "").toLowerCase();
  const base = "inline-flex rounded-none border px-2 py-0.5 text-[11px]";
  if (value === "queued" || value === "sent") {
    return `${base} border-emerald-400/40 bg-emerald-400/10 text-emerald-300`;
  }
  if (value === "failed") {
    return `${base} border-rose-400/40 bg-rose-400/10 text-rose-300`;
  }
  return `${base} border-slate-500/50 bg-slate-500/10 text-slate-400`;
}

export function WebhookAlertsPanel({ accessToken, watchlists }: Props) {
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [subscriptions, setSubscriptions] = useState<SubscriptionRow[]>([]);
  const [deliveries, setDeliveries] = useState<DeliveryRow[]>([]);
  const [statusText, setStatusText] = useState("");

  const [watchlistId, setWatchlistId] = useState("");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [endpointSecret, setEndpointSecret] = useState("");
  const [include13dg, setInclude13dg] = useState(true);
  const [includeInsider, setIncludeInsider] = useState(true);
  const [lookbackHours, setLookbackHours] = useState(48);

  const eligibleWatchlists = useMemo(() => {
    return watchlists.filter((list) => (list.item_count ?? 0) > 0);
  }, [watchlists]);

  useEffect(() => {
    if (!watchlistId && eligibleWatchlists.length > 0) {
      setWatchlistId(eligibleWatchlists[0].watchlist_id);
    }
  }, [eligibleWatchlists, watchlistId]);

  async function refreshData() {
    setLoading(true);
    try {
      const [subsRes, deliveriesRes] = await Promise.all([
        getWebhookSubscriptions(accessToken),
        getWebhookDeliveries(accessToken, { limitN: 30 }),
      ]);
      setSubscriptions(subsRes.rows ?? []);
      setDeliveries(deliveriesRes.rows ?? []);
    } catch (error) {
      setStatusText(`Failed to load webhook data: ${String(error)}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [accessToken]);

  async function createSubscription() {
    const normalizedUrl = endpointUrl.trim();
    if (!watchlistId) {
      setStatusText("Select a watchlist with items first.");
      return;
    }
    if (!normalizedUrl) {
      setStatusText("Endpoint URL is required.");
      return;
    }
    setBusy(true);
    setStatusText("");
    try {
      await createWebhookSubscription(accessToken, {
        watchlist_id: watchlistId,
        endpoint_url: normalizedUrl,
        endpoint_secret: endpointSecret.trim() || undefined,
        include_13dg: include13dg ? 1 : 0,
        include_insider: includeInsider ? 1 : 0,
        is_active: 1,
      });
      setEndpointUrl("");
      setEndpointSecret("");
      await refreshData();
      setStatusText("Webhook subscription created.");
    } catch (error) {
      setStatusText(`Create failed: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function deleteSubscription(webhookSubscriptionId: string) {
    if (!confirm("Delete this webhook subscription?")) return;
    setBusy(true);
    setStatusText("");
    try {
      await deleteWebhookSubscription(accessToken, webhookSubscriptionId);
      await refreshData();
      setStatusText("Webhook subscription deleted.");
    } catch (error) {
      setStatusText(`Delete failed: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function sendTest(webhookSubscriptionId: string) {
    setBusy(true);
    setStatusText("");
    try {
      const result = await testWebhookSubscription(accessToken, webhookSubscriptionId);
      await refreshData();
      setStatusText(
        result.ok
          ? `Test sent (${result.status}).`
          : `Test failed (${result.status})${result.error_text ? `: ${result.error_text}` : ""}`
      );
    } catch (error) {
      setStatusText(`Test failed: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  async function dispatchNow() {
    setBusy(true);
    setStatusText("");
    try {
      const result = await dispatchWebhookAlerts(accessToken, {
        lookbackHours: lookbackHours,
        maxEvents: 500,
      });
      await refreshData();
      setStatusText(
        `Dispatch complete: ${result.dispatched} sent, ${result.failed} failed, ${result.skipped_duplicates} skipped.`
      );
    } catch (error) {
      setStatusText(`Dispatch failed: ${String(error)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-lg font-semibold text-slate-100">Webhook Alerts</h2>
        <div className="flex items-center gap-2">
          <input
            type="number"
            min={1}
            max={24 * 30}
            value={lookbackHours}
            onChange={(event) => setLookbackHours(Number(event.target.value || 48))}
            className="h-8 w-20 border border-line/80 bg-card/70 px-2 text-xs text-slate-200 outline-none focus:border-accentBlue/60"
          />
          <button
            type="button"
            disabled={busy || loading}
            onClick={dispatchNow}
            className="inline-flex h-8 items-center gap-1.5 border border-accentBlue/55 bg-accentBlue/15 px-2.5 text-xs text-slate-100 transition hover:bg-accentBlue/25 disabled:opacity-50"
          >
            <Send className="h-3.5 w-3.5" />
            Dispatch
          </button>
          <button
            type="button"
            disabled={busy || loading}
            onClick={() => void refreshData()}
            className="inline-flex h-8 w-8 items-center justify-center border border-line/80 text-slate-300 transition hover:text-white disabled:opacity-50"
            aria-label="Refresh webhook data"
            title="Refresh"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>

      <article className="rounded-none border border-line/80 bg-card/80 p-4 shadow-panel">
        <div className="grid gap-2 md:grid-cols-[180px_minmax(0,1fr)_minmax(0,1fr)_auto]">
          <select
            value={watchlistId}
            onChange={(event) => setWatchlistId(event.target.value)}
            className="h-9 border border-line/80 bg-card/70 px-2 text-sm text-slate-200 outline-none focus:border-accentBlue/60"
          >
            {eligibleWatchlists.length === 0 ? <option value="">No watchlists with items</option> : null}
            {eligibleWatchlists.map((list) => (
              <option key={list.watchlist_id} value={list.watchlist_id}>
                {list.name}
              </option>
            ))}
          </select>
          <input
            type="url"
            value={endpointUrl}
            onChange={(event) => setEndpointUrl(event.target.value)}
            placeholder="https://your-webhook-endpoint"
            className="h-9 border border-line/80 bg-card/70 px-3 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-accentBlue/60"
          />
          <input
            type="text"
            value={endpointSecret}
            onChange={(event) => setEndpointSecret(event.target.value)}
            placeholder="Optional HMAC secret"
            className="h-9 border border-line/80 bg-card/70 px-3 text-sm text-slate-100 outline-none placeholder:text-slate-500 focus:border-accentBlue/60"
          />
          <button
            type="button"
            disabled={busy || loading || eligibleWatchlists.length === 0}
            onClick={createSubscription}
            className="inline-flex h-9 items-center border border-accentBlue/55 bg-accentBlue/15 px-3 text-sm text-slate-100 transition hover:bg-accentBlue/25 disabled:opacity-50"
          >
            Create
          </button>
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-4 text-xs text-slate-400">
          <label className="inline-flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={include13dg}
              onChange={(event) => setInclude13dg(event.target.checked)}
              className="h-3.5 w-3.5 accent-accentBlue"
            />
            13D/G
          </label>
          <label className="inline-flex items-center gap-1.5">
            <input
              type="checkbox"
              checked={includeInsider}
              onChange={(event) => setIncludeInsider(event.target.checked)}
              className="h-3.5 w-3.5 accent-accentBlue"
            />
            Insider
          </label>
        </div>

        {loading ? (
          <div className="grid place-items-center py-4">
            <LottieLoader size={72} />
          </div>
        ) : (
          <div className="mt-3 grid gap-4 lg:grid-cols-2">
            <div className="overflow-x-auto border border-line/70">
              <table className="min-w-full divide-y divide-line/60 text-sm">
                <thead>
                  <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">Watchlist</th>
                    <th className="px-3 py-2">Endpoint</th>
                    <th className="px-3 py-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/50 text-slate-300">
                  {subscriptions.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-3 py-4 text-center text-xs text-slate-500">
                        No webhook subscriptions yet.
                      </td>
                    </tr>
                  ) : (
                    subscriptions.map((row) => (
                      <tr key={row.webhook_subscription_id}>
                        <td className="px-3 py-2">
                          <div className="text-slate-100">{row.watchlist_name || row.watchlist_id}</div>
                          <div className="mt-1 text-[11px] text-slate-500">
                            13D/G {row.include_13dg ? "on" : "off"} · Insider {row.include_insider ? "on" : "off"}
                          </div>
                        </td>
                        <td className="px-3 py-2">
                          <div className="max-w-[290px] truncate text-xs text-slate-400">{row.endpoint_url}</div>
                        </td>
                        <td className="px-3 py-2">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void sendTest(row.webhook_subscription_id)}
                              className="inline-flex h-7 w-7 items-center justify-center border border-emerald-400/50 bg-emerald-400/10 text-emerald-300 transition hover:bg-emerald-400/20 disabled:opacity-50"
                              title="Send test event"
                              aria-label="Send test event"
                            >
                              <TestTube2 className="h-3.5 w-3.5" />
                            </button>
                            <button
                              type="button"
                              disabled={busy}
                              onClick={() => void deleteSubscription(row.webhook_subscription_id)}
                              className="inline-flex h-7 w-7 items-center justify-center border border-rose-400/50 bg-rose-400/10 text-rose-300 transition hover:bg-rose-400/20 disabled:opacity-50"
                              title="Delete subscription"
                              aria-label="Delete subscription"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>

            <div className="overflow-x-auto border border-line/70">
              <table className="min-w-full divide-y divide-line/60 text-sm">
                <thead>
                  <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
                    <th className="px-3 py-2">Status</th>
                    <th className="px-3 py-2">Event</th>
                    <th className="px-3 py-2">Time</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-line/50 text-slate-300">
                  {deliveries.length === 0 ? (
                    <tr>
                      <td colSpan={3} className="px-3 py-4 text-center text-xs text-slate-500">
                        No deliveries yet.
                      </td>
                    </tr>
                  ) : (
                    deliveries.map((row) => (
                      <tr key={row.webhook_delivery_id}>
                        <td className="px-3 py-2">
                          <span className={toStatusClass(row.status)}>{row.status}</span>
                        </td>
                        <td className="px-3 py-2">
                          <div className="text-xs text-slate-300">{row.event_source}</div>
                          <div className="max-w-[240px] truncate text-[11px] text-slate-500">{row.event_key}</div>
                        </td>
                        <td className="px-3 py-2 text-xs text-slate-500">{row.created_at || "-"}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </article>

      {statusText ? <p className="text-sm text-slate-400">{statusText}</p> : null}
    </section>
  );
}

