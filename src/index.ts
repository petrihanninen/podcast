import Fastify from "fastify";
import fastifyCookie from "@fastify/cookie";
import fastifyFormbody from "@fastify/formbody";

import { settings } from "./config.js";
import { RequiresLogin, RequiresRegistration } from "./auth.js";
import { renderTemplate } from "./templates.js";
import { apiRoutes } from "./routes/api.js";
import { authRoutes } from "./routes/auth.js";
import { feedRoutes } from "./routes/feed.js";
import { pageRoutes } from "./routes/pages.js";

const app = Fastify({ logger: false, bodyLimit: 4_500_000 });

await app.register(fastifyCookie);
await app.register(fastifyFormbody);

app.addHook("onRequest", async (request, reply) => {
  if (["GET", "HEAD", "OPTIONS"].includes(request.method)) return;
  const origin = request.headers.origin;
  if (!origin) return;
  const expected = new URL(settings.baseUrl).origin;
  if (origin !== expected) {
    return reply.code(403).send({ error: "Forbidden" });
  }
});

app.setErrorHandler((error: any, request, reply) => {
  if (error instanceof RequiresLogin) {
    return reply.code(303).redirect(`/auth/login?next=${encodeURIComponent(error.nextUrl)}`);
  }
  if (error instanceof RequiresRegistration) {
    return reply.code(403).header("Content-Type", "text/html").send(renderTemplate("not_registered.html", {}));
  }
  if (!error.statusCode || error.statusCode >= 500) {
    console.error(`[web] ${request.method} ${request.url} failed:`, error);
  }
  reply.code(error.statusCode ?? 500).send({ error: error.message || "Internal Server Error" });
});

await app.register(authRoutes);
await app.register(apiRoutes);
await app.register(feedRoutes);
await app.register(pageRoutes);

await app.ready();

export default (req: any, res: any) => {
  app.server.emit("request", req, res);
};
