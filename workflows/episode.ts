import { sleep } from "workflow";
import {
  finalizeStep,
  finishTtsStep,
  markFailedStep,
  outlineTranscriptStep,
  planTranscriptStep,
  planTtsStep,
  researchStep,
  saveTranscriptStep,
  spendGateStep,
  synthesizeBatchStep,
  writeTranscriptPartStep,
} from "./steps.js";

const STEP_ORDER = ["research", "transcript", "tts", "encode"] as const;
type Step = (typeof STEP_ORDER)[number];

export async function generateEpisode(episodeId: string, fromStep: string) {
  "use workflow";

  const startIndex = Math.max(0, STEP_ORDER.indexOf(fromStep as Step));

  for (let i = startIndex; i < STEP_ORDER.length; i++) {
    const step = STEP_ORDER[i];

    if (step !== "encode") {
      while (true) {
        const gate = await spendGateStep(episodeId, step);
        if (!gate.blocked) break;
        await sleep(gate.waitMs);
      }
    }

    try {
      if (step === "research") {
        await researchStep(episodeId);
      } else if (step === "transcript") {
        await runTranscript(episodeId);
      } else if (step === "tts") {
        await runTts(episodeId);
      } else {
        await finalizeStep(episodeId);
      }
    } catch (e: any) {
      await markFailedStep(episodeId, step, String(e?.message ?? e));
      throw e;
    }
  }

  return { episodeId, status: "ready" };
}

async function runTranscript(episodeId: string) {
  const startedAt = Date.now();
  const plan = await planTranscriptStep(episodeId);
  let usage = { input_tokens: 0, output_tokens: 0, cost_usd: 0, calls: 0 };
  let outline = null;
  if (plan.parts > 1) {
    const result = await outlineTranscriptStep(episodeId, plan);
    outline = result.outline;
    usage = add(usage, result.usage);
  }

  const segments: Array<{ speaker: string; text: string }> = [];
  let model = "";
  for (let part = 0; part < plan.parts; part++) {
    const result = await writeTranscriptPartStep(episodeId, plan, part, outline, segments.slice(-6));
    segments.push(...result.segments);
    usage = add(usage, result.usage);
    model = result.model;
  }

  await saveTranscriptStep(episodeId, segments, usage, model, (Date.now() - startedAt) / 1000);
}

async function runTts(episodeId: string) {
  const startedAt = Date.now();
  const { batches, parallel } = await planTtsStep(episodeId);
  const results = [];
  for (let i = 0; i < batches.length; i += parallel) {
    const group = batches.slice(i, i + parallel);
    const done = await Promise.all(group.map((batch) => synthesizeBatchStep(batch)));
    results.push(...done);
  }
  await finishTtsStep(episodeId, results, (Date.now() - startedAt) / 1000);
}

function add(
  a: { input_tokens: number; output_tokens: number; cost_usd: number; calls: number },
  b: { input_tokens: number; output_tokens: number; cost_usd: number; calls: number }
) {
  return {
    input_tokens: a.input_tokens + b.input_tokens,
    output_tokens: a.output_tokens + b.output_tokens,
    cost_usd: a.cost_usd + b.cost_usd,
    calls: a.calls + b.calls,
  };
}
