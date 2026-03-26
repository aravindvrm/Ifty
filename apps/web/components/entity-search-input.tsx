"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import { searchInstitutions, searchSecurities, type InstitutionUniverseResponse } from "@/lib/api";
import { TickerIcon } from "@/components/ticker-icon";

type SecurityHit = {
  security_id: number;
  security_name: string | null;
  issuer_name: string | null;
  ticker: string | null;
  mic: string | null;
};

type InstitutionHit = InstitutionUniverseResponse["rows"][number];

export type EntitySuggestionItem = {
  id: string;
  href: string;
  primary: string;
  secondary: string;
  kind: "security" | "institution";
  ticker?: string;
  managerId?: number;
};

const DERIVATIVE_SECURITY_PATTERN =
  /\b(?:PUT|CALL|OPTION|WARRANT|RIGHT|PREFERRED|PFD|NOTE|BOND|DEBENTURE)\b|OPTION ROOT=/i;
const OCC_STYLE_OPTION_TICKER_PATTERN = /^[A-Z]{1,6}\d{6}[CP]\d{8}$/;

function isDisplayableSecurityHit(row: SecurityHit): boolean {
  const ticker = String(row.ticker ?? "").trim().toUpperCase();
  const securityName = String(row.security_name ?? "").trim();
  const issuerName = String(row.issuer_name ?? "").trim();
  const combined = `${securityName} ${issuerName}`.trim();
  if (!ticker) return false;
  if (OCC_STYLE_OPTION_TICKER_PATTERN.test(ticker)) return false;
  if (DERIVATIVE_SECURITY_PATTERN.test(combined)) return false;
  return true;
}

function applyHrefTemplate(template: string, values: Record<string, string>): string {
  let href = template;
  for (const [key, value] of Object.entries(values)) {
    href = href.replaceAll(`{${key}}`, encodeURIComponent(value));
  }
  return href;
}

