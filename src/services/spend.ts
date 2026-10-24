import { and, eq, gte } from "drizzle-orm";
import { db } from "../database.js";
import { jobs } from "../schema.js";
import { settings } from "../config.js";
import { parseMetrics, stepCost } from "./cost.js";

export async function todaysSpend(): Promise<number> {
  const todayStart = new Date();
  todayStart.setUTCHours(0, 0, 0, 0);
  const completed = await db
    .select({ metricsJson: jobs.metricsJson })
    .from(jobs)
    .where(and(eq(jobs.status, "completed"), gte(jobs.completedAt, todayStart)));
  let total = 0;
  for (const job of completed) total += stepCost(parseMetrics(job.metricsJson));
  return total;
}

export interface SpendGate {
  blocked: boolean;
  spend: number;
  limit: number;
  waitMs: number;
}

export async function checkSpendGate(): Promise<SpendGate> {
  const limit = settings.dailySpendLimit;
  if (!(limit > 0)) return { blocked: false, spend: 0, limit, waitMs: 0 };
  const spend = await todaysSpend();
  if (spend < limit) return { blocked: false, spend, limit, waitMs: 0 };
  const midnight = new Date();
  midnight.setUTCHours(24, 0, 0, 0);
  return { blocked: true, spend, limit, waitMs: Math.max(60_000, midnight.getTime() - Date.now()) };
}
