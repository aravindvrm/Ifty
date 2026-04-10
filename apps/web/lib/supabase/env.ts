type SupabaseEnv = {
  url: string;
  anonKey: string;
};

function toTrimmed(value: string | undefined): string {
  return String(value ?? "").trim();
}

export function getSupabaseEnv(): SupabaseEnv | null {
  const url = toTrimmed(process.env.NEXT_PUBLIC_SUPABASE_URL);
  const anonKey = toTrimmed(process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY);
  if (!url || !anonKey) return null;
  return { url, anonKey };
}

export function isSupabaseConfigured(): boolean {
  return getSupabaseEnv() !== null;
}
