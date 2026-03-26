"use client";

import { useEffect, useRef, useState } from "react";

import { LottieLoader } from "@/components/lottie-loader";

const MIN_VISIBLE_MS = 700;
const MAX_WAIT_MS = 5000;
const FADE_OUT_MS = 220;

type OverlayPhase = "visible" | "fading" | "hidden";

export function InitialLoadOverlay() {
  const [phase, setPhase] = useState<OverlayPhase>("visible");
  const startedAtRef = useRef<number>(Date.now());

  useEffect(() => {
    if (phase !== "fading") {
      return;
    }
    const fadeTimer = window.setTimeout(() => {
      setPhase("hidden");
    }, FADE_OUT_MS);
    return () => window.clearTimeout(fadeTimer);
  }, [phase]);

  useEffect(() => {
    let waitTimer: number | undefined;

    const startFadeOut = () => {
      setPhase((prev) => (prev === "visible" ? "fading" : prev));
    };

    const finishWhenReady = () => {
      const elapsed = Date.now() - startedAtRef.current;
      const waitMs = Math.max(0, MIN_VISIBLE_MS - elapsed);
      waitTimer = window.setTimeout(startFadeOut, waitMs);
    };

    if (document.readyState === "complete") {
      finishWhenReady();
    } else {
      window.addEventListener("load", finishWhenReady, { once: true });
    }

    const maxTimer = window.setTimeout(startFadeOut, MAX_WAIT_MS);
    return () => {
      window.removeEventListener("load", finishWhenReady);
      window.clearTimeout(maxTimer);
      if (waitTimer !== undefined) {
        window.clearTimeout(waitTimer);
      }
    };
  }, []);

  if (phase === "hidden") {
    return null;
  }

  return (
    <div
      className={`initial-load-overlay ${phase === "fading" ? "is-fading" : ""}`.trim()}
      role="status"
      aria-live="polite"
      aria-label="Loading page"
    >
      <div className="route-loading-center">
        <LottieLoader size={250} className="route-loading-lottie" />
      </div>
    </div>
  );
}
