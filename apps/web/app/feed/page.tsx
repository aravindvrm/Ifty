import Link from "next/link";

import { FeedLiveTable } from "@/components/feed-live-table";
import { get13DGFeed } from "@/lib/api";

export default async function FeedPage() {
  let loadError: string | null = null;
  const primary = await get13DGFeed({
    days: 90,
    limitN: 2000,
    includeOther: false,
    mappedOnly: true,
    includeLowQuality: false
  }).catch((error) => {
    loadError = String(error);
    return null;
  });

  return (
    <div className="stack">
      <div className="card">
        <h1 className="page-title">13D/G Event Feed</h1>
        <p className="page-subtitle">
          Daily-updated beneficial ownership event stream across the active institution universe.
        </p>
      </div>

      <div className="card">
        <div className="feed-header">
          <h3>Live Feed Explorer</h3>
          <Link href="/">Back to home</Link>
        </div>
        <FeedLiveTable rows={primary?.rows ?? []} loadError={loadError} />
      </div>
    </div>
  );
}
