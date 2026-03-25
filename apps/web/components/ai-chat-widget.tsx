"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useChat } from "@ai-sdk/react";
import type { UIMessage } from "@ai-sdk/react";
import { Sixtyfour_Convergence } from "next/font/google";
import { Bot, Loader2, MessageCircle, Octagon, Send, X } from "lucide-react";

const MAX_HISTORY_MESSAGES = 12;
const MAX_MESSAGE_CHARS = 1800;
const iftyWordmarkFont = Sixtyfour_Convergence({
  subsets: ["latin"],
  weight: "400",
  display: "swap",
});

type BackendChatMessage = {
  role: "user" | "assistant";
  content: string;
};

type CitationSource = {
  label: string;
  path?: string;
};

type SendMessagesOptions = {
  trigger: "submit-message" | "regenerate-message";
  chatId: string;
  messageId: string | undefined;
  messages: UIMessage[];
  abortSignal: AbortSignal | undefined;
  headers?: Record<string, string> | Headers;
  body?: object;
  metadata?: unknown;
};

const SOURCES_MARKER_RE = /\[\[IFTY_SOURCES_B64:([A-Za-z0-9+/=]+)\]\]\s*$/;

function parseAssistantPayload(text: string): { body: string; sources: CitationSource[] } {
  const trimmed = text.trim();
  const match = trimmed.match(SOURCES_MARKER_RE);
  if (!match) return { body: text, sources: [] };

  const body = trimmed.replace(SOURCES_MARKER_RE, "").trim();
  try {
    const binary = atob(match[1]);
    const bytes = Uint8Array.from(binary, (ch) => ch.charCodeAt(0));
    const decoded = new TextDecoder().decode(bytes);
    const parsed = JSON.parse(decoded);
    const sources: CitationSource[] = Array.isArray(parsed)
      ? parsed
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
    return { body, sources };
  } catch {
    return { body, sources: [] };
  }
}

function clipMessage(text: string): string {
  if (text.length <= MAX_MESSAGE_CHARS) return text;
  return `${text.slice(0, MAX_MESSAGE_CHARS)}…`;
}

function extractMessageText(message: UIMessage): string {
  const raw = message as unknown as { content?: unknown; parts?: unknown };
  const parts = Array.isArray(raw.parts) ? raw.parts : [];
  const out: string[] = [];

  for (const part of parts) {
    if (!part || typeof part !== "object") continue;
    const rec = part as Record<string, unknown>;
    const type = String(rec.type ?? "").toLowerCase();
    const text = typeof rec.text === "string" ? rec.text.trim() : "";
    if (!text) continue;
    if (type === "" || type === "text" || type === "reasoning") {
      out.push(text);
    }
  }

  if (out.length) return out.join("\n").trim();
  return typeof raw.content === "string" ? raw.content.trim() : "";
}

function toBackendMessages(messages: UIMessage[]): BackendChatMessage[] {
  const out: BackendChatMessage[] = [];
  for (const message of messages) {
    if (message.role !== "user" && message.role !== "assistant") continue;
    const rawText = extractMessageText(message);
    const body = message.role === "assistant" ? parseAssistantPayload(rawText).body : rawText;
    const text = clipMessage(body);
    if (!text) continue;
    out.push({ role: message.role, content: text });
  }
  return out.slice(-MAX_HISTORY_MESSAGES);
}

async function sendChatRequest(options: SendMessagesOptions): Promise<ReadableStream<Record<string, unknown>>> {
  const compactMessages = toBackendMessages(options.messages);
  const response = await fetch("/api/ai/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: compactMessages,
      trigger: options.trigger,
      messageId: options.messageId,
      id: options.chatId,
    }),
    signal: options.abortSignal,
    cache: "no-store",
  });

  if (!response.ok) {
    const errorText = await response.text();
    throw new Error(errorText || `AI request failed with status ${response.status}`);
  }
  if (!response.body) {
    throw new Error("AI response body is empty.");
  }

  return response.body.pipeThrough(new TextDecoderStream()).pipeThrough(
    new TransformStream<string, Record<string, unknown>>({
      start(controller) {
        controller.enqueue({ type: "start" });
        controller.enqueue({ type: "start-step" });
        controller.enqueue({ type: "text-start", id: "text-1" });
      },
      transform(chunk, controller) {
        if (!chunk) return;
        controller.enqueue({ type: "text-delta", id: "text-1", delta: chunk });
      },
      flush(controller) {
        controller.enqueue({ type: "text-end", id: "text-1" });
        controller.enqueue({ type: "finish-step" });
        controller.enqueue({ type: "finish" });
      },
    })
  );
}

