export default function Loading() {
  return (
    <div className="route-loading" role="status" aria-live="polite" aria-label="Loading page">
      <div className="route-loading-top-progress" />
      <div className="route-loading-center">
        <div className="route-loading-histogram" aria-hidden="true">
          {Array.from({ length: 12 }, (_, index) => (
            <span key={`route-loader-bar-${index}`} className="route-loading-histogram-bar" />
          ))}
        </div>
        <div className="route-loading-caption">Loading market data...</div>
      </div>
    </div>
  );
}
