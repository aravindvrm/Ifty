import { Sparkline } from "@/components/charts";
import { getAccumulation, getAccumulationHistory, getNew5Pct } from "@/lib/api";
import { fmtNumber } from "@/lib/format";

type Props = {
  searchParams: Promise<{
    curr_q?: string;
    prev_q?: string;
    start_date?: string;
    end_date?: string;
  }>;
};

function shiftDate(days: number): string {
  const dt = new Date();
  dt.setUTCDate(dt.getUTCDate() + days);
  return dt.toISOString().slice(0, 10);
}

export default async function ScreenersPage({ searchParams }: Props) {
  const query = await searchParams;

  const history = await getAccumulationHistory(40);
  const quarters = history.quarters;
  const currQ = query.curr_q ?? quarters[quarters.length - 1] ?? "";
  const prevQ = query.prev_q ?? quarters[quarters.length - 2] ?? "";

  const [accumulation, new5Pct] = await Promise.all([
    currQ && prevQ ? getAccumulation(currQ, prevQ, 100) : Promise.resolve({ curr_q: "", prev_q: "", rows: [] }),
    getNew5Pct(query.start_date ?? shiftDate(-90), query.end_date ?? shiftDate(0), 100)
  ]);

  const sparkBySecurity = new Map(history.rows.map((r) => [r.security_id, r.series]));

  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">Screeners</h1>
        <p className="page-subtitle">Accumulation leaderboard with trend lines and new 5% beneficial ownership alerts.</p>
      </div>

      <div className="card">
        <h3>Accumulation Leaderboard</h3>
        <form className="input-row" method="get">
          <input name="prev_q" defaultValue={prevQ} placeholder="Prev quarter (YYYY-MM-DD)" />
          <input name="curr_q" defaultValue={currQ} placeholder="Curr quarter (YYYY-MM-DD)" />
          <button type="submit">Refresh</button>
        </form>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Security</th>
                <th>Net Holders</th>
                <th>Net Shares</th>
                <th>Sparkline</th>
              </tr>
            </thead>
            <tbody>
              {accumulation.rows.map((row) => (
                <tr key={row.security_id}>
                  <td>{row.security_name ?? `Security ${row.security_id}`}</td>
                  <td className={row.net_holder_count >= 0 ? "badge-pos" : "badge-neg"}>{fmtNumber(row.net_holder_count)}</td>
                  <td className={row.net_shares >= 0 ? "badge-pos" : "badge-neg"}>{fmtNumber(row.net_shares)}</td>
                  <td className="spark-cell">
                    <Sparkline data={sparkBySecurity.get(row.security_id) ?? []} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card">
        <h3>New 13D/G 5% Holders</h3>
        <form className="input-row" method="get">
          <input name="start_date" defaultValue={query.start_date ?? new5Pct.start_date} placeholder="Start (YYYY-MM-DD)" />
          <input name="end_date" defaultValue={query.end_date ?? new5Pct.end_date} placeholder="End (YYYY-MM-DD)" />
          <button type="submit">Refresh</button>
        </form>
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Manager</th>
                <th>Security</th>
                <th>% Owned</th>
                <th>Form</th>
              </tr>
            </thead>
            <tbody>
              {new5Pct.rows.map((row, idx) => (
                <tr key={`${row.accession_no}-${idx}`}>
                  <td>{row.report_date}</td>
                  <td>{row.manager_name ?? "Unknown"}</td>
                  <td>{row.security_name ?? `Security ${row.security_id ?? "?"}`}</td>
                  <td>{row.percent_beneficial_owned === null ? "-" : `${row.percent_beneficial_owned.toFixed(2)}%`}</td>
                  <td>{row.form_type}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
