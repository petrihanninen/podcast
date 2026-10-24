import { FatalError } from "workflow";
import { runResearch } from "../src/services/research.js";
import {
  outlineTranscript,
  planTranscript,
  saveTranscript,
  writeTranscriptPart,
  type LlmUsage,
  type Outline,
  type Segment,
  type TranscriptPlan,
} from "../src/services/transcript.js";
import { finishTts, planTts, synthesizeBatch, type TtsBatch, type TtsBatchResult } from "../src/services/tts.js";
import { finalizeEpisode } from "../src/services/finalize.js";
import { completeJob, failJob, startJob } from "../src/services/jobs.js";
import { checkSpendGate } from "../src/services/spend.js";
import type { PipelineStep } from "../src/view-helpers.js";

function fatalIfMisconfigured(e: unknown): never {
  const message = String((e as any)?.message ?? e);
  if (/not configured/i.test(message)) throw new FatalError(message);
  throw e;
}

export async function spendGateStep(episodeId: string, step: string) {
  "use step";
  const gate = await checkSpendGate();
  if (gate.blocked) {
    console.warn(
      `[workflow] Daily spend limit reached ($${gate.spend.toFixed(2)}/$${gate.limit.toFixed(2)}); ` +
        `episode ${episodeId} waits ${Math.round(gate.waitMs / 60000)} min before ${step}`
    );
  }
  return { blocked: gate.blocked, waitMs: gate.waitMs };
}

export async function researchStep(episodeId: string) {
  "use step";
  await startJob(episodeId, "research");
  try {
    const metrics = await runResearch(episodeId);
    await completeJob(episodeId, "research", metrics);
  } catch (e) {
    fatalIfMisconfigured(e);
  }
}
researchStep.maxRetries = 2;

export async function planTranscriptStep(episodeId: string): Promise<TranscriptPlan> {
  "use step";
  return planTranscript(episodeId);
}

export async function outlineTranscriptStep(episodeId: string, plan: TranscriptPlan) {
  "use step";
  try {
    return await outlineTranscript(episodeId, plan);
  } catch (e) {
    fatalIfMisconfigured(e);
  }
}
outlineTranscriptStep.maxRetries = 2;

export async function writeTranscriptPartStep(
  episodeId: string,
  plan: TranscriptPlan,
  partIndex: number,
  outline: Outline | null,
  previousTail: Segment[]
) {
  "use step";
  try {
    return await writeTranscriptPart(episodeId, plan, partIndex, outline, previousTail);
  } catch (e) {
    fatalIfMisconfigured(e);
  }
}
writeTranscriptPartStep.maxRetries = 2;

export async function saveTranscriptStep(
  episodeId: string,
  segments: Segment[],
  usage: LlmUsage,
  model: string,
  durationSeconds: number
) {
  "use step";
  await saveTranscript(episodeId, segments, usage, model, durationSeconds);
}

export async function planTtsStep(episodeId: string) {
  "use step";
  try {
    return await planTts(episodeId);
  } catch (e) {
    fatalIfMisconfigured(e);
  }
}
planTtsStep.maxRetries = 2;

export async function synthesizeBatchStep(batch: TtsBatch): Promise<TtsBatchResult> {
  "use step";
  try {
    return await synthesizeBatch(batch);
  } catch (e) {
    fatalIfMisconfigured(e);
  }
}
synthesizeBatchStep.maxRetries = 3;

export async function finishTtsStep(episodeId: string, results: TtsBatchResult[], wallSeconds: number) {
  "use step";
  await finishTts(episodeId, results, wallSeconds);
}

export async function finalizeStep(episodeId: string) {
  "use step";
  try {
    await finalizeEpisode(episodeId);
  } catch (e) {
    fatalIfMisconfigured(e);
  }
}
finalizeStep.maxRetries = 2;

export async function markFailedStep(episodeId: string, step: string, message: string) {
  "use step";
  await failJob(episodeId, step as PipelineStep, message);
}
