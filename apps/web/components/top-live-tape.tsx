"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { Dot, TrendingDown, TrendingUp } from "lucide-react";

import { get13DGFeed, type Feed13DGResponse } from "@/lib/api";

type FeedRow = Feed13DGResponse["rows"][number];

function toEventDirection(eventType: string): "up" | "down" | "flat" {
  const value = (eventType || "").toUpperCase();
  if (value === "NEW_5PCT" || value === "AMENDMENT_UP") {
    return "up";
  }
  if (value === "EXIT_5PCT" || value === "AMENDMENT_DOWN") {
    return "down";
  }
  return "flat";
}

export function TopLiveTape({ className }: { className?: string }) {
  const [rows, setRows] = useState<FeedRow[]>([]);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState(false);
  const seq = useRef(0);

  useEffect(() => {
    let disposed = false;

    async function load() {
      const token = seq.current + 1;
      seq.current = token;
      try {
        const response = await get13DGFeed({
          days: 45,
          limitN: 16,
          includeOther: false,
          mappedOnly: true,
          includeLowQuality: false,
        });
        if (disposed || seq.current !== token) return;
        setRows(response.rows);
        setError(false);
      } catch {
        if (disposed || seq.current !== token) return;
        setRows([]);
        setError(true);
      } finally {
        if (!disposed && seq.current === token) {
          setReady(true);
        }
      }
    }

    load();
    const interval = window.setInterval(load, 5 * 60 * 1000);
    return () => {
      disposed = true;
      window.clearInterval(interval);
    };
  }, []);

  const items = useMemo(() => {
    if (!rows.length) return [];
    return [...rows, ...rows];
  }, [rows]);

  if (!ready) {
    return <div className={className ? `${className} text-xs text-slate-500` : "text-xs text-slate-500"}>Loading tape...</div>;
  }

  if (error || rows.length === 0) {
    return <div className={className ? `${className} text-xs text-slate-500` : "text-xs text-slate-500"}>13D/G tape unavailable</div>;
  }

  return (
    <div className={className}>
      <div className="feed-ticker-top-viewport">
        <div className="feed-ticker-top-track">
          {items.map((row, idx) => (
            <div key={`top-tape-${row.bo_event_id}-${idx}`} className="feed-ticker-top-item">
              <span className="feed-ticker-top-date">{row.report_date}</span>
              <span className="inline-flex items-center">
                {toEventDirection(row.event_type) === "up" ? (
                  <TrendingUp className="h-4 w-4 text-emerald-300" />
                ) : toEventDirection(row.event_type) === "down" ? (
                  <TrendingDown className="h-4 w-4 text-rose-300" />
                ) : (
                  <Dot className="h-4 w-4 text-slate-500" />
                )}
              </span>
              <span className="feed-ticker-top-security">
                {row.ticker ? (
                  <Link href={`/security/${encodeURIComponent(row.ticker)}`} className="text-accentBlue hover:text-white">
                    {row.ticker}
                  </Link>
                ) : (
                  row.security_display || row.security_name || row.issuer_name_raw || "-"
                )}
              </span>
              <span className="feed-ticker-top-manager">
                {row.manager_id ? (
                  <Link href={`/institution/${row.manager_id}`} className="text-slate-300 hover:text-white">
                    {row.manager_name ?? `Institution ${row.manager_id}`}
                  </Link>
                ) : (
                  row.manager_name ?? "-"
                )}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
