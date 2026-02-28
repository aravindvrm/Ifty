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
  };
};

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

export function getManager(managerKey: string) {
  return requestJson<ManagerPageResponse>(`/manager/${encodeURIComponent(managerKey)}`);
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

export function getManagerUniverse(limitN = 300) {
  return requestJson<ManagerUniverseResponse>(`/ops/manager-universe?limit_n=${limitN}`);
}

export function getApiUsage(days = 7, limitN = 100) {
  return requestJson<ApiUsageResponse>(`/ops/api-usage?days=${days}&limit_n=${limitN}`);
}

export function getPipelineRunLatest() {
  return requestJson<PipelineRunLatestResponse>("/ops/pipeline-runs/latest");
}

export function searchSecurities(query: string, limitN = 20) {
  return requestJson<SecuritySearchResponse>(
    `/security/search?q=${encodeURIComponent(query)}&limit_n=${limitN}`
  );
}
