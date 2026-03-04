"use client";

import { useEffect, useMemo, useState } from "react";

type Props = {
  ticker?: string | null;
  label?: string | null;
  size?: number;
  className?: string;
};

const VALID_TICKER_RE = /^[A-Z]{1,6}(?:\.[A-Z]{1,2})?$/;

function cleanTicker(value: string | null | undefined): string {
  return (value ?? "").trim().toUpperCase();
}

function buildSources(ticker: string): string[] {
  if (!ticker || !VALID_TICKER_RE.test(ticker)) return [];
  const plain = ticker.replace(/\./g, "-");
  return [
    `https://financialmodelingprep.com/image-stock/${encodeURIComponent(ticker)}.png`,
    `https://eodhd.com/img/logos/US/${encodeURIComponent(plain)}.png`,
  ];
}

function initialsFromTicker(ticker: string): string {
  const normalized = ticker.replace(/[^A-Z0-9]/g, "");
  if (!normalized) return "?";
  return normalized.slice(0, Math.min(2, normalized.length));
}

function hueFromTicker(ticker: string): number {
  let hash = 0;
  for (let i = 0; i < ticker.length; i += 1) {
    hash = (hash * 31 + ticker.charCodeAt(i)) % 360;
  }
  return (hash + 360) % 360;
}

export function TickerIcon({ ticker, label, size = 20, className }: Props) {
  const normalized = cleanTicker(ticker);
  const sources = useMemo(() => buildSources(normalized), [normalized]);
  const [sourceIndex, setSourceIndex] = useState(0);
  const [showFallback, setShowFallback] = useState(sources.length === 0);

  useEffect(() => {
    setSourceIndex(0);
    setShowFallback(sources.length === 0);
  }, [normalized, sources.length]);

  const initials = initialsFromTicker(normalized || "?");
  const hue = hueFromTicker(normalized || "fallback");
  const source = sources[sourceIndex];
  const title = label ?? normalized ?? "Symbol";

  return (
    <span
      title={title}
      aria-label={title}
      className={className}
      style={{
        display: "inline-flex",
        width: size,
        height: size,
        borderRadius: 0,
        alignItems: "center",
        justifyContent: "center",
        overflow: "hidden",
        background: `linear-gradient(145deg, hsla(${hue}, 78%, 34%, 0.92), hsla(${(hue + 42) % 360}, 82%, 16%, 0.92))`,
        color: "#e2e8f0",
        fontSize: Math.max(9, Math.round(size * 0.44)),
        fontWeight: 700,
        letterSpacing: "0.02em",
        lineHeight: 1,
        flexShrink: 0,
      }}
    >
      {!showFallback && source ? (
        <img
          src={source}
          alt={title}
          width={size}
          height={size}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          style={{ width: "100%", height: "100%", objectFit: "cover", background: "#0b1220" }}
          onError={() => {
            const nextIndex = sourceIndex + 1;
            if (nextIndex < sources.length) {
              setSourceIndex(nextIndex);
            } else {
              setShowFallback(true);
            }
          }}
        />
      ) : (
        <span>{initials}</span>
      )}
    </span>
  );
}