export function EntitySearchInput({
  placeholder,
  defaultValue = "",
  fallbackPath,
  className,
  inputClassName,
  dropdownClassName,
  showIcon = false,
  includeSecurities = true,
  includeInstitutions = true,
  securityLimit = 10,
  institutionLimit = 10,
  securityHrefTemplate,
  institutionHrefTemplate,
  onQueryChange,
  navigateOnSelect = true,
  onSelectSuggestion,
}: {
  placeholder: string;
  defaultValue?: string;
  fallbackPath?: string;
  className?: string;
  inputClassName?: string;
  dropdownClassName?: string;
  showIcon?: boolean;
  includeSecurities?: boolean;
  includeInstitutions?: boolean;
  securityLimit?: number;
  institutionLimit?: number;
  securityHrefTemplate?: string;
  institutionHrefTemplate?: string;
  onQueryChange?: (query: string) => void;
  navigateOnSelect?: boolean;
  onSelectSuggestion?: (item: EntitySuggestionItem) => void;
}) {
  const router = useRouter();
  const [query, setQuery] = useState(defaultValue);
  const [focused, setFocused] = useState(false);
  const [loading, setLoading] = useState(false);
  const [searchError, setSearchError] = useState("");
  const [securityHits, setSecurityHits] = useState<SecurityHit[]>([]);
  const [institutionHits, setInstitutionHits] = useState<InstitutionHit[]>([]);
  const [activeIndex, setActiveIndex] = useState(-1);

  const searchSeq = useRef(0);
  const wrapRef = useRef<HTMLDivElement | null>(null);

  const trimmedQuery = query.trim();

  const securityItems = useMemo<EntitySuggestionItem[]>(() => {
    if (!includeSecurities) return [];
    return securityHits
      .filter((row): row is SecurityHit & { ticker: string } => !!row.ticker)
      .filter((row) => isDisplayableSecurityHit(row))
      .map((row) => ({
        id: `security-${row.security_id}`,
        href: securityHrefTemplate
          ? applyHrefTemplate(securityHrefTemplate, {
              ticker: row.ticker,
              security_id: String(row.security_id),
            })
          : `/security/${encodeURIComponent(row.ticker)}`,
        primary: row.ticker,
        secondary: row.security_name ?? row.issuer_name ?? "-",
        kind: "security",
        ticker: row.ticker,
      }));
  }, [includeSecurities, securityHrefTemplate, securityHits]);

  const institutionItems = useMemo<EntitySuggestionItem[]>(() => {
    if (!includeInstitutions) return [];
    return institutionHits.map((row) => ({
      id: `institution-${row.manager_id}`,
      href: institutionHrefTemplate
        ? applyHrefTemplate(institutionHrefTemplate, {
            manager_id: String(row.manager_id),
            cik: row.cik ?? "",
            manager_name: row.manager_name ?? "",
          })
        : `/institution/${encodeURIComponent(String(row.manager_id))}`,
      primary: row.manager_name,
      secondary: row.cik ?? "CIK -",
      kind: "institution",
      managerId: Number(row.manager_id),
    }));
  }, [includeInstitutions, institutionHits, institutionHrefTemplate]);

  const allItems = useMemo(() => [...securityItems, ...institutionItems], [securityItems, institutionItems]);

  const showDropdown = focused && trimmedQuery.length > 0 && (loading || !!searchError || allItems.length > 0);

  const commitSelection = useCallback(
    (item: EntitySuggestionItem) => {
      setQuery(item.primary);
      onQueryChange?.(item.primary);
      onSelectSuggestion?.(item);
      if (navigateOnSelect) {
        router.push(item.href);
      }
      setFocused(false);
    },
    [navigateOnSelect, onSelectSuggestion, router]
  );

  useEffect(() => {
    setQuery(defaultValue);
  }, [defaultValue]);

  useEffect(() => {
    function onDocPointerDown(event: MouseEvent) {
      const target = event.target as Node | null;
      if (!target) return;
      if (wrapRef.current && !wrapRef.current.contains(target)) {
        setFocused(false);
      }
    }
    document.addEventListener("mousedown", onDocPointerDown);
    return () => document.removeEventListener("mousedown", onDocPointerDown);
  }, []);

  useEffect(() => {
    if (!trimmedQuery) {
      setLoading(false);
      setSearchError("");
      setSecurityHits([]);
      setInstitutionHits([]);
      setActiveIndex(-1);
      return;
    }

    const seq = searchSeq.current + 1;
    searchSeq.current = seq;

    const timer = setTimeout(async () => {
      setLoading(true);
      try {
        const [securityResult, institutionResult] = await Promise.allSettled([
          includeSecurities
            ? searchSecurities(trimmedQuery, securityLimit)
            : Promise.resolve({ query: trimmedQuery, rows: [] }),
          includeInstitutions
            ? searchInstitutions(trimmedQuery, institutionLimit)
            : Promise.resolve({ query: trimmedQuery, rows: [] }),
        ]);

        if (searchSeq.current !== seq) return;

        const securityRows =
          securityResult.status === "fulfilled" ? (securityResult.value.rows as SecurityHit[]) : [];
        const institutionRows =
          institutionResult.status === "fulfilled"
            ? (institutionResult.value.rows as InstitutionHit[])
            : [];

        setSecurityHits(securityRows);
        setInstitutionHits(institutionRows);
        setSearchError(
          securityResult.status === "rejected" && institutionResult.status === "rejected"
            ? "Search unavailable"
            : ""
        );
      } catch (error) {
        if (searchSeq.current !== seq) return;
        setSecurityHits([]);
        setInstitutionHits([]);
        setSearchError(String(error));
      } finally {
        if (searchSeq.current === seq) {
          setLoading(false);
        }
      }
    }, 180);

    return () => clearTimeout(timer);
  }, [
    includeSecurities,
    includeInstitutions,
    trimmedQuery,
    securityLimit,
    institutionLimit,
  ]);

  useEffect(() => {
    if (!showDropdown || allItems.length === 0) {
      setActiveIndex(-1);
      return;
    }
    setActiveIndex((prev) => {
      if (prev >= 0 && prev < allItems.length) return prev;
      return 0;
    });
  }, [showDropdown, allItems.length]);

  return (
    <div className={className} ref={wrapRef}>
      <div className="relative">
        {showIcon ? (
          <div className="pointer-events-none absolute inset-y-0 left-3 flex items-center">
            <Search className="h-4 w-4 text-slate-500" />
          </div>
        ) : null}
        <input
          type="search"
          value={query}
          onFocus={() => setFocused(true)}
          onChange={(event) => {
            const next = event.target.value;
            setFocused(true);
            setQuery(next);
            onQueryChange?.(next);
          }}
          onKeyDown={(event) => {
            if (event.key === "ArrowDown") {
              event.preventDefault();
              if (!showDropdown) {
                setFocused(true);
              }
              if (allItems.length > 0) {
                setActiveIndex((prev) => (prev < 0 ? 0 : (prev + 1) % allItems.length));
              }
              return;
            }
            if (event.key === "ArrowUp") {
              event.preventDefault();
              if (!showDropdown) {
                setFocused(true);
              }
              if (allItems.length > 0) {
                setActiveIndex((prev) => {
                  if (prev < 0) return allItems.length - 1;
                  return (prev - 1 + allItems.length) % allItems.length;
                });
              }
              return;
            }
            if (event.key === "Escape") {
              event.preventDefault();
              setFocused(false);
              return;
            }
            if (event.key === "Enter") {
              event.preventDefault();
              const active = activeIndex >= 0 ? allItems[activeIndex] : null;
              if (active) {
                commitSelection(active);
                return;
              }
              const first = allItems[0];
              if (first) {
                commitSelection(first);
                return;
              }
              if (navigateOnSelect && fallbackPath && trimmedQuery) {
                router.push(`${fallbackPath}?q=${encodeURIComponent(trimmedQuery)}`);
                setFocused(false);
              }
            }
          }}
          placeholder={placeholder}
          className={inputClassName}
        />
      </div>

      {showDropdown ? (
        <div className={dropdownClassName}>
          {loading ? <div className="px-3 py-2 text-xs text-slate-400">Searching...</div> : null}
          {!loading && searchError ? <div className="px-3 py-2 text-xs text-rose-300">Search unavailable</div> : null}
          {!loading && !searchError && allItems.length === 0 ? (
            <div className="px-3 py-2 text-xs text-slate-500">No matches</div>
          ) : null}

          {!loading && securityItems.length > 0 ? (
            <div className={institutionItems.length > 0 ? "border-b border-line/70" : undefined}>
              <div className="px-3 py-1.5 text-[11px] uppercase tracking-wide text-slate-500">Securities</div>
              {securityItems.map((item) => {
                const index = allItems.findIndex((x) => x.id === item.id);
                const active = index === activeIndex;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => commitSelection(item)}
                    className={[
                      "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm transition",
                      active ? "bg-accentBlue/20 text-white" : "text-slate-200 hover:bg-card/70",
                    ].join(" ")}
                  >
                    <span className="inline-flex min-w-0 items-center gap-2 font-medium text-accentBlue">
                      <TickerIcon ticker={item.ticker ?? item.primary} label={item.secondary} />
                      <span>{item.primary}</span>
                    </span>
                    <span className="truncate text-xs text-slate-500">{item.secondary}</span>
                  </button>
                );
              })}
            </div>
          ) : null}

          {!loading && institutionItems.length > 0 ? (
            <div>
              <div className="px-3 py-1.5 text-[11px] uppercase tracking-wide text-slate-500">Institutions</div>
              {institutionItems.map((item) => {
                const index = allItems.findIndex((x) => x.id === item.id);
                const active = index === activeIndex;
                return (
                  <button
                    key={item.id}
                    type="button"
                    onMouseEnter={() => setActiveIndex(index)}
                    onClick={() => commitSelection(item)}
                    className={[
                      "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm transition",
                      active ? "bg-accentBlue/20 text-white" : "text-slate-200 hover:bg-card/70",
                    ].join(" ")}
                  >
                    <span className="truncate">{item.primary}</span>
                    <span className="text-xs text-slate-500">{item.secondary}</span>
                  </button>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
