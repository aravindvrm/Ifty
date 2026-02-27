INSERT INTO api_budgets (provider, max_per_minute, max_per_day, burst_per_second, notes, updated_at)
VALUES
  ('SEC', 480, NULL, 8, 'Keep below SEC 10 req/s policy; always send compliant User-Agent.', datetime('now')),
  ('POLYGON', 5, NULL, NULL, 'Free tier: 5 requests/minute.', datetime('now')),
  ('AV', NULL, 25, NULL, 'Free tier: reserve for low-frequency backfills.', datetime('now')),
  ('YF', 30, NULL, NULL, 'Unofficial source; local conservative cap with caching.', datetime('now')),
  ('OPENFIGI', 20, NULL, NULL, 'CUSIP to ticker enrichment budget.', datetime('now'))
ON CONFLICT(provider) DO UPDATE SET
  max_per_minute = excluded.max_per_minute,
  max_per_day = excluded.max_per_day,
  burst_per_second = excluded.burst_per_second,
  notes = excluded.notes,
  updated_at = datetime('now');
