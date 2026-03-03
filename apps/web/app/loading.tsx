export default function Loading() {
  return (
    <div className="route-loading" role="status" aria-live="polite" aria-label="Loading page">
      <div className="route-loading-bar" />
      <div className="route-loading-body">
        <div className="route-loading-spinner" />
        <span>Loading...</span>
      </div>
    </div>
  );
}
