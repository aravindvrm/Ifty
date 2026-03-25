import { NextResponse } from "next/server";

type ChatMessage = {
  role: "system" | "user" | "assistant";
  content: string;
};

type CitationSource = {
  label: string;
  path?: string;
};

const API_BASE = process.env.API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";
const MAX_HISTORY_MESSAGES = 12;
const MAX_MESSAGE_CHARS = 1800;

function _clipText(text: string): string {
  if (text.length <= MAX_MESSAGE_CHARS) return text;
  return `${text.slice(0, MAX_MESSAGE_CHARS)}…`;
}

function _extractTextParts(parts: unknown): string {
  if (!Array.isArray(parts)) return "";
  const out: string[] = [];
  for (const part of parts) {
    if (!part || typeof part !== "object") continue;
    const record = part as Record<string, unknown>;
    const type = String(record.type ?? "").toLowerCase();
    const text = typeof record.text === "string" ? record.text.trim() : "";
    if (!text) continue;
    if (type === "" || type === "text" || type === "reasoning") {
      out.push(text);
    }
  }
  return out.join("\n").trim();
}

function _normalizeMessages(rawMessages: unknown): ChatMessage[] {
  if (!Array.isArray(rawMessages)) return [];
  const normalized: ChatMessage[] = [];
  for (const raw of rawMessages) {
    if (!raw || typeof raw !== "object") continue;
    const record = raw as Record<string, unknown>;
    const role = String(record.role ?? "").toLowerCase();
    if (role !== "user" && role !== "assistant" && role !== "system") continue;

    let content = "";
    if (typeof record.content === "string") {
      content = record.content.trim();
    } else {
      content = _extractTextParts(record.parts);
    }

    if (!content) continue;
    if (role === "system") continue;
    normalized.push({ role, content: _clipText(content) } as ChatMessage);
  }
  if (!normalized.length) return [];
  return normalized.slice(-MAX_HISTORY_MESSAGES);
}

export async function POST(req: Request) {
  let payload: { prompt?: string; messages?: unknown };
  try {
    payload = (await req.json()) as { prompt?: string; messages?: unknown };
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }

  const prompt = _clipText((payload.prompt ?? "").trim());
  const cleaned = _normalizeMessages(payload.messages);
  const messages: ChatMessage[] = cleaned.length > 0 ? cleaned : prompt ? [{ role: "user", content: prompt }] : [];

  if (!messages.length) {
    return NextResponse.json({ error: "No message content provided" }, { status: 400 });
  }

  let response: Response;
  try {
    response = await fetch(`${API_BASE}/ai/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
      body: JSON.stringify({
        messages,
        include_trace: false,
      }),
    });
  } catch (error) {
    return NextResponse.json(
      {
        error: `AI backend unreachable: ${error instanceof Error ? error.message : String(error)}`,
      },
      { status: 502 }
    );
  }

  if (!response.ok) {
    const detail = await response.text();
    return NextResponse.json(
      {
        error: `AI backend error ${response.status}: ${detail}`,
      },
      { status: response.status }
    );
  }

  let data: { answer?: string; sources?: unknown };
  try {
    data = (await response.json()) as { answer?: string; sources?: unknown };
  } catch {
    return NextResponse.json({ error: "AI backend returned invalid JSON" }, { status: 502 });
  }

  const answer = String(data.answer ?? "").trim();
  const normalizedSources: CitationSource[] = Array.isArray(data.sources)
    ? data.sources
        .map((row) => {
          if (!row || typeof row !== "object") return null;
          const rec = row as Record<string, unknown>;
          const label = String(rec.label ?? "").trim();
          if (!label) return null;
          const out: CitationSource = { label };
          const path = String(rec.path ?? "").trim();
          if (path.startsWith("/")) out.path = path;
          return out;
        })
        .filter((row): row is CitationSource => row !== null)
        .slice(0, 8)
    : [];

  const marker =
    normalizedSources.length > 0
      ? `\n\n[[IFTY_SOURCES_B64:${Buffer.from(JSON.stringify(normalizedSources), "utf-8").toString("base64")}]]`
      : "";
  const responseText = `${answer}${marker}`.trim();

  return new Response(responseText, {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}
