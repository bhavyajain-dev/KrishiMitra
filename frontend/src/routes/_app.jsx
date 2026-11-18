import { Outlet, createFileRoute, redirect } from "@tanstack/react-router";
import { AppShell } from "@/components/app/AppShell";

export const Route = createFileRoute("/_app")({
  // Signed-in pages depend on the user's data (farm, location) and today's
  // date, so a page pre-built at deploy time can never match what the
  // browser renders; React then logs hydration error #418. Render this whole
  // section in the browser only. Public pages (landing, sign-in) stay
  // pre-rendered.
  ssr: false,
  pendingComponent: AppLoading,
  beforeLoad: () => {
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("krishimitra_token");
      if (!token) {
        throw redirect({ to: "/auth" });
      }
    }
  },
  component: AppLayout,
});

function AppLoading() {
  return (
    <div className="grid min-h-screen place-items-center bg-background">
      <div className="flex flex-col items-center gap-3 text-sm text-muted-foreground">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-primary/30 border-t-primary" />
        Loading KrishiMitra…
      </div>
    </div>
  );
}

function AppLayout() {
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}
