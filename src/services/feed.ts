import { eq, and, isNotNull } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, podcastSettings, type User } from "../schema.js";
import { settings } from "../config.js";

function escapeXml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function cdata(value: string): string {
  return `<![CDATA[${value.replace(/\]\]>/g, "]]]]><![CDATA[>")}]]>`;
}

function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${minutes}:${String(secs).padStart(2, "0")}`;
}

export async function generateFeed(user: User): Promise<string> {
  const [psettings] = await db
    .select()
    .from(podcastSettings)
    .where(eq(podcastSettings.userId, user.id))
    .limit(1);

  const ps = psettings ?? {
    title: "My Private Podcast",
    description: "AI-generated podcast episodes",
    author: "Podcast Bot",
    language: "en",
    imageUrl: null,
  };

  const base = settings.baseUrl.replace(/\/$/, "");
  const feedUrl = `${base}/feed/${user.feedToken}.xml`;
  const imageUrl = ps.imageUrl || `${base}/static/til.png`;

  const readyEpisodes = await db
    .select()
    .from(episodes)
    .where(
      and(
        eq(episodes.userId, user.id),
        eq(episodes.status, "ready"),
        isNotNull(episodes.audioUrl)
      )
    )
    .orderBy(episodes.publishedAt);

  const items = readyEpisodes
    .map((ep) => {
      const date = (ep.publishedAt ?? ep.createdAt).toUTCString();
      const lines = [
        `    <item>`,
        `      <title>${cdata(ep.title)}</title>`,
        `      <link>${escapeXml(`${base}/episodes/${ep.id}`)}</link>`,
        `      <guid isPermaLink="false">${escapeXml(ep.id)}</guid>`,
        `      <pubDate>${date}</pubDate>`,
        `      <description>${cdata(ep.description || ep.topic)}</description>`,
        `      <enclosure url="${escapeXml(ep.audioUrl!)}" length="${ep.audioSizeBytes ?? 0}" type="audio/mpeg"/>`,
        `      <itunes:author>${escapeXml(ps.author)}</itunes:author>`,
      ];
      if (ep.audioDurationSeconds) {
        lines.push(`      <itunes:duration>${formatDuration(ep.audioDurationSeconds)}</itunes:duration>`);
      }
      if (ep.episodeNumber) {
        lines.push(`      <itunes:episode>${ep.episodeNumber}</itunes:episode>`);
      }
      lines.push(`    </item>`);
      return lines.join("\n");
    })
    .join("\n");

  return `<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd" xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>${cdata(ps.title)}</title>
    <link>${escapeXml(base)}</link>
    <atom:link href="${escapeXml(feedUrl)}" rel="self" type="application/rss+xml"/>
    <description>${cdata(ps.description)}</description>
    <language>${escapeXml(ps.language)}</language>
    <generator>Podcast Generator</generator>
    <lastBuildDate>${new Date().toUTCString()}</lastBuildDate>
    <itunes:author>${escapeXml(ps.author)}</itunes:author>
    <itunes:image href="${escapeXml(imageUrl)}"/>
    <image>
      <url>${escapeXml(imageUrl)}</url>
      <title>${cdata(ps.title)}</title>
      <link>${escapeXml(base)}</link>
    </image>
${items}
  </channel>
</rss>
`;
}
