const DEFAULT_POST_LOGIN_PATH = "/explore";

export function normalizeNextPath(input: string | null | undefined): string {
  const value = String(input ?? "").trim();
  if (!value) return DEFAULT_POST_LOGIN_PATH;
  if (!value.startsWith("/")) return DEFAULT_POST_LOGIN_PATH;
  if (value.startsWith("//")) return DEFAULT_POST_LOGIN_PATH;
  return value;
}

export function getDefaultPostLoginPath(): string {
  return DEFAULT_POST_LOGIN_PATH;
}
