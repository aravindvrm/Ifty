import Link from "next/link";

import { getManagerUniverse } from "@/lib/api";
import { fmtNumber } from "@/lib/format";

type Props = {
  searchParams: Promise<{ q?: string }>;
};

export default async function ManagerDirectoryPage({ searchParams }: Props) {
  const q = ((await searchParams).q ?? "").trim().toLowerCase();

  let universe;
  try {
    universe = await getManagerUniverse(500);
  } catch (error) {
    return (
      <div className="card">
        <h1 className="page-title">Managers</h1>
        <p className="page-subtitle">Failed to load manager universe.</p>
        <pre>{String(error)}</pre>
      </div>
    );
  }

  const rows = q
    ? universe.rows.filter((row) => {
        const name = (row.manager_name ?? "").toLowerCase();
        const cik = (row.cik ?? "").toLowerCase();
        return name.includes(q) || cik.includes(q);
      })
    : universe.rows;

  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">Manager Directory</h1>
        <p className="page-subtitle">Open any tracked manager by rank, name, or CIK.</p>
        <form className="input-row" method="get">
          <input name="q" placeholder="Search manager or CIK" defaultValue={q} />
          <button type="submit">Search</button>
        </form>
      </div>

      <div className="card">
        <h3>Tracked Universe</h3>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Rank</th>
                <th>Manager</th>
                <th>CIK</th>
                <th>Total Value (USD)</th>
                <th>As Of</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={5}>No managers match your query.</td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.manager_id}>
                    <td>{row.rank}</td>
                    <td>
                      <Link prefetch={false} href={`/manager/${encodeURIComponent(String(row.manager_id))}`}>
                        {row.manager_name}
                      </Link>
                    </td>
                    <td>{row.cik ?? "-"}</td>
                    <td>{fmtNumber(row.total_value_usd ?? 0, 0)}</td>
                    <td>{row.as_of_report_date}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
