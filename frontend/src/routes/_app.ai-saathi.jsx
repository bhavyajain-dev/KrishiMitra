import { createFileRoute, redirect } from "@tanstack/react-router";

/**
 * Backward-compatible redirect route for legacy /ai-saathi URLs and bookmarks.
 * Automatically forwards to canonical /ai-mitra while preserving all query parameters.
 */
export const Route = createFileRoute("/_app/ai-saathi")({
  beforeLoad: ({ search }) => {
    throw redirect({
      to: "/ai-mitra",
      search,
    });
  },
  component: () => null,
});
