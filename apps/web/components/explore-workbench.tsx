"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Search } from "lucide-react";

import { ExploreEntityView, type ExploreSelection } from "@/components/explore-entity-view";
import { EntitySearchInput, type EntitySuggestionItem } from "@/components/entity-search-input";

type Props = {
  defaultQuery?: string;
  initialSelection?: ExploreSelection | null;
  pulseContent: React.ReactNode;
};

const transition = {
  duration: 0.26,
  ease: [0.2, 0.65, 0.2, 1] as const,
};

function updateExploreUrl(selection: ExploreSelection | null) {
  if (typeof window === "undefined") return;
  const next = selection
    ? `/explore?type=${selection.type}&key=${encodeURIComponent(selection.key)}`
    : "/explore";
  window.history.replaceState(window.history.state, "", next);
}

export function ExploreWorkbench({ defaultQuery = "", initialSelection = null, pulseContent }: Props) {
  const [query, setQuery] = useState(defaultQuery);
  const [selected, setSelected] = useState<ExploreSelection | null>(initialSelection);
  const initialSelectionToken = initialSelection ? `${initialSelection.type}:${initialSelection.key}` : "";

  useEffect(() => {
    setQuery(defaultQuery);
    setSelected(initialSelection);
  }, [defaultQuery, initialSelectionToken]);

  const mode = useMemo(() => {
    return selected ? "entity" : "pulse";
  }, [selected]);

  const handleQueryChange = useCallback(
    (next: string) => {
      const normalized = next.trim().toLowerCase();
      setQuery(next);
      if (normalized.length === 0) {
        setSelected(null);
        updateExploreUrl(null);
      }
    },
    []
  );

  const handleSelectSuggestion = useCallback((item: EntitySuggestionItem) => {
    let nextSelection: ExploreSelection | null = null;
    let nextQuery = item.primary;

    if (item.kind === "security") {
      const key = (item.ticker ?? item.primary ?? "").trim().toUpperCase();
      if (key) {
        nextSelection = { type: "security", key };
        nextQuery = key;
      }
    } else {
      const key = String(item.managerId ?? "").trim();
      if (key) {
        nextSelection = { type: "institution", key };
        nextQuery = item.primary;
      }
    }

    if (!nextSelection) return;

    setQuery(nextQuery);
    setSelected(nextSelection);
    updateExploreUrl(nextSelection);
  }, []);

  return (
    <div className="space-y-6">
      <section className="rounded-none p-6">
        <motion.div layout transition={transition} className="relative mx-auto w-full max-w-4xl">
          <EntitySearchInput
            placeholder="Search by ticker or institution..."
            defaultValue={defaultQuery}
            showIcon={false}
            className="relative"
            inputClassName="search-pill w-full rounded-full border border-line/80 bg-card/80 py-4 pl-12 pr-5 text-lg text-slate-100 outline-none transition-all placeholder:text-slate-500 hover:border-line focus:border-accentBlue/50"
            dropdownClassName="absolute left-0 right-0 top-[calc(100%+10px)] z-40 overflow-hidden rounded-none border border-line/80 bg-[#02050c]"
            securityLimit={12}
            institutionLimit={12}
            navigateOnSelect={false}
            onQueryChange={handleQueryChange}
            onSelectSuggestion={handleSelectSuggestion}
          />
          <div className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500">
            <Search className="h-5 w-5" />
          </div>
        </motion.div>
      </section>

      <div className="relative">
        <AnimatePresence mode="wait" initial={false}>
          {mode === "pulse" ? (
            <motion.div
              key="pulse"
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={transition}
            >
              {pulseContent}
            </motion.div>
          ) : null}

          {mode === "entity" ? (
            <motion.div
              key={`entity:${selected?.type ?? "none"}:${selected?.key ?? "none"}`}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -12 }}
              transition={transition}
            >
              <ExploreEntityView selection={selected} />
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </div>
  );
}
