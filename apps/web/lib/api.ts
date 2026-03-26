const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const FETCH_TIMEOUT_MS = 15000;

async function requestJson<T>(path: string): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), FETCH_TIMEOUT_MS);
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { cache: "no-store", signal: controller.signal });
  } catch (error) {
    const localhostBase = API_BASE.includes("localhost") ? API_BASE : "";
    if (!localhostBase) {
      clearTimeout(timeout);
      throw error;
    }
    const fallbackBase = localhostBase.replace("localhost", "127.0.0.1");
    response = await fetch(`${fallbackBase}${path}`, { cache: "no-store", signal: controller.signal });
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status} ${response.statusText}: ${body}`);
  }
  return (await response.json()) as T;
}

export type SecurityPageResponse = {
  security_id: number;
  ticker: string;
  security_name?: string;
  mic: string;
  latest_quarter: string | null;
  top_holders: Array<{ manager_id: number; manager_name: string; shares: number; value_usd_thousands: number }>;
  active_positions: Array<{
    manager_id: number;
    manager_name: string;
    shares: number;
    value_usd_thousands: number;
    qoq_delta_shares: number;
    pct_manager_portfolio: number | null;
    is_new: boolean;
  }>;
  net_change_last_4q: Array<{
    manager_id: number;
    manager_name: string;
    report_date: string;
    net_change_shares: number;
  }>;
  ownership_summary: {
    holders_count?: number;
    total_shares?: number;
    total_value_usd?: number;
    qoq_net_change_shares?: number;
    top10_concentration_pct?: number;
  };
  activity_breakdown: {
    total?: number;
    new?: number;
    increased?: number;
    decreased?: number;
    sold_out?: number;
    activity?: number;
  };
  concentration: {
    total_shares?: number;
    top10_shares?: number;
    top10_pct?: number;
  };
};

export type SecurityEventResponse = {
  security_id: number;
  ticker: string;
  rows: Array<{
    report_date: string;
    event_type: string;
    percent_beneficial_owned: number | null;
    shares_beneficial_owned: number | null;
    cusip_raw: string | null;
    mapping_status: string;
    manager_name: string | null;
    form_type: string;
    accession_no: string;
  }>;
};

export type ManagerPageResponse = {
  manager: { manager_id: number; cik: string; manager_name: string };
  latest_quarter: string | null;
  top_positions: Array<{
    security_id: number;
    issuer_name_raw: string | null;
    class_title_raw: string | null;
    ticker?: string | null;
    shares: number;
    value_usd_thousands: number;
    qoq_delta_value_usd_thousands?: number | null;
  }>;
  new_positions: Array<Record<string, unknown>>;
  exited_positions: Array<Record<string, unknown>>;
  top_buys: Array<{
    security_id: number;
    issuer_name_raw: string | null;
    class_title_raw: string | null;
    delta_val: number;
  }>;
  top_sells: Array<{
    security_id: number;
    issuer_name_raw: string | null;
    class_title_raw: string | null;
    delta_val: number;
  }>;
  metrics: {
    turnover_ratio?: number;
    top10_concentration_pct?: number;
    new_positions_count?: number;
    exited_positions_count?: number;
    total_value_current?: number;
    total_value_previous?: number;
    comparison_quarter?: string | null;
    comparison_method?: "exact_previous_quarter" | "latest_available_prior" | null;
  };
};

export type InstitutionPageResponse = ManagerPageResponse;

export type AccumulationResponse = {
  curr_q: string;
  prev_q: string;
  rows: Array<{
    security_id: number;
    security_name: string | null;
    ticker?: string | null;
    instrument_type: string | null;
    net_holder_count: number;
    net_shares: number;
  }>;
};

export type AccumulationHistoryResponse = {
  quarters: string[];
  rows: Array<{
    security_id: number;
    security_name: string | null;
    ticker?: string | null;
    series: Array<{
      report_date: string;
      net_shares: number;
      net_holder_count: number;
    }>;
  }>;
};

export type New5PctResponse = {
  start_date: string;
  end_date: string;
  rows: Array<{
    report_date: string;
    manager_id: number | null;
    manager_name: string | null;
    security_id: number | null;
    security_name: string | null;
    percent_beneficial_owned: number | null;
    shares_beneficial_owned: number | null;
    accession_no: string;
    form_type: string;
  }>;
};

export type ManagerUniverseResponse = {
  rows: Array<{
    rank: number;
    manager_id: number;
    cik: string | null;
    manager_name: string;
    total_value_usd: number | null;
    as_of_report_date: string;
    is_active: number;
  }>;
};

export type InstitutionUniverseResponse = ManagerUniverseResponse;
export type InstitutionSearchResponse = {
  query: string;
  rows: InstitutionUniverseResponse["rows"];
};

export type HomeOverviewResponse = {
  latest_quarter: string | null;
  previous_quarter: string | null;
  pulse: {
    universe_count: number;
    accum_count: number;
    dist_count: number;
    breadth_accum_pct: number;
    breadth_dist_pct: number;
    holders_added: number;
    holders_trimmed: number;
    participation_increase_pct: number;
    net_value_change_usd: number;
    form_13d_30d: number;
    form_13g_30d: number;
    bo_13d_share_30d: number;
    bo_13g_share_30d: number;
  };
  trust: {
    latest_quarter_loaded: string | null;
    managers_in_universe: number;
    managers_with_positions: number;
    holdings_rows_latest_quarter: number;
    mapping_coverage_pct_latest_quarter: number;
  };
  bo_activity_30d: {
    unique_filers: number;
    unique_securities: number;
  };
  flow_distribution: {
    bin_count: number;
    max_abs_value_usd: number;
    raw_max_abs_value_usd?: number;
    clip_low_usd?: number;
    clip_high_usd?: number;
    total_securities: number;
    filters?: {
      min_holders?: number;
      min_total_value_usd?: number;
      clip_lower_quantile?: number;
      clip_upper_quantile?: number;
      binning_method?: string;
      min_bins?: number;
      max_bins?: number;
    };
    bins: Array<{
      bin_index: number;
      range_start_usd: number;
      range_end_usd: number;
      count: number;
      pct_of_universe?: number;
      top_contributors?: Array<{
        security_id: number;
        ticker: string | null;
        security_name: string | null;
        label: string;
        net_value_usd: number;
      }>;
    }>;
  };
  pulse_series: {
    breadth_accum_pct: Array<{ report_date: string; value: number }>;
    participation_increase_pct: Array<{ report_date: string; value: number }>;
    net_value_change_usd: Array<{ report_date: string; value: number }>;
    bo_13d_share_pct: Array<{ report_date: string; value: number }>;
  };
  top_movers: {
    accumulated: Array<{
      security_id: number;
      ticker: string | null;
      security_name: string | null;
      net_shares: number;
      net_value_change_usd: number;
      net_holder_count: number;
      holders_count: number;
      top10_pct: number;
      total_value_usd: number;
      series: Array<{ report_date: string; net_shares: number; net_holder_count: number }>;
    }>;
    distributed: Array<{
      security_id: number;
      ticker: string | null;
      security_name: string | null;
      net_shares: number;
      net_value_change_usd: number;
      net_holder_count: number;
      holders_count: number;
      top10_pct: number;
      total_value_usd: number;
      series: Array<{ report_date: string; net_shares: number; net_holder_count: number }>;
    }>;
    new_holders: Array<{
      security_id: number;
      ticker: string | null;
      security_name: string | null;
      net_shares: number;
      net_value_change_usd: number;
      net_holder_count: number;
      holders_count: number;
      top10_pct: number;
      total_value_usd: number;
      series: Array<{ report_date: string; net_shares: number; net_holder_count: number }>;
    }>;
  };
  breadth_concentration: Array<{
    security_id: number;
    ticker: string | null;
    security_name: string | null;
    holders_count: number;
    top10_pct: number;
    total_value_usd: number;
  }>;
};

export type ApiUsageResponse = {
  summary: Array<{
    provider: string;
    calls: number;
    ok_calls: number;
    error_calls: number;
    avg_latency_ms: number;
  }>;
  recent: Array<{
    provider: string;
    endpoint: string;
    request_ts: string;
    status_code: number | null;
    ok: number;
    latency_ms: number | null;
    cache_hit: number;
  }>;
};

export type PipelineRunEvent = {
  run_id: string;
  event_ts: string;
  stage: string;
  status: string;
  message: string | null;
  metrics_json: string | null;
  metrics: Record<string, unknown>;
};

export type PipelineRunLatestResponse = {
  run_id: string | null;
  current: PipelineRunEvent | null;
  events: PipelineRunEvent[];
};

export type AiObservabilityResponse = {
  runtime: {
    enabled: boolean;
    api_key_configured: boolean;
    base_origin: string;
    model: string;
    temperature: number;
    request_timeout_seconds: number;
    max_steps: number;
    sql_fallback_enabled: boolean;
    max_output_tokens: number;
    max_history_messages: number;
    max_message_chars: number;
    max_tool_result_chars: number;
  };
  usage_windows: Array<{
    window: string;
    calls: number;
    ok_calls: number;
    error_calls: number;
    avg_latency_ms: number;
    p95_latency_ms: number | null;
  }>;
  status_breakdown: Array<{
    status_code: number | null;
    calls: number;
  }>;
  model_calls: Array<{
    model: string;
    calls: number;
  }>;
  recent: Array<{
    request_ts: string;
    endpoint: string;
    status_code: number | null;
    ok: number;
    latency_ms: number | null;
  }>;
};

export type SecuritySearchResponse = {
  query: string;
  rows: Array<{
    security_id: number;
    security_name: string | null;
    issuer_name: string | null;
    ticker: string | null;
    mic: string | null;
  }>;
};

export type Feed13DGResponse = {
  start_date: string;
  end_date: string;
  filters: {
    event_type: string | null;
    form_type: string | null;
    include_other: number;
    mapped_only: number;
    include_low_quality: number;
    ticker: string | null;
    manager_key: string | null;
    q: string | null;
  };
  counts: {
    rows: number;
    by_event_type: Record<string, number>;
  };
  rows: Array<{
    bo_event_id: number;
    report_date: string;
    event_type: string;
    percent_beneficial_owned: number | null;
    shares_beneficial_owned: number | null;
    mapping_status: string;
    mapping_confidence: number | null;
    cusip_raw: string | null;
    ticker_raw: string | null;
    manager_id: number | null;
    manager_name: string | null;
    security_id: number | null;
    security_name: string | null;
    issuer_name_raw: string | null;
    ticker: string | null;
    security_display: string | null;
    is_low_quality_security: number;
    filing_id: number;
    accession_no: string;
    form_type: string;
    filed_at: string | null;
    sec_url: string | null;
  }>;
};

export function getSecurity(ticker: string) {
  return requestJson<SecurityPageResponse>(`/security/${encodeURIComponent(ticker.toUpperCase())}`);
}

export function getSecurityEvents(ticker: string) {
  return requestJson<SecurityEventResponse>(`/security/${encodeURIComponent(ticker.toUpperCase())}/events`);
}

export function getSecurityEventsFiltered(
  ticker: string,
  options?: { new5pctOnly?: boolean; startDate?: string; endDate?: string; limitN?: number }
) {
  const params = new URLSearchParams();
  if (options?.new5pctOnly) params.set("new_5pct_only", "1");
  if (options?.startDate) params.set("start_date", options.startDate);
  if (options?.endDate) params.set("end_date", options.endDate);
  params.set("limit_n", String(options?.limitN ?? 100));
  const qs = params.toString();
  return requestJson<SecurityEventResponse>(
    `/security/${encodeURIComponent(ticker.toUpperCase())}/events${qs ? `?${qs}` : ""}`
  );
}

export function getInstitution(institutionKey: string) {
  return requestJson<InstitutionPageResponse>(`/institution/${encodeURIComponent(institutionKey)}`);
}

export function getManager(managerKey: string) {
  return getInstitution(managerKey);
}

export function getAccumulation(currQ: string, prevQ: string, limitN = 100) {
  return requestJson<AccumulationResponse>(
    `/screeners/accumulation?curr_q=${encodeURIComponent(currQ)}&prev_q=${encodeURIComponent(prevQ)}&limit_n=${limitN}`
  );
}

export function getAccumulationHistory(limitN = 50) {
  return requestJson<AccumulationHistoryResponse>(`/screeners/accumulation-history?limit_n=${limitN}`);
}

export function getNew5Pct(startDate: string, endDate: string, limitN = 100) {
  return requestJson<New5PctResponse>(
    `/screeners/new-5pct-holders?start_date=${encodeURIComponent(startDate)}&end_date=${encodeURIComponent(endDate)}&limit_n=${limitN}`
  );
}

export function getHomeOverview(
  options?: {
    quartersN?: number;
    topN?: number;
    scatterN?: number;
    strongSharesThreshold?: number;
    strongHoldersThreshold?: number;
    flowMinHolders?: number;
    flowMinTotalValueUsd?: number;
    flowClipLowerQuantile?: number;
    flowClipUpperQuantile?: number;
  }
) {
  const params = new URLSearchParams();
  if (options?.quartersN !== undefined) params.set("quarters_n", String(options.quartersN));
  if (options?.topN !== undefined) params.set("top_n", String(options.topN));
  if (options?.scatterN !== undefined) params.set("scatter_n", String(options.scatterN));
  if (options?.strongSharesThreshold !== undefined) params.set("strong_shares_threshold", String(options.strongSharesThreshold));
  if (options?.strongHoldersThreshold !== undefined) params.set("strong_holders_threshold", String(options.strongHoldersThreshold));
  if (options?.flowMinHolders !== undefined) params.set("flow_min_holders", String(options.flowMinHolders));
  if (options?.flowMinTotalValueUsd !== undefined) params.set("flow_min_total_value_usd", String(options.flowMinTotalValueUsd));
  if (options?.flowClipLowerQuantile !== undefined) params.set("flow_clip_lower_quantile", String(options.flowClipLowerQuantile));
  if (options?.flowClipUpperQuantile !== undefined) params.set("flow_clip_upper_quantile", String(options.flowClipUpperQuantile));
  const qs = params.toString();
  return requestJson<HomeOverviewResponse>(`/home/overview${qs ? `?${qs}` : ""}`);
}

export function getInstitutionUniverse(limitN = 300) {
  return requestJson<InstitutionUniverseResponse>(`/ops/institution-universe?limit_n=${limitN}`);
}

export function getManagerUniverse(limitN = 300) {
  return getInstitutionUniverse(limitN);
}

export function getApiUsage(days = 7, limitN = 100) {
  return requestJson<ApiUsageResponse>(`/ops/api-usage?days=${days}&limit_n=${limitN}`);
}

export function getPipelineRunLatest() {
  return requestJson<PipelineRunLatestResponse>("/ops/pipeline-runs/latest");
}

export function getAiObservability(days = 7, recentN = 100) {
  return requestJson<AiObservabilityResponse>(`/ops/ai-observability?days=${days}&recent_n=${recentN}`);
}

export function searchSecurities(query: string, limitN = 20) {
  return requestJson<SecuritySearchResponse>(
    `/security/search?q=${encodeURIComponent(query)}&limit_n=${limitN}`
  );
}

export function searchInstitutions(query: string, limitN = 20) {
  return requestJson<InstitutionSearchResponse>(
    `/institution/search?q=${encodeURIComponent(query)}&limit_n=${limitN}`
  );
}

export function get13DGFeed(
  options?: {
    limitN?: number;
    days?: number;
    startDate?: string;
    endDate?: string;
    eventType?: "NEW_5PCT" | "EXIT_5PCT" | "AMENDMENT_UP" | "AMENDMENT_DOWN" | "OTHER";
    formType?: string;
    includeOther?: boolean;
    mappedOnly?: boolean;
    includeLowQuality?: boolean;
    ticker?: string;
    managerKey?: string;
    q?: string;
  }
) {
  const params = new URLSearchParams();
  if (options?.limitN !== undefined) params.set("limit_n", String(options.limitN));
  if (options?.days !== undefined) params.set("days", String(options.days));
  if (options?.startDate) params.set("start_date", options.startDate);
  if (options?.endDate) params.set("end_date", options.endDate);
  if (options?.eventType) params.set("event_type", options.eventType);
  if (options?.formType) params.set("form_type", options.formType);
  if (options?.includeOther !== undefined) params.set("include_other", options.includeOther ? "1" : "0");
  if (options?.mappedOnly !== undefined) params.set("mapped_only", options.mappedOnly ? "1" : "0");
  if (options?.includeLowQuality !== undefined) params.set("include_low_quality", options.includeLowQuality ? "1" : "0");
  if (options?.ticker) params.set("ticker", options.ticker.toUpperCase());
  if (options?.managerKey) params.set("manager_key", options.managerKey);
  if (options?.q) params.set("q", options.q);
  const qs = params.toString();
  return requestJson<Feed13DGResponse>(`/feeds/13dg${qs ? `?${qs}` : ""}`);
}
