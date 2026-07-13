"use client";

import { useMemo } from "react";
import dynamic from "next/dynamic";

const ReactPlayer = dynamic(() => import("react-player/lazy"), { ssr: false });

type Props = {
  sourceUrl: string | null;
  localObjectUrl: string | null;
  seekTo: number | null;
  onReady?: () => void;
};

export function VideoPane({ sourceUrl, localObjectUrl, seekTo }: Props) {
  const url = localObjectUrl || sourceUrl;

  const playerKey = useMemo(
    () => `${url ?? "none"}-${seekTo ?? "start"}`,
    [url, seekTo],
  );

  if (!url) {
    return (
      <div className="flex aspect-video items-center justify-center rounded-2xl border border-dashed border-fog/20 bg-ink-soft/50">
        <p className="max-w-xs text-center text-sm text-fog/55">
          Paste a YouTube link or upload a clip to begin.
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-2xl border border-fog/10 bg-black shadow-[0_20px_60px_rgba(0,0,0,0.35)]">
      <div className="aspect-video">
        <ReactPlayer
          key={playerKey}
          url={url}
          width="100%"
          height="100%"
          controls
          playing={seekTo != null}
          config={{
            youtube: {
              playerVars: {
                start: seekTo != null ? Math.floor(seekTo) : 0,
              },
            },
            file: {
              attributes: {
                controlsList: "nodownload",
              },
            },
          }}
          onReady={(player) => {
            if (seekTo != null && localObjectUrl) {
              const internal = player.getInternalPlayer?.();
              if (internal && typeof internal.currentTime === "number") {
                internal.currentTime = seekTo;
              } else if (typeof player.seekTo === "function") {
                player.seekTo(seekTo, "seconds");
              }
            }
          }}
        />
      </div>
    </div>
  );
}
