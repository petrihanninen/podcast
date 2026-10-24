import { defineConfig } from "nitro";
import type { ModuleOptions as WorkflowOptions } from "workflow/nitro";

const workflow: WorkflowOptions = { runtime: "nodejs24.x" };

export default defineConfig({
  modules: ["workflow/nitro"],
  routes: {
    "/**": { handler: "./src/index.ts", format: "node" },
  },
  vercel: {
    entryFormat: "node",
    functions: { maxDuration: 300 },
  },
  ...({ workflow } as object),
});