export function AiChatWidget() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement | null>(null);

  const transport = useMemo(
    () => ({
      sendMessages: (options: SendMessagesOptions) => sendChatRequest(options),
      reconnectToStream: async () => null,
    }),
    []
  );

  const { messages, sendMessage, stop, status, error } = useChat({
    transport: transport as any,
    experimental_throttle: 40,
  });

  const isLoading = status === "submitted" || status === "streaming";

  const scrollToBottom = useCallback(() => {
    if (!scrollRef.current) return;
    scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, []);

  useEffect(() => {
    if (!open) return;
    scrollToBottom();
  }, [open, messages, status, scrollToBottom]);

  const submit = useCallback(async () => {
    const text = input.trim();
    if (!text || isLoading) return;
    setInput("");
    await sendMessage({ text });
  }, [input, isLoading, sendMessage]);

  const onSubmit = useCallback(
    (event: React.FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      void submit();
    },
    [submit]
  );

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-label={open ? "Close AI chat" : "Open AI chat"}
        className="sidebar-circle fixed bottom-6 right-6 z-50 inline-flex h-12 w-12 items-center justify-center border border-violet-400/65 bg-[#140a24]/92 text-violet-300 shadow-[0_0_0_1px_rgba(167,139,250,.28)_inset,0_8px_26px_rgba(0,0,0,.55)] transition hover:border-violet-300 hover:bg-[#1a0d2e]"
      >
        {open ? <X className="h-5 w-5" /> : <MessageCircle className="h-5 w-5" />}
      </button>

      {open ? (
        <section className="fixed bottom-20 right-6 z-50 flex h-[560px] w-[370px] flex-col border border-violet-500/35 bg-black/45 shadow-[0_18px_48px_rgba(0,0,0,.62),0_0_0_1px_rgba(167,139,250,.15)] backdrop-blur-md backdrop-saturate-150 supports-[backdrop-filter]:bg-black/25">
          <header className="flex items-center justify-between border-b border-violet-500/25 bg-violet-950/60 px-4 py-3 supports-[backdrop-filter]:bg-violet-950/40">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-7 w-7 items-center justify-center border border-violet-400/50 bg-violet-500/12 text-violet-300">
                <Bot className="h-4 w-4" />
              </span>
              <div>
                <div className={`${iftyWordmarkFont.className} text-sm text-slate-100`}>Ifty AI</div>
              </div>
            </div>
            {isLoading ? (
              <button
                type="button"
                onClick={() => {
                  void stop();
                }}
                aria-label="Stop response"
                title="Stop response"
                className="inline-flex h-8 w-8 items-center justify-center border border-violet-400/40 text-slate-300 transition hover:border-rose-400/75 hover:text-rose-200"
              >
                <Octagon className="h-4 w-4" />
              </button>
            ) : null}
          </header>

          <div
            ref={scrollRef}
            className="app-main-scroll flex-1 space-y-3 overflow-y-auto bg-black/50 px-4 py-3 supports-[backdrop-filter]:bg-black/35"
          >
            {messages.map((message) => {
              const isUser = message.role === "user";
              const rawText = extractMessageText(message);
              const parsed = isUser ? { body: rawText, sources: [] } : parseAssistantPayload(rawText);
              const text = parsed.body;
              if (!text && parsed.sources.length === 0) return null;
              return (
                <div key={message.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[86%] border px-3 py-2 text-sm leading-relaxed ${
                      isUser
                        ? "border-violet-300/70 bg-violet-500/30 text-slate-100"
                        : "border-[#9f8ac9]/55 bg-[#3d3158]/68 text-slate-100"
                    }`}
                  >
                    <div className="mb-1 text-[10px] uppercase tracking-wide text-slate-400">
                      {isUser ? "You" : "Ifty AI"}
                    </div>
                    {text ? <div className="whitespace-pre-wrap break-words">{text}</div> : null}
                    {!isUser && parsed.sources.length > 0 ? (
                      <div className="mt-2 border-t border-cyan-300/25 pt-1.5">
                        <div className="mb-1 text-[10px] uppercase tracking-wide text-cyan-100/80">Sources</div>
                        <div className="flex flex-wrap gap-1.5">
                          {parsed.sources.map((source, index) =>
                            source.path ? (
                              <a
                                key={`${source.label}-${index}`}
                                href={source.path}
                                className="rounded-none border border-cyan-300/35 bg-cyan-500/15 px-1.5 py-0.5 text-[11px] text-cyan-50 transition hover:border-cyan-200/65 hover:bg-cyan-500/22"
                              >
                                {source.label}
                              </a>
                            ) : (
                              <span
                                key={`${source.label}-${index}`}
                                className="rounded-none border border-cyan-300/25 bg-cyan-500/10 px-1.5 py-0.5 text-[11px] text-cyan-100/90"
                              >
                                {source.label}
                              </span>
                            )
                          )}
                        </div>
                      </div>
                    ) : null}
                  </div>
                </div>
              );
            })}

            {isLoading ? (
              <div className="flex items-center gap-2 text-xs text-slate-400">
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
                Thinking...
              </div>
            ) : null}

            {error ? (
              <div className="border border-rose-400/45 bg-rose-500/10 px-3 py-2 text-xs text-rose-200">
                {String(error.message || "AI request failed")}
              </div>
            ) : null}
          </div>

          <form
            onSubmit={onSubmit}
            className="border-t border-violet-500/25 bg-violet-950/60 px-3 py-3 supports-[backdrop-filter]:bg-violet-950/40"
          >
            <div className="flex items-end gap-2">
              <textarea
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask about securities, institutions, market pulse, or recent 13D/G activity."
                rows={2}
                className="min-h-[62px] flex-1 resize-none border border-violet-500/30 bg-[#0a0714]/80 px-3 py-2 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-violet-400/85"
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void submit();
                  }
                }}
              />
              <button
                type="submit"
                disabled={isLoading || input.trim().length === 0}
                className="inline-flex h-[38px] w-[38px] items-center justify-center border border-violet-400/60 bg-violet-500/16 text-violet-300 transition enabled:hover:bg-violet-500/30 disabled:cursor-not-allowed disabled:border-violet-500/20 disabled:bg-violet-500/8 disabled:text-slate-500"
              >
                <Send className="h-4 w-4" />
              </button>
            </div>
          </form>
        </section>
      ) : null}
    </>
  );
}
