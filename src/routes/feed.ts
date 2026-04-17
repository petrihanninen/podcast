import type { FastifyInstance } from "fastify";
import { eq, and } from "drizzle-orm";
import { db } from "../database.js";
import { users } from "../schema.js";
import { generateFeed } from "../services/feed.js";

export async function feedRoutes(app: FastifyInstance) {
  app.get<{ Params: { feedToken: string } }>(
    "/feed/:feedToken.xml",
    async (request, reply) => {
      const { feedToken } = request.params;
      const [user] = await db
        .select()
        .from(users)
        .where(and(eq(users.feedToken, feedToken), eq(users.enabled, true)))
        .limit(1);

      if (!user) {
        return reply.code(404).send({ error: "Feed not found" });
      }

      const xml = await generateFeed(user);
      return reply
        .header("Content-Type", "application/rss+xml; charset=utf-8")
        .send(xml);
    }
  );
}
