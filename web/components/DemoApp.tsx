"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";
import {
  askQuestion,
  enqueueVideo,
  extractYouTubeId,
  getJobStatus,
  type ChatMessage,
  type Citation,
  type JobStatus,
} from "@/lib/api";
import { ChatPanel } from "@/components/ChatPanel";
import { PipelineViz } from "@/components/PipelineViz";
import { VideoPane } from "@/components/VideoPane";

export function DemoApp() {
  const [urlInput, setUrlInput] = useState(
    "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
  );
  const [sourceUrl, setSourceUrl] = useState<string | null>(null);
  const [localObjectUrl, setLocalObjectUrl] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [status, setStatus] = useState<JobStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [seekTo, setSeekTo] = useState<number | null>(null);

  const ready = status?.status === "succeeded";

  useEffect(() => {
    if (!jobId) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const next = await getJobStatus(jobId);
        if (!cancelled) setStatus(next);
        if (next.status === "succeeded" || next.status === "failed") return;
        window.setTimeout(tick, 900);
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "Polling failed");
        }
      }
    };
    tick();
    return () => {
      cancelled = true;
    };
  }, [jobId]);

  useEffect(() => {
    return () => {
      if (localObjectUrl) URL.revokeObjectURL(localObjectUrl);
    };
  }, [localObjectUrl]);

  const ytId = useMemo(
    () => (sourceUrl ? extractYouTubeId(sourceUrl) : null),
    [sourceUrl],
  );

  async function startFromUrl(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessages([]);
    setSeekTo(null);
    const url = urlInput.trim();
    if (!extractYouTubeId(url)) {
      setError("Enter a valid YouTube URL for the demo player.");
      return;
    }
    setBusy(true);
    try {
      if (localObjectUrl) {
        URL.revokeObjectURL(localObjectUrl);
        setLocalObjectUrl(null);
      }
      setSourceUrl(url);
      const videoId = `yt-${extractYouTubeId(url)}`;
      const enq = await enqueueVideo({ videoId, sourceUri: url });
      setJobId(enq.job_id);
      setStatus({
        job_id: enq.job_id,
        video_id: videoId,
        status: "queued",
        stage: "ingest",
        progress: 0,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to enqueue");
    } finally {
      setBusy(false);
    }
  }

  async function onUpload(file: File | null) {
    if (!file) return;
    setError(null);
    setMessages([]);
    setSeekTo(null);
    setBusy(true);
    try {
      if (localObjectUrl) URL.revokeObjectURL(localObjectUrl);
      const obj = URL.createObjectURL(file);
      setLocalObjectUrl(obj);
      setSourceUrl(null);
      const videoId = `upload-${file.name.replace(/[^a-zA-Z0-9_-]/g, "").slice(0, 40)}`;
      const enq = await enqueueVideo({
        videoId,
        sourceUri: `upload://${file.name}`,
      });
      setJobId(enq.job_id);
      setStatus({
        job_id: enq.job_id,
        video_id: videoId,
        status: "queued",
        stage: "ingest",
        progress: 0,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload enqueue failed");
    } finally {
      setBusy(false);
    }
  }

  async function onAsk(question: string) {
    if (!jobId || !ready) return;
    setBusy(true);
    setError(null);
    const userMsg: ChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      content: question,
    };
    setMessages((m) => [...m, userMsg]);
    try {
      const result = await askQuestion(jobId, question);
      setMessages((m) => [
        ...m,
        {
          id: `a-${Date.now()}`,
          role: "assistant",
          content: result.answer,
          citations: result.citations,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ask failed");
    } finally {
      setBusy(false);
    }
  }

  function onSeek(citation: Citation) {
    setSeekTo(citation.start_time);
  }

  return (
    <div className="relative min-h-screen bg-meridian text-fog">
      <div className="pointer-events-none absolute inset-0 bg-grid opacity-40" />
      <div className="relative mx-auto max-w-6xl px-5 pb-16 pt-10 md:px-8">
        <header className="animate-rise mb-10">
          <p className="text-xs uppercase tracking-[0.28em] text-brass">Meridian</p>
          <h1 className="mt-3 max-w-3xl font-display text-5xl leading-[1.05] text-fog md:text-6xl">
            Ask the long video.
            <span className="block text-fog/70">Get answers you can seek.</span>
          </h1>
          <p className="mt-4 max-w-2xl text-base leading-relaxed text-fog/70 md:text-lg">
            Paste a YouTube URL or upload a clip. Watch the hierarchy build, then
            chat with grounded citations that jump the player to the evidence.
          </p>
        </header>

        <div className="mb-4 rounded-xl border border-brass/25 bg-brass/10 px-4 py-3 text-sm text-fog/85">
          <strong className="text-brass-bright">Demo quota:</strong> shared
          rate-limited try-it mode via API key{" "}
          <code className="text-fog">demo-web</code>. Cloud spend is capped by the
          Terraform billing budget alert on the GCP project - see{" "}
          <code className="text-fog">infra/terraform</code>.
        </div>

        <form
          onSubmit={startFromUrl}
          className="animate-rise mb-8 grid gap-3 md:grid-cols-[1fr_auto_auto]"
          style={{ animationDelay: "80ms" }}
        >
          <input
            value={urlInput}
            onChange={(e) => setUrlInput(e.target.value)}
            placeholder="https://www.youtube.com/watch?v=..."
            className="rounded-xl border border-fog/15 bg-ink-soft/80 px-4 py-3 text-sm outline-none ring-sea/30 placeholder:text-fog/35 focus:ring-2"
          />
          <button
            type="submit"
            disabled={busy}
            className="rounded-xl bg-sea px-5 py-3 text-sm font-semibold text-ink transition hover:brightness-110 disabled:opacity-50"
          >
            Process URL
          </button>
          <label className="cursor-pointer rounded-xl border border-fog/20 bg-ink-mist/50 px-5 py-3 text-center text-sm font-semibold text-fog transition hover:border-fog/40">
            Upload
            <input
              type="file"
              accept="video/*"
              className="hidden"
              onChange={(e) => onUpload(e.target.files?.[0] ?? null)}
            />
          </label>
        </form>

        {error && (
          <p className="mb-6 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm text-red-200">
            {error}
          </p>
        )}

        <div className="grid gap-6 lg:grid-cols-[1.4fr_0.9fr]">
          <div className="space-y-6">
            <VideoPane
              sourceUrl={sourceUrl}
              localObjectUrl={localObjectUrl}
              seekTo={seekTo}
            />
            <ChatPanel
              messages={messages}
              busy={busy || !ready}
              onAsk={onAsk}
              onSeek={onSeek}
            />
            {!ready && jobId && (
              <p className="text-sm text-fog/55">
                Job <code>{jobId.slice(0, 8)}</code> · {status?.status}
                {ytId ? ` · YouTube ${ytId}` : ""} - chat unlocks when processing
                succeeds.
              </p>
            )}
          </div>
          <PipelineViz status={status} />
        </div>
      </div>
    </div>
  );
}
