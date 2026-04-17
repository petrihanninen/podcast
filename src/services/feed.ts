import { Feed } from "feed";
import { eq, and, isNotNull } from "drizzle-orm";
import { db } from "../database.js";
import { episodes, podcastSettings, type User } from "../schema.js";
import { settings } from "../config.js";

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
  const imageUrl = ps.imageUrl || `${base}/static/til.png`;

  const feed = new Feed({
    title: ps.title,
    description: ps.description,
    id: `${base}/feed/${user.feedToken}.xml`,
    link: base,
    language: ps.language,
    generator: "Podcast Generator",
    image: imageUrl,
    copyright: "",
    author: { name: ps.author },
  });

  // Fetch ready episodes
  const readyEpisodes = await db
    .select()
    .from(episodes)
    .where(
      and(
        eq(episodes.userId, user.id),
        eq(episodes.status, "ready"),
        isNotNull(episodes.audioFilename)
      )
    )
    .orderBy(episodes.publishedAt);

  for (const ep of readyEpisodes) {
    const audioUrl = `${base}/audio/${user.id}/${ep.audioFilename}`;
    feed.addItem({
      title: ep.title,
      id: ep.id,
      link: `${base}/episodes/${ep.id}`,
      description: ep.description || ep.topic,
      date: ep.publishedAt ?? ep.createdAt,
      enclosure: {
        url: audioUrl,
        length: ep.audioSizeBytes ?? 0,
        type: "audio/mpeg",
      },
      extensions: [
        {
          name: "_itunes",
          objects: {
            author: ps.author,
            ...(ep.audioDurationSeconds
              ? { duration: formatDuration(ep.audioDurationSeconds) }
              : {}),
            ...(ep.episodeNumber ? { episode: String(ep.episodeNumber) } : {}),
          },
        },
      ],
    });
  }

  return feed.rss2();
}
