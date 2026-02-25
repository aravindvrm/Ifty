export function fmtNumber(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) {
    return "-";
  }
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  }).format(n);
}

export function fmtPct(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || Number.isNaN(n)) {
    return "-";
  }
  return `${(n * 100).toFixed(digits)}%`;
}

export function fmtUsdThousands(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) {
    return "-";
  }
  const usd = v * 1000;
  if (Math.abs(usd) >= 1_000_000_000) return `$${(usd / 1_000_000_000).toFixed(2)}B`;
  if (Math.abs(usd) >= 1_000_000) return `$${(usd / 1_000_000).toFixed(2)}M`;
  if (Math.abs(usd) >= 1_000) return `$${(usd / 1_000).toFixed(1)}K`;
  return `$${usd.toFixed(0)}`;
}
