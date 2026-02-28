import Link from "next/link";

import { searchSecurities } from "@/lib/api";

type Props = {
  searchParams: Promise<{ q?: string }>;
};

export default async function SecuritySearchPage({ searchParams }: Props) {
  const query = (await searchParams).q?.trim() ?? "";
  let results = { query: "", rows: [] as Array<{ security_id: number; security_name: string | null; issuer_name: string | null; ticker: string | null; mic: string | null }> };
  let loadError = "";
  try {
    results = query ? await searchSecurities(query, 50) : results;
  } catch (error) {
    loadError = String(error);
  }

  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">Security Search</h1>
        <p className="page-subtitle">Search by ticker or issuer name.</p>
        <form className="input-row" method="get">
          <input name="q" placeholder="AAPL or Apple" defaultValue={query} />
          <button type="submit">Search</button>
        </form>
      </div>

      <div className="card">
        <h3>Results</h3>
        {loadError ? <p className="page-subtitle">Search failed: {loadError}</p> : null}
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Security</th>
                <th>Issuer</th>
                <th>MIC</th>
              </tr>
            </thead>
            <tbody>
              {results.rows.length === 0 ? (
                <tr>
                  <td colSpan={4}>No results.</td>
                </tr>
              ) : (
                results.rows.map((row) => (
                  <tr key={row.security_id}>
                    <td>
                      {row.ticker ? (
                        <Link prefetch={false} href={`/security/${encodeURIComponent(row.ticker)}`}>
                          {row.ticker}
                        </Link>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td>{row.security_name ?? "-"}</td>
                    <td>{row.issuer_name ?? "-"}</td>
                    <td>{row.mic ?? "-"}</td>
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
