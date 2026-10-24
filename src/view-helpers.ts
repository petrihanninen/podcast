export const PIPELINE_STEPS = ["research", "transcript", "tts", "encode"] as const;
export type PipelineStep = (typeof PIPELINE_STEPS)[number];

export const STEP_LABELS: Record<string, string> = {
  research: "Research",
  transcript: "Transcript",
  tts: "Audio",
  encode: "Encode",
};

export const EPISODE_STATUS_FOR_STEP: Record<string, string> = {
  research: "researching",
  transcript: "writing_transcript",
  tts: "generating_audio",
  encode: "encoding",
};

export function statusBadge(status: string): string {
  const mapping: Record<string, string> = {
    ready: "badge--success",
    failed: "badge--error",
    pending: "badge--info",
  };
  return mapping[status] ?? "badge--warning";
}

export function statusLabel(status: string): string {
  const mapping: Record<string, string> = {
    pending: "Pending",
    researching: "Researching",
    writing_transcript: "Writing transcript",
    generating_audio: "Generating audio",
    encoding: "Encoding",
    ready: "Ready",
    failed: "Failed",
  };
  return mapping[status] ?? status.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatDuration(seconds: number | null): string {
  if (seconds == null) return "";
  const minutes = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

export function formatFileSize(sizeBytes: number | null): string {
  if (sizeBytes == null) return "";
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  if (sizeBytes < 1024 * 1024) return `${(sizeBytes / 1024).toFixed(1)} KB`;
  return `${(sizeBytes / (1024 * 1024)).toFixed(1)} MB`;
}

export interface TtsProgress {
  segments_completed: number;
  total_segments: number;
  audio_duration_seconds: number;
  audio_duration_formatted: string;
}

export function ttsProgressFromJob(job: any): TtsProgress | null {
  if (!job || job.status !== "running" || !job.progressTotal) return null;
  const seconds = Number(job.progressSeconds ?? 0);
  return {
    segments_completed: job.progressDone ?? 0,
    total_segments: job.progressTotal,
    audio_duration_seconds: seconds,
    audio_duration_formatted: formatDuration(Math.floor(seconds)),
  };
}

export function buildPipelineInfo(episode: any): Array<Record<string, unknown>> {
  const jobsByStep: Record<string, any> = {};
  for (const job of episode.jobs ?? []) {
    jobsByStep[job.step] = job;
  }

  return PIPELINE_STEPS.map((stepName) => {
    const job = jobsByStep[stepName];
    if (job) {
      let duration = null;
      if (job.startedAt && job.completedAt) {
        const totalSecs = Math.round(
          (new Date(job.completedAt).getTime() - new Date(job.startedAt).getTime()) / 1000
        );
        duration = totalSecs >= 60 ? `${Math.floor(totalSecs / 60)}m ${totalSecs % 60}s` : `${totalSecs}s`;
      }
      return {
        name: stepName,
        label: STEP_LABELS[stepName],
        status: job.status,
        attempts: job.attempts,
        duration,
      };
    }
    return {
      name: stepName,
      label: STEP_LABELS[stepName],
      status: "waiting",
      attempts: 0,
      duration: null,
    };
  });
}

export function getCurrentStepIndex(episode: any): number {
  if (episode.status === "ready") return PIPELINE_STEPS.length;
  const jobsByStep: Record<string, any> = {};
  for (const job of episode.jobs ?? []) {
    jobsByStep[job.step] = job;
  }
  for (let i = 0; i < PIPELINE_STEPS.length; i++) {
    const job = jobsByStep[PIPELINE_STEPS[i]];
    if (!job || job.status === "pending" || job.status === "running") return i;
  }
  return PIPELINE_STEPS.length;
}

export function getTtsProgress(episode: any): TtsProgress | null {
  if (episode.status !== "generating_audio") return null;
  const job = (episode.jobs ?? []).find((j: any) => j.step === "tts");
  return ttsProgressFromJob(job);
}
