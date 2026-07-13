"use client";

import type { ChatMessage, Citation } from "@/lib/api";

type Props = {
  messages: ChatMessage[];
  busy: boolean;
  onSeek: (citation: Citation) => void;
  onAsk: (question: string) => void;
};

export function ChatPanel({ messages, busy, onSeek, onAsk }: Props) {
  return (
    <section className="flex h-full min-h-[28rem] flex-col rounded-2xl border border-fog/10 bg-ink-soft/70 backdrop-blur">
      <header className="border-b border-fog/10 px-5 py-4">
        <p className="text-xs uppercase tracking-[0.2em] text-brass">Ask the video</p>
        <h2 className="mt-1 font-display text-2xl text-fog">Grounded Q&amp;A</h2>
      </header>

      <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
        {messages.length === 0 && (
          <p className="text-sm text-fog/55">
            When processing finishes, ask about who is on the panel, what
            happened in a scene, or any detail from the video—answers include
            seekable timestamps.
          </p>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`animate-rise max-w-[92%] rounded-2xl px-4 py-3 text-sm leading-relaxed ${
              m.role === "user"
                ? "ml-auto bg-sea/20 text-fog"
                : "bg-ink-mist/60 text-fog/90"
            }`}
          >
            <p className="whitespace-pre-wrap">{m.content}</p>
            {m.citations && m.citations.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {m.citations.map((c, idx) => (
                  <button
                    key={`${c.start_time}-${idx}`}
                    type="button"
                    onClick={() => onSeek(c)}
                    className="rounded-full border border-brass/40 bg-brass/10 px-3 py-1 text-xs text-brass-bright transition hover:bg-brass/20"
                  >
                    {formatTs(c.start_time)}-{formatTs(c.end_time)}
                  </button>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>

      <form
        className="border-t border-fog/10 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          const fd = new FormData(e.currentTarget);
          const q = String(fd.get("q") || "").trim();
          if (!q || busy) return;
          onAsk(q);
          e.currentTarget.reset();
        }}
      >
        <div className="flex gap-2">
          <input
            name="q"
            disabled={busy}
            placeholder="Ask a question about this video…"
            className="flex-1 rounded-xl border border-fog/15 bg-ink px-4 py-3 text-sm text-fog outline-none ring-sea/40 placeholder:text-fog/35 focus:ring-2 disabled:opacity-50"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-brass px-4 py-3 text-sm font-semibold text-ink transition hover:bg-brass-bright disabled:opacity-50"
          >
            Ask
          </button>
        </div>
      </form>
    </section>
  );
}

function formatTs(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}
