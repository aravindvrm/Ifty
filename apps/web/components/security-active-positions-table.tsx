"use client";

import { useMemo, useState } from "react";

import { fmtNumber, fmtPct, fmtUsdThousands } from "@/lib/format";

type Row = {
  manager_id: number;
  manager_name: string;
  shares: number;
  value_usd_thousands: number;
  qoq_delta_shares: number;
  pct_manager_portfolio: number | null;
  is_new: boolean;
};

type SortKey = "manager_name" | "shares" | "value_usd_thousands" | "qoq_delta_shares" | "pct_manager_portfolio";

export function SecurityActivePositionsTable({ rows }: { rows: Row[] }) {
  const [sortKey, setSortKey] = useState<SortKey>("value_usd_thousands");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [page, setPage] = useState(1);
  const pageSize = 25;

  const sorted = useMemo(() => {
    const data = [...rows];
    data.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "manager_name") {
        cmp = a.manager_name.localeCompare(b.manager_name);
      } else {
        const av = Number(a[sortKey] ?? 0);
        const bv = Number(b[sortKey] ?? 0);
        cmp = av < bv ? -1 : av > bv ? 1 : 0;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return data;
  }, [rows, sortKey, sortDir]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const clampedPage = Math.min(page, totalPages);
  const start = (clampedPage - 1) * pageSize;
  const paged = sorted.slice(start, start + pageSize);

  function toggleSort(next: SortKey) {
    if (next === sortKey) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(next);
      setSortDir(next === "manager_name" ? "asc" : "desc");
    }
    setPage(1);
  }

  return (
    <section className="rounded-none border border-line/80 bg-card/80 p-5 shadow-panel">
      <h3 className="text-lg font-semibold text-slate-100">Active Positions</h3>
      <div className="mt-4 overflow-x-auto rounded-none border border-line/70">
        <table className="min-w-full divide-y divide-line/60 text-sm">
          <thead>
            <tr className="bg-black/20 text-left text-xs uppercase tracking-wide text-slate-500">
              <th className="px-3 py-2">
                <button type="button" onClick={() => toggleSort("manager_name")} className="hover:text-slate-300">
                  Institution
                </button>
              </th>
              <th className="px-3 py-2 text-right">
                <button type="button" onClick={() => toggleSort("shares")} className="hover:text-slate-300">
                  Shares
                </button>
              </th>
              <th className="px-3 py-2 text-right">
                <button type="button" onClick={() => toggleSort("value_usd_thousands")} className="hover:text-slate-300">
                  Value
                </button>
              </th>
              <th className="px-3 py-2 text-right">
                <button type="button" onClick={() => toggleSort("qoq_delta_shares")} className="hover:text-slate-300">
                  QoQ Δ Shares
                </button>
              </th>
              <th className="px-3 py-2 text-right">
                <button type="button" onClick={() => toggleSort("pct_manager_portfolio")} className="hover:text-slate-300">
                  % of Institution
                </button>
              </th>
              <th className="px-3 py-2">New</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line/50 text-slate-300">
            {paged.map((row) => (
              <tr key={row.manager_id}>
                <td className="px-3 py-2">{row.manager_name}</td>
                <td className="px-3 py-2 text-right">{fmtNumber(row.shares)}</td>
                <td className="px-3 py-2 text-right">{fmtUsdThousands(row.value_usd_thousands)}</td>
                <td className={`px-3 py-2 text-right ${row.qoq_delta_shares >= 0 ? "text-emerald-300" : "text-rose-300"}`}>
                  {fmtNumber(row.qoq_delta_shares)}
                </td>
                <td className="px-3 py-2 text-right">{row.pct_manager_portfolio === null ? "-" : fmtPct(row.pct_manager_portfolio)}</td>
                <td className="px-3 py-2">{row.is_new ? "NEW" : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 flex items-center gap-2">
        <button
          type="button"
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={clampedPage <= 1}
          className="rounded-none border border-line/80 bg-cardSoft/80 px-2.5 py-1 text-xs text-slate-300 transition hover:border-accentBlue/70 hover:text-white disabled:opacity-40"
        >
          Prev
        </button>
        <span className="text-xs text-slate-500">
          Page {clampedPage} / {totalPages}
        </span>
        <button
          type="button"
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={clampedPage >= totalPages}
          className="rounded-none border border-line/80 bg-cardSoft/80 px-2.5 py-1 text-xs text-slate-300 transition hover:border-accentBlue/70 hover:text-white disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </section>
  );
}
