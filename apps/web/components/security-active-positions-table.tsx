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
    <div className="card">
      <h3>Active Positions</h3>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th><button type="button" onClick={() => toggleSort("manager_name")}>Manager</button></th>
              <th><button type="button" onClick={() => toggleSort("shares")}>Shares</button></th>
              <th><button type="button" onClick={() => toggleSort("value_usd_thousands")}>Value</button></th>
              <th><button type="button" onClick={() => toggleSort("qoq_delta_shares")}>QoQ Δ Shares</button></th>
              <th><button type="button" onClick={() => toggleSort("pct_manager_portfolio")}>% of Manager</button></th>
              <th>New</th>
            </tr>
          </thead>
          <tbody>
            {paged.map((row) => (
              <tr key={row.manager_id}>
                <td>{row.manager_name}</td>
                <td>{fmtNumber(row.shares)}</td>
                <td>{fmtUsdThousands(row.value_usd_thousands)}</td>
                <td className={row.qoq_delta_shares >= 0 ? "badge-pos" : "badge-neg"}>{fmtNumber(row.qoq_delta_shares)}</td>
                <td>{row.pct_manager_portfolio === null ? "-" : fmtPct(row.pct_manager_portfolio)}</td>
                <td>{row.is_new ? "NEW" : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="input-row">
        <button type="button" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={clampedPage <= 1}>Prev</button>
        <span>Page {clampedPage} / {totalPages}</span>
        <button type="button" onClick={() => setPage((p) => Math.min(totalPages, p + 1))} disabled={clampedPage >= totalPages}>Next</button>
      </div>
    </div>
  );
}
