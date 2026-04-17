import { drizzle } from "drizzle-orm/node-postgres";
import pg from "pg";
import { settings } from "./config.js";
import * as schema from "./schema.js";

const pool = new pg.Pool({
  connectionString: settings.databaseUrl,
});

export const db = drizzle(pool, { schema });
export type Db = typeof db;

export async function closePool() {
  await pool.end();
}
