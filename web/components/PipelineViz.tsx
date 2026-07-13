"use client";

import { PIPELINE_STAGES, stageIndex, type JobStatus } from "@/lib/api";

type Props = {
  status: JobStatus | null;
};

export function PipelineViz({ status }: Props) {
  const active = status ? stageIndex(status.stage) : -1;

  return (
    <aside className="rounded-2xl border border-fog/10 bg-ink-soft/70 p-5 backdrop-blur">
      <p className="text-xs uppercase tracking-[0.2em] text-brass">How this works</p>
      <h2 className="mt-2 font-display text-2xl text-fog">Live pipeline</h2>
      <p className="mt-2 text-sm leading-relaxed text-fog/70">
        Transcript → chunking → retrieval → answer. Watch each stage light up
        as the job runs—same architecture the API and workers use.
      </p>

      <ol className="mt-6 space-y-3">
        {PIPELINE_STAGES.map((stage, idx) => {
          const isActive =
            status?.status === "running" && idx === active;
          const isComplete =
            status?.status === "succeeded" ||
            (active >= 0 && idx < active);

          return (
            <li
              key={stage.id}
              className={`animate-stage-in rounded-xl border px-3 py-3 transition ${
                isActive
                  ? "border-sea/50 bg-sea/10 animate-pulse-glow"
                  : isComplete
                    ? "border-fog/15 bg-ink-mist/40"
                    : "border-fog/5 bg-transparent opacity-60"
              }`}
              style={{ animationDelay: `${idx * 60}ms` }}
            >
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-sm font-semibold text-fog">{stage.label}</span>
                <span className="text-[11px] uppercase tracking-wider text-fog/45">
                  {isActive ? "running" : isComplete ? "done" : status ? "waiting" : "idle"}
                </span>
              </div>
              <p className="mt-1 text-xs leading-relaxed text-fog/60">{stage.detail}</p>
            </li>
          );
        })}
      </ol>

      {status && (
        <div className="mt-5">
          <div className="mb-1 flex justify-between text-[11px] uppercase tracking-wider text-fog/50">
            <span>Progress</span>
            <span>{Math.round((status.progress || 0) * 100)}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-ink-mist">
            <div
              className="h-full rounded-full bg-gradient-to-r from-sea to-brass transition-all duration-500"
              style={{ width: `${Math.max(4, (status.progress || 0) * 100)}%` }}
            />
          </div>
        </div>
      )}
    </aside>
  );
}
