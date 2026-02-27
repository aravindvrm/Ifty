import Link from "next/link";

export default function HomePage() {
  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">Flow Intelligence Console</h1>
        <p className="page-subtitle">
          Analyze institutional ownership flow from SEC 13F and 13D/G with split-aware deltas, holder concentration,
          and manager-level turnover.
        </p>
      </div>

      <div className="grid-2">
        <div className="card">
          <h3>Security Lens</h3>
          <p>Quarterly net accumulation chart, top holders with QoQ change, and 13D/G events feed.</p>
          <Link href="/security">Search securities</Link>
        </div>
        <div className="card">
          <h3>Manager Lens</h3>
          <p>Treemap of current exposures plus top buys and sells.</p>
          <Link href="/manager">Browse managers</Link>
        </div>
      </div>

      <div className="card">
        <h3>Screeners</h3>
        <p>Accumulation leaderboard with trend sparklines and new 5% beneficial ownership events.</p>
        <Link href="/screeners">Open screeners</Link>
      </div>
    </div>
  );
}
