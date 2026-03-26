import { LottieLoader } from "@/components/lottie-loader";

export default function Loading() {
  return (
    <div className="route-loading" role="status" aria-live="polite" aria-label="Loading page">
      <div className="route-loading-center">
        <LottieLoader size={240} className="route-loading-lottie" />
        <div className="route-loading-caption">Loading market data...</div>
      </div>
    </div>
  );
}
