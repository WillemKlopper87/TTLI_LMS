import { getPublicEpisodes } from "@/lib/server-api";

import { EpisodeDetail } from "./episode-detail";

/**
 * Thin server wrapper around the client-rendered episode player
 * (episode-detail.tsx — split out so this route can export
 * `generateMetadata`, which a "use client" file can't). The list
 * endpoint already carries title/description, so no new API call is
 * needed just to fill in a page title.
 */
export async function generateMetadata({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  const episodes = await getPublicEpisodes();
  const episode = episodes.find((e) => e.slug === slug);
  if (!episode) return { title: "Episode" };
  return {
    title: episode.title,
    description: episode.description ?? undefined,
    alternates: { canonical: `/podcasts/${episode.slug}` },
  };
}

export default function PodcastEpisodePage() {
  return <EpisodeDetail />;
}
