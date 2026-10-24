import { drizzle } from "drizzle-orm/node-postgres";
import pg from "pg";
import { attachDatabasePool } from "@vercel/functions";
import { settings } from "./config.js";
import * as schema from "./schema.js";

const pool = new pg.Pool({
  connectionString: settings.databaseUrl,
  max: 5,
});

if (process.env.VERCEL) {
  attachDatabasePool(pool);
}

export const db = drizzle(pool, { schema });
export type Db = typeof db;

export async function closePool() {
  await pool.end();
}
