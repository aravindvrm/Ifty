"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";

import { getInstitutionUniverse, searchSecurities, type InstitutionUniverseResponse } from "@/lib/api";

type SecurityHit = {
  security_id: number;
  security_name: string | null;
  issuer_name: string | null;
  ticker: string | null;
  mic: string | null;
};

type InstitutionHit = InstitutionUniverseResponse["rows"][number];

type SuggestionItem = {
  id: string;
  href: string;
  primary: string;
  secondary: string;
  kind: "security" | "institution";
};

let institutionUniverseCache: InstitutionHit[] | null = null;
let institutionUniversePromise: Promise<InstitutionHit[]> | null = null;

function loadInstitutionUniverse(limitN: number): Promise<InstitutionHit[]> {
  if (institutionUniverseCache) {
    return Promise.resolve(institutionUniverseCache);
  }
  if (!institutionUniversePromise) {
    institutionUniversePromise = getInstitutionUniverse(limitN)
      .then((response) => {
        institutionUniverseCache = response.rows;
        return response.rows;
      })
      .finally(() => {
        institutionUniversePromise = null;
      });
  }
  return institutionUniversePromise;
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
  institutionUniverseLimit = 500,
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
  institutionUniverseLimit?: number;
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

  const securityItems = useMemo<SuggestionItem[]>(() => {
    if (!includeSecurities) return [];
    return securityHits
      .filter((row): row is SecurityHit & { ticker: string } => !!row.ticker)
      .map((row) => ({
        id: `security-${row.security_id}`,
        href: `/security/${encodeURIComponent(row.ticker)}`,
        primary: row.ticker,
        secondary: row.security_name ?? row.issuer_name ?? "-",
        kind: "security",
      }));
  }, [includeSecurities, securityHits]);

  const institutionItems = useMemo<SuggestionItem[]>(() => {
    if (!includeInstitutions) return [];
    return institutionHits.map((row) => ({
      id: `institution-${row.manager_id}`,
      href: `/institution/${encodeURIComponent(String(row.manager_id))}`,
      primary: row.manager_name,
      secondary: row.cik ?? "CIK -",
      kind: "institution",
    }));
  }, [includeInstitutions, institutionHits]);

  const allItems = useMemo(() => [...securityItems, ...institutionItems], [securityItems, institutionItems]);

  const showDropdown = focused && trimmedQuery.length > 0 && (loading || !!searchError || allItems.length > 0);

  const navigateTo = useCallback(
    (href: string) => {
      router.push(href);
      setFocused(false);
    },
    [router]
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
        const [securityResponse, universeRows] = await Promise.all([
          includeSecurities ? searchSecurities(trimmedQuery, securityLimit) : Promise.resolve({ query: trimmedQuery, rows: [] }),
          includeInstitutions ? loadInstitutionUniverse(institutionUniverseLimit) : Promise.resolve([]),
        ]);

        if (searchSeq.current !== seq) return;

        const q = trimmedQuery.toLowerCase();
        const matchedInstitutions = includeInstitutions
          ? universeRows
              .filter((row) => {
                const managerName = (row.manager_name ?? "").toLowerCase();
                const cik = (row.cik ?? "").toLowerCase();
                return managerName.includes(q) || cik.includes(q);
              })
              .slice(0, institutionLimit)
          : [];

        setSecurityHits(securityResponse.rows as SecurityHit[]);
        setInstitutionHits(matchedInstitutions);
        setSearchError("");
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
    institutionUniverseLimit,
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
          onChange={(event) => setQuery(event.target.value)}
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
                navigateTo(active.href);
                return;
              }
              const first = allItems[0];
              if (first) {
                navigateTo(first.href);
                return;
              }
              if (fallbackPath && trimmedQuery) {
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
                    onClick={() => navigateTo(item.href)}
                    className={[
                      "flex w-full items-center justify-between gap-2 px-3 py-1.5 text-left text-sm transition",
                      active ? "bg-accentBlue/20 text-white" : "text-slate-200 hover:bg-card/70",
                    ].join(" ")}
                  >
                    <span className="font-medium text-accentBlue">{item.primary}</span>
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
                    onClick={() => navigateTo(item.href)}
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
