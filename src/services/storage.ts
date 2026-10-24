import {
  DeleteObjectCommand,
  GetObjectCommand,
  ListObjectsV2Command,
  PutObjectCommand,
  S3Client,
} from "@aws-sdk/client-s3";
import { settings } from "../config.js";

let client: S3Client | null = null;

function getClient(): S3Client {
  if (client) return client;
  const s = settings.storage;
  if (!s.endpoint || !s.bucket || !s.accessKeyId || !s.secretAccessKey) {
    throw new Error(
      "Object storage is not configured (STORAGE_ENDPOINT, STORAGE_BUCKET, STORAGE_ACCESS_KEY_ID, STORAGE_SECRET_ACCESS_KEY)"
    );
  }
  client = new S3Client({
    endpoint: s.endpoint,
    region: s.region,
    forcePathStyle: s.forcePathStyle,
    credentials: { accessKeyId: s.accessKeyId, secretAccessKey: s.secretAccessKey },
    requestChecksumCalculation: "WHEN_REQUIRED",
    responseChecksumValidation: "WHEN_REQUIRED",
  });
  return client;
}

export function publicUrl(key: string): string {
  const base = settings.storage.publicUrl;
  if (!base) throw new Error("STORAGE_PUBLIC_URL is not configured");
  return `${base}/${key.split("/").map(encodeURIComponent).join("/")}`;
}

export async function putObject(
  key: string,
  body: Buffer,
  contentType: string
): Promise<void> {
  await getClient().send(
    new PutObjectCommand({
      Bucket: settings.storage.bucket,
      Key: key,
      Body: body,
      ContentType: contentType,
      ContentLength: body.length,
      CacheControl: "public, max-age=31536000, immutable",
    })
  );
}

export async function getObject(key: string): Promise<Buffer> {
  const res = await getClient().send(
    new GetObjectCommand({ Bucket: settings.storage.bucket, Key: key })
  );
  if (!res.Body) throw new Error(`Object ${key} has no body`);
  return Buffer.from(await res.Body.transformToByteArray());
}

export async function deleteObjects(keys: string[]): Promise<void> {
  for (let i = 0; i < keys.length; i += 8) {
    await Promise.all(
      keys.slice(i, i + 8).map((Key) =>
        getClient().send(new DeleteObjectCommand({ Bucket: settings.storage.bucket, Key }))
      )
    );
  }
}

export async function deletePrefix(prefix: string): Promise<number> {
  let deleted = 0;
  let token: string | undefined;
  do {
    const res = await getClient().send(
      new ListObjectsV2Command({
        Bucket: settings.storage.bucket,
        Prefix: prefix,
        ContinuationToken: token,
      })
    );
    const keys = (res.Contents ?? []).map((o) => o.Key!).filter(Boolean);
    if (keys.length > 0) {
      await deleteObjects(keys);
      deleted += keys.length;
    }
    token = res.IsTruncated ? res.NextContinuationToken : undefined;
  } while (token);
  return deleted;
}
