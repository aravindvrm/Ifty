import Link from "next/link";

import { getInstitutionUniverse } from "@/lib/api";
import { fmtNumber } from "@/lib/format";

type Props = {
  searchParams: Promise<{ q?: string }>;
};

export default async function InstitutionDirectoryPage({ searchParams }: Props) {
  const q = ((await searchParams).q ?? "").trim().toLowerCase();

  let universe;
  try {
    universe = await getInstitutionUniverse(500);
  } catch (error) {
    return (
      <div className="card">
        <h1 className="page-title">Institutions</h1>
        <p className="page-subtitle">Failed to load institution universe.</p>
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
        <h1 className="page-title">Institution Directory</h1>
        <p className="page-subtitle">Open any tracked institution by rank, name, or CIK.</p>
        <form className="input-row" method="get">
          <input name="q" placeholder="Search institution or CIK" defaultValue={q} />
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
                <th>Institution</th>
                <th>CIK</th>
                <th>Total Value (USD)</th>
                <th>As Of</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={5}>No institutions match your query.</td>
                </tr>
              ) : (
                rows.map((row) => (
                  <tr key={row.manager_id}>
                    <td>{row.rank}</td>
                    <td>
                      <Link prefetch={false} href={`/institution/${encodeURIComponent(String(row.manager_id))}`}>
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
