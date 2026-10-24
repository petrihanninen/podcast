import nunjucks from "nunjucks";
import { templates } from "./generated/templates.js";
import {
  buildPipelineInfo,
  formatDuration,
  formatFileSize,
  getCurrentStepIndex,
  getTtsProgress,
  statusLabel,
} from "./view-helpers.js";

class BundledLoader extends nunjucks.Loader {
  getSource(name: string) {
    const src = templates[name];
    if (src === undefined) throw new Error(`Template not found: ${name}`);
    return { src, path: name, noCache: false };
  }
}

const env = new nunjucks.Environment(new BundledLoader(), { autoescape: true });

env.addGlobal("status_label", statusLabel);
env.addGlobal("format_duration", formatDuration);
env.addGlobal("format_file_size", formatFileSize);
env.addGlobal("build_pipeline_info", buildPipelineInfo);
env.addGlobal("get_current_step_index", getCurrentStepIndex);
env.addGlobal("get_tts_progress", getTtsProgress);

env.addFilter("from_json", (value: string) => {
  try {
    return JSON.parse(value);
  } catch {
    return [];
  }
});
env.addFilter("tojson", (value: unknown) =>
  new nunjucks.runtime.SafeString(
    (JSON.stringify(value ?? null) ?? "null")
      .replace(/</g, "\\u003c")
      .replace(/>/g, "\\u003e")
      .replace(/&/g, "\\u0026")
      .replace(/'/g, "\\u0027")
  )
);
env.addFilter("money", (value: number | null | undefined) => `$${Number(value ?? 0).toFixed(4)}`);
env.addFilter("fixed", (value: number | null | undefined, digits = 1) =>
  Number(value ?? 0).toFixed(digits)
);
env.addFilter("intcomma", (value: number | null | undefined) =>
  Math.round(Number(value ?? 0)).toLocaleString("en-US")
);
env.addFilter("mmss", (value: number | null | undefined) => {
  const total = Math.floor(Number(value ?? 0));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
});

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
env.addFilter("date", (value: Date | string | null, fmt: string) => {
  if (!value) return "";
  const d = typeof value === "string" ? new Date(value) : value;
  if (isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return fmt
    .replace("%b", MONTHS[d.getMonth()])
    .replace("%d", String(d.getDate()))
    .replace("%Y", String(d.getFullYear()))
    .replace("%H", pad(d.getHours()))
    .replace("%M", pad(d.getMinutes()));
});

export function renderTemplate(name: string, context: Record<string, unknown>): string {
  return env.render(name, context);
}
