"use client";

import Lottie from "lottie-react";

import loadingAnimation from "@/lib/lottie/loading-7xyTDwuIwc.json";

type LottieLoaderProps = {
  size?: number;
  className?: string;
};

export function LottieLoader({ size = 220, className = "" }: LottieLoaderProps) {
  return (
    <div className={`lottie-loader ${className}`.trim()} style={{ width: size, height: size }} aria-hidden="true">
      <Lottie
        animationData={loadingAnimation}
        loop
        autoplay
        rendererSettings={{ preserveAspectRatio: "xMidYMid meet" }}
      />
    </div>
  );
}
