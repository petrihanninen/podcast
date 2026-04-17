import { sql } from "drizzle-orm";
import { db } from "./database.js";
import { logEntries } from "./schema.js";
import pino from "pino";

// ─── Module state ────────────────────────────────────────────────────
interface LogRecord {
  timestamp: Date;
  level: string;
  loggerName: string;
  message: string;
  source: string;
}

const buffer: LogRecord[] = [];
let source = "unknown";
let flushTimer: ReturnType<typeof setInterval> | null = null;
let pruneCounter = 0;

const FLUSH_INTERVAL_MS = 5000;
const MAX_LOGS_IN_DB = 5000;
const PRUNE_BATCH_SIZE = 500;
const MAX_BUFFER_SIZE = 1000;

// ─── Logger ──────────────────────────────────────────────────────────
export const logger = pino({
  level: "info",
  transport:
    process.env.NODE_ENV !== "production"
      ? { target: "pino-pretty", options: { colorize: true } }
      : undefined,
});

// ─── Buffer push (called from a pino hook or manually) ──────────────
export function pushLog(
  level: string,
  loggerName: string,
  message: string
): void {
  if (buffer.length >= MAX_BUFFER_SIZE) {
    buffer.shift();
  }
  buffer.push({
    timestamp: new Date(),
    level,
    loggerName,
    message,
    source,
  });
}

// ─── Wrap logger to also push to DB buffer ───────────────────────────
export function createLogger(name: string) {
  const child = logger.child({ name });
  return {
    info(msg: string, ...args: unknown[]) {
      const formatted = formatMsg(msg, args);
      child.info(formatted);
      pushLog("INFO", name, formatted);
    },
    warn(msg: string, ...args: unknown[]) {
      const formatted = formatMsg(msg, args);
      child.warn(formatted);
      pushLog("WARNING", name, formatted);
    },
    error(msg: string, ...args: unknown[]) {
      const formatted = formatMsg(msg, args);
      child.error(formatted);
      pushLog("ERROR", name, formatted);
    },
    debug(msg: string, ...args: unknown[]) {
      child.debug(formatMsg(msg, args));
    },
  };
}

function formatMsg(msg: string, args: unknown[]): string {
  if (args.length === 0) return msg;
  // Simple sprintf-like replacement for %s, %d
  let i = 0;
  return msg.replace(/%[sd]/g, () => {
    if (i < args.length) return String(args[i++]);
    return "%s";
  });
}

// ─── Flush to database ──────────────────────────────────────────────
async function flushToDb(): Promise<void> {
  if (buffer.length === 0) return;
  const batch = buffer.splice(0, buffer.length);
  try {
    await db.insert(logEntries).values(
      batch.map((r) => ({
        timestamp: r.timestamp,
        level: r.level,
        loggerName: r.loggerName,
        message: r.message,
        source: r.source,
      }))
    );
  } catch {
    // If DB write fails, records are lost — acceptable for logs
  }
}

async function pruneOldLogs(): Promise<void> {
  try {
    const [{ count }] = await db
      .select({ count: sql<number>`count(*)` })
      .from(logEntries);
    if (count > MAX_LOGS_IN_DB + PRUNE_BATCH_SIZE) {
      await db.execute(
        sql`DELETE FROM log_entries WHERE id NOT IN (SELECT id FROM log_entries ORDER BY timestamp DESC LIMIT ${MAX_LOGS_IN_DB})`
      );
    }
  } catch {
    // ignore
  }
}

// ─── Lifecycle ──────────────────────────────────────────────────────
export function setupLogging(src: string): void {
  source = src;
}

export function startFlushLoop(): void {
  flushTimer = setInterval(async () => {
    await flushToDb();
    pruneCounter++;
    if (pruneCounter >= 12) {
      pruneCounter = 0;
      await pruneOldLogs();
    }
  }, FLUSH_INTERVAL_MS);
}

export async function stopFlushLoop(): Promise<void> {
  if (flushTimer) {
    clearInterval(flushTimer);
    flushTimer = null;
  }
  await flushToDb();
}
