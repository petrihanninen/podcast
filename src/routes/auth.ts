import fs from "node:fs";
import path from "node:path";
import { URL } from "node:url";
import type { FastifyInstance, FastifyRequest, FastifyReply } from "fastify";
import { eq, sql } from "drizzle-orm";
import crypto from "node:crypto";
import { db } from "../database.js";
import { users, podcastSettings } from "../schema.js";
import { settings } from "../config.js";
import {
  REGISTER_COOKIE,
  SESSION_COOKIE,
  SESSION_MAX_AGE,
  cookieSecure,
  createSessionCookie,
  getCurrentUser,
  verifyShooToken,
} from "../auth.js";
import { createLogger } from "../log-handler.js";
import { renderTemplate } from "../server.js";

const log = createLogger("auth-routes");

function safeRedirectUrl(nextUrl: string): string {
  try {
    const parsed = new URL(nextUrl, "http://localhost");
    if (parsed.hostname !== "localhost") return "/";
  } catch {
    return "/";
  }
  if (nextUrl.startsWith("//")) return "/";
  return nextUrl;
}

function setCookie(
  reply: FastifyReply,
  name: string,
  value: string,
  maxAge: number
) {
  reply.setCookie(name, value, {
    maxAge,
    httpOnly: true,
    sameSite: "lax",
    secure: cookieSecure,
    path: "/",
  });
}

export async function authRoutes(app: FastifyInstance) {
  // GET /auth/login
  app.get<{ Querystring: { next?: string } }>(
    "/auth/login",
    async (request, reply) => {
      const next = safeRedirectUrl(request.query.next || "/");
      const user = getCurrentUser(request);
      if (user) {
        return reply.code(303).redirect(next);
      }
      return reply
        .header("Content-Type", "text/html")
        .send(renderTemplate("login.html", { next_url: next }));
    }
  );

  // GET /auth/register
  app.get<{ Querystring: { token?: string } }>(
    "/auth/register",
    async (request, reply) => {
      const token = request.query.token || "";
      if (
        !token ||
        !settings.registerToken ||
        token !== settings.registerToken
      ) {
        return reply
          .code(403)
          .header("Content-Type", "text/html")
          .send(renderTemplate("invalid_invite.html", {}));
      }
      setCookie(reply, REGISTER_COOKIE, token, 3600);
      return reply.code(303).redirect("/auth/login");
    }
  );

  // POST /auth/verify
  app.post("/auth/verify", async (request, reply) => {
    const body = request.body as { token?: string } | null;
    const token = body?.token;
    if (!token) {
      return reply.code(400).send({ error: "Missing token" });
    }

    let claims: Record<string, unknown>;
    try {
      claims = await verifyShooToken(token);
    } catch (e: any) {
      log.warn("Token verification failed: %s", e.message);
      return reply.code(401).send({ error: `Invalid token: ${e.message}` });
    }

    const sub = claims.pairwise_sub as string;
    const email = (claims.email as string) || null;

    // Look up existing user
    const [user] = await db
      .select()
      .from(users)
      .where(eq(users.shooSub, sub))
      .limit(1);

    if (user) {
      if (!user.enabled) {
        return reply.code(403).send({ error: "Account disabled" });
      }
      // Update email if changed
      if (email && user.email !== email) {
        await db
          .update(users)
          .set({ email })
          .where(eq(users.id, user.id));
      }
      const cookieValue = createSessionCookie(sub);
      setCookie(reply, SESSION_COOKIE, cookieValue, SESSION_MAX_AGE);
      return reply.send({ ok: true, sub });
    }

    // Check for registration token cookie
    const registerToken = (request.cookies as Record<string, string>)?.[
      REGISTER_COOKIE
    ];
    if (
      registerToken &&
      settings.registerToken &&
      registerToken === settings.registerToken
    ) {
      try {
        // Check if first user (becomes admin)
        const [{ count }] = await db
          .select({ count: sql<number>`count(*)` })
          .from(users);
        const isFirstUser = count === 0;

        const feedToken = crypto.randomBytes(32).toString("base64url");

        const [newUser] = await db
          .insert(users)
          .values({
            shooSub: sub,
            email,
            feedToken,
            isAdmin: isFirstUser,
          })
          .returning();

        // Create default podcast settings
        await db.insert(podcastSettings).values({ userId: newUser.id });

        // Create user's audio directory
        const userAudioDir = path.join(settings.audioDir, newUser.id);
        fs.mkdirSync(userAudioDir, { recursive: true });

        log.info("Registered new user: sub=%s, admin=%s", sub, isFirstUser);

        const cookieValue = createSessionCookie(sub);
        setCookie(reply, SESSION_COOKIE, cookieValue, SESSION_MAX_AGE);
        reply.clearCookie(REGISTER_COOKIE, { path: "/" });
        return reply.send({ ok: true, sub, registered: true });
      } catch (e: any) {
        // Race condition: user was created between check and insert
        if (e.code === "23505") {
          log.info("User already registered (race condition): sub=%s", sub);
          const cookieValue = createSessionCookie(sub);
          setCookie(reply, SESSION_COOKIE, cookieValue, SESSION_MAX_AGE);
          return reply.send({ ok: true, sub });
        }
        throw e;
      }
    }

    // Not registered and no valid invite — set session anyway
    const cookieValue = createSessionCookie(sub);
    setCookie(reply, SESSION_COOKIE, cookieValue, SESSION_MAX_AGE);
    return reply.send({ ok: true, sub });
  });

  // POST /auth/logout
  app.post("/auth/logout", async (_request, reply) => {
    reply.clearCookie(SESSION_COOKIE, { path: "/" });
    return reply.code(303).redirect("/");
  });
}
