import { createHmac, timingSafeEqual } from "node:crypto";
import { createRemoteJWKSet, jwtVerify } from "jose";
import { eq } from "drizzle-orm";
import type { FastifyRequest, FastifyReply } from "fastify";
import { settings } from "./config.js";
import { db } from "./database.js";
import { users, type User } from "./schema.js";

const JWKS = createRemoteJWKSet(
  new URL("https://shoo.dev/.well-known/jwks.json")
);

export const SESSION_COOKIE = "podcast_session";
export const SESSION_MAX_AGE = 30 * 24 * 60 * 60; // 30 days
export const REGISTER_COOKIE = "register_token";

export class RequiresLogin extends Error {
  nextUrl: string;
  constructor(nextUrl = "/") {
    super("Login required");
    this.nextUrl = nextUrl;
  }
}

export class RequiresRegistration extends Error {
  constructor() {
    super("Registration required");
  }
}

function getOrigin(url: string): string {
  const parsed = new URL(url);
  let origin = `${parsed.protocol}//${parsed.hostname}`;
  if (parsed.port && parsed.port !== "80" && parsed.port !== "443") {
    origin += `:${parsed.port}`;
  }
  return origin;
}

export async function verifyShooToken(
  idToken: string
): Promise<Record<string, unknown>> {
  const origin = getOrigin(settings.baseUrl);
  const { payload } = await jwtVerify(idToken, JWKS, {
    issuer: "https://shoo.dev",
    audience: `origin:${origin}`,
    algorithms: ["ES256"],
  });
  if (!payload.pairwise_sub) {
    throw new Error("Missing pairwise_sub claim");
  }
  return payload as Record<string, unknown>;
}

export function createSessionCookie(sub: string): string {
  const expires = Math.floor(Date.now() / 1000) + SESSION_MAX_AGE;
  const message = `${sub}:${expires}`;
  const sig = createHmac("sha256", settings.sessionSecret)
    .update(message)
    .digest("hex");
  return `${message}:${sig}`;
}

export function verifySessionCookie(cookie: string): string | null {
  try {
    const lastColon = cookie.lastIndexOf(":");
    if (lastColon === -1) return null;
    const secondLastColon = cookie.lastIndexOf(":", lastColon - 1);
    if (secondLastColon === -1) return null;

    const sub = cookie.slice(0, secondLastColon);
    const expiresStr = cookie.slice(secondLastColon + 1, lastColon);
    const sig = cookie.slice(lastColon + 1);

    const message = `${sub}:${expiresStr}`;
    const expectedSig = createHmac("sha256", settings.sessionSecret)
      .update(message)
      .digest("hex");

    if (
      !timingSafeEqual(Buffer.from(sig, "hex"), Buffer.from(expectedSig, "hex"))
    ) {
      return null;
    }
    if (parseInt(expiresStr, 10) < Math.floor(Date.now() / 1000)) {
      return null;
    }
    return sub;
  } catch {
    return null;
  }
}

export function getCurrentUser(request: FastifyRequest): string | null {
  const cookie = (request.cookies as Record<string, string | undefined>)?.[
    SESSION_COOKIE
  ];
  if (!cookie) return null;
  return verifySessionCookie(cookie);
}

export async function requireAuth(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<User> {
  const sub = getCurrentUser(request);
  if (!sub) {
    reply.code(401).send({ error: "Not authenticated" });
    throw new Error("Not authenticated");
  }
  const [user] = await db
    .select()
    .from(users)
    .where(eq(users.shooSub, sub))
    .limit(1);
  if (!user || !user.enabled) {
    reply.code(403).send({ error: "Not registered or account disabled" });
    throw new Error("Not registered");
  }
  // Attach user to request for downstream use
  (request as any).user = user;
  return user;
}

export async function requireAuthPage(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<User> {
  const sub = getCurrentUser(request);
  if (!sub) {
    throw new RequiresLogin(request.url);
  }
  const [user] = await db
    .select()
    .from(users)
    .where(eq(users.shooSub, sub))
    .limit(1);
  if (!user || !user.enabled) {
    throw new RequiresRegistration();
  }
  (request as any).user = user;
  return user;
}

export async function requireAdmin(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<User> {
  const user = await requireAuth(request, reply);
  if (!user.isAdmin) {
    reply.code(403).send({ error: "Admin access required" });
    throw new Error("Admin access required");
  }
  return user;
}

export async function requireAdminPage(
  request: FastifyRequest,
  reply: FastifyReply
): Promise<User> {
  const user = await requireAuthPage(request, reply);
  if (!user.isAdmin) {
    reply.code(403).send({ error: "Admin access required" });
    throw new Error("Admin access required");
  }
  return user;
}

export const cookieSecure = settings.baseUrl.startsWith("https://");

export function safeTokenCompare(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  return timingSafeEqual(Buffer.from(a), Buffer.from(b));
}
