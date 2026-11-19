import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect } from "react";
import { AlertTriangle, CheckCheck, CloudRain, Info, ShieldAlert, Sprout, Timer, RotateCcw } from "lucide-react";
import { useAppData } from "@/lib/AppDataContext";
import { PageHeader } from "@/components/app/AppShell";
import { toast } from "sonner";
import {
  farmHasCoords, fetchFarmWeatherSnapshot, weatherRisk, cropHealthRisk, tasksThisWeek,
  severeWeatherAlert, alreadyRaisedToday,
} from "@/lib/farmWeather";

export const Route = createFileRoute("/_app/alerts")({
  head: () => ({
    meta: [
      { title: "Risk Alerts — KrishiMitra" },
      {
        name: "description",
        content:
          "Severity-ranked farm risk alerts: weather warnings, delay risks and crop health signals.",
      },
    ],
  }),
  component: AlertsPage,
});

const config = {
  critical: {
    icon: ShieldAlert,
    ring: "border-destructive/40",
    glow: "shadow-[0_0_36px_-12px_var(--color-destructive)]",
    chip: "bg-destructive/12 text-destructive ring-1 ring-destructive/30",
    icoBg: "bg-destructive/10 text-destructive ring-1 ring-destructive/25",
  },
  warning: {
    icon: AlertTriangle,
    ring: "border-warning/35",
    glow: "",
    chip: "bg-warning/12 text-warning ring-1 ring-warning/30",
    icoBg: "bg-warning/10 text-warning ring-1 ring-warning/25",
  },
  info: {
    icon: Info,
    ring: "border-cyan/25",
    glow: "",
    chip: "bg-cyan/12 text-cyan ring-1 ring-cyan/25",
    icoBg: "bg-cyan/10 text-cyan ring-1 ring-cyan/25",
  },
};

function AlertsPage() {
  const {
    token, activeFarm, farmAlerts: alerts = [], setAlerts, patchRecord, postScoped, fetchScoped,
    weatherSnapshot, setWeatherSnapshot, fetchDashboardData,
  } = useAppData();
  const [dismissed, setDismissed] = useState([]);
  const [isRestoring, setIsRestoring] = useState(false);

  const visibleAlerts = alerts.filter((a) => !dismissed.includes(a._id) && a.status !== "dismissed");
  const dismissedAlerts = alerts.filter((a) => dismissed.includes(a._id) || a.status === "dismissed");
  const criticalCount = visibleAlerts.filter((a) => a.severity === "critical").length;
  const warningCount = visibleAlerts.filter((a) => a.severity === "warning").length;

  // Live weather for this farm (shared with the dashboard and AI Mitra).
  const hasCoords = farmHasCoords(activeFarm);
  const [weatherState, setWeatherState] = useState("loading");
  useEffect(() => {
    if (!activeFarm || !token) return;
    if (!hasCoords) { setWeatherState("no-location"); return; }
    if (weatherSnapshot) { setWeatherState("ready"); return; }
    let cancelled = false;
    setWeatherState("loading");
    fetchFarmWeatherSnapshot(activeFarm, token)
      .then((snap) => { if (!cancelled) setWeatherSnapshot(snap); })
      .catch(() => { if (!cancelled) setWeatherState("unavailable"); });
    return () => { cancelled = true; };
  }, [activeFarm, token, hasCoords, weatherSnapshot, setWeatherSnapshot]);

  // Severe weather today raises an alert here too, not only on the Weather page.
  useEffect(() => {
    if (!weatherSnapshot || !activeFarm) return;
    const raised = severeWeatherAlert(weatherSnapshot, activeFarm.location?.address || activeFarm.name);
    if (!raised || alreadyRaisedToday(alerts, raised.title)) return;
    postScoped("/alerts", { category: "weather", ...raised }).then(() => fetchDashboardData?.());
  }, [weatherSnapshot, activeFarm]);

  // The farm's active crop plan, for this week's work.
  const [plan, setPlan] = useState(undefined); // undefined = loading, null = none
  const farmId = activeFarm?._id || activeFarm?.id || null;
  useEffect(() => {
    if (!farmId) { setPlan(null); return; }
    let cancelled = false;
    setPlan(undefined);
    fetchScoped("/crop-plans")
      .then((list) => {
        if (cancelled) return;
        const plans = Array.isArray(list) ? list : [];
        setPlan(plans.find((p) => p.status === "active") || null);
      })
      .catch(() => { if (!cancelled) setPlan(null); });
    return () => { cancelled = true; };
  }, [farmId, fetchScoped]);

  const openCount = (category) => visibleAlerts.filter((a) => a.category === category).length;

  // Every tile is worked out from real data; "—" when there is none.
  const unknown = (hint) => ({ level: "—", pct: 0, tone: "primary", hint });
  const weather = weatherRisk(weatherSnapshot, openCount("weather"));
  const weatherTile = weather || unknown(
    weatherState === "no-location" ? "Farm location not found on the map. Edit it on the Farms page."
      : weatherState === "unavailable" ? "Weather service unreachable right now."
      : "Loading today's weather…"
  );
  const weekTasks = tasksThisWeek(plan);
  const scheduleTile = plan === undefined
    ? unknown("Loading crop plan…")
    : !plan
      ? unknown("No active crop plan for this farm.")
      : {
          level: weekTasks.length ? `${weekTasks.length} ${weekTasks.length === 1 ? "task" : "tasks"}` : "None due",
          pct: Math.min(100, weekTasks.length * 20),
          tone: weekTasks.length ? "cyan" : "primary",
          hint: weekTasks.length
            ? `Next: ${weekTasks[0].title} (${new Date(`${String(weekTasks[0].date).slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short" })})`
            : `No ${plan.cropName || "crop plan"} tasks in the next 7 days.`,
        };
  const healthTile = cropHealthRisk(openCount("crop_health"));

  const riskCategories = [
    { icon: CloudRain, label: "Weather risk today", ...weatherTile },
    { icon: Timer, label: "Crop plan work this week", ...scheduleTile },
    { icon: Sprout, label: "Crop health", ...healthTile },
  ];

  // Persist dismissal as status: "dismissed" so it survives a refresh
  const handleDismiss = (id) => {
    setDismissed((prev) => [...prev, id]);
    setAlerts((prev) => prev.map((a) => (a._id === id ? { ...a, status: "dismissed" } : a)));
    patchRecord(`/alerts/${id}`, { status: "dismissed" }).catch(() => {
      toast.error("Couldn't save — this alert may reappear after refresh.");
    });
  };

  const handleMarkAllReviewed = () => {
    const ids = visibleAlerts.map((a) => a._id);
    if (ids.length === 0) return;
    setDismissed((prev) => [...prev, ...ids]);
    setAlerts((prev) => prev.map((a) => (ids.includes(a._id) ? { ...a, status: "dismissed" } : a)));
    Promise.all(ids.map((id) => patchRecord(`/alerts/${id}`, { status: "dismissed" }))).catch(() => {
      toast.error("Some alerts failed to save as reviewed.");
    });
  };

  // Restore all dismissed alerts back to status: "active" on server and in state
  const handleRestoreAlerts = async () => {
    if (dismissedAlerts.length === 0 || isRestoring) return;
    setIsRestoring(true);
    const idsToRestore = dismissedAlerts.map(a => a._id);
    setDismissed([]);
    setAlerts((prev) => prev.map((a) => (idsToRestore.includes(a._id) ? { ...a, status: "active" } : a)));

    try {
      await Promise.all(idsToRestore.map((id) => patchRecord(`/alerts/${id}`, { status: "active" })));
      toast.success(`Restored ${idsToRestore.length} alert${idsToRestore.length > 1 ? "s" : ""}`);
    } catch (err) {
      toast.error("Failed to restore some alerts on the server.");
    } finally {
      setIsRestoring(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Risk Alerts"
        subtitle={activeFarm
          ? `${criticalCount} critical · ${warningCount} warnings · monitored for ${activeFarm.name}`
          : "Add a farm to start risk monitoring"}
        action={
          <div className="flex flex-wrap items-center gap-2">
            {dismissedAlerts.length > 0 && (
              <button
                type="button"
                onClick={handleRestoreAlerts}
                disabled={isRestoring}
                className="glass flex items-center gap-1.5 rounded-xl border border-border px-3 sm:px-4 py-2 text-xs font-semibold text-muted-foreground hover:border-primary/40 hover:text-primary transition-colors cursor-pointer"
              >
                <RotateCcw className={`h-3.5 w-3.5 ${isRestoring ? "animate-spin" : ""}`} />
                <span>{isRestoring ? "Restoring..." : `Restore reviewed (${dismissedAlerts.length})`}</span>
              </button>
            )}
            {visibleAlerts.length > 0 && (
              <button
                type="button"
                onClick={handleMarkAllReviewed}
                className="glass flex items-center gap-1.5 rounded-xl px-3 sm:px-4 py-2 text-xs font-semibold transition-colors hover:border-primary/30 cursor-pointer"
              >
                <CheckCheck className="h-3.5 w-3.5 text-primary" /> Mark all reviewed
              </button>
            )}
          </div>
        }
      />

      {/* Risk radar */}
      <section className="mb-6 grid gap-4 sm:grid-cols-3">
        {riskCategories.map((r) => (
          <div key={r.label} className="glass hover-lift rounded-2xl p-5">
            <div className="flex items-center justify-between">
              <r.icon
                className={`h-5 w-5 ${r.tone === "warning" ? "text-warning" : r.tone === "cyan" ? "text-cyan" : "text-primary"}`}
              />
              <span
                className={`text-[10px] font-bold uppercase tracking-widest ${
                  r.tone === "warning" ? "text-warning" : r.tone === "cyan" ? "text-cyan" : "text-primary"
                }`}
              >
                {activeFarm ? r.level : "—"}
              </span>
            </div>
            <div className="mt-3 text-xs font-medium">{r.label}</div>
            <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-secondary">
              <div
                className={`h-full rounded-full ${
                  r.tone === "warning"
                    ? "bg-gradient-to-r from-warning to-destructive/70"
                    : r.tone === "cyan"
                      ? "bg-gradient-to-r from-cyan to-cyan/40"
                      : "bg-gradient-to-r from-primary to-primary/50"
                }`}
                style={{ width: `${r.pct}%` }}
              />
            </div>
            {activeFarm && r.hint && (
              <p className="mt-2 text-[11px] leading-snug text-muted-foreground">{r.hint}</p>
            )}
          </div>
        ))}
      </section>

      {/* Alert cards */}
      {visibleAlerts.length === 0 ? (
        <div className="glass grid place-items-center rounded-2xl p-8 sm:p-12 text-center">
          {dismissedAlerts.length > 0 ? (
            <>
              <CheckCheck className="h-8 w-8 text-primary" />
              <div className="mt-3 text-base font-semibold">All active alerts reviewed</div>
              <p className="mt-1 text-xs text-muted-foreground max-w-sm leading-relaxed">
                You have reviewed and dismissed {dismissedAlerts.length} alert{dismissedAlerts.length > 1 ? "s" : ""}. You can restore them anytime to inspect their history and recommendations.
              </p>
              <button
                type="button"
                onClick={handleRestoreAlerts}
                disabled={isRestoring}
                className="mt-4 flex items-center gap-1.5 rounded-xl border border-primary/40 bg-primary/10 px-4 py-2 text-xs font-semibold text-primary hover:bg-primary/20 transition-colors cursor-pointer"
              >
                <RotateCcw className={`h-3.5 w-3.5 ${isRestoring ? "animate-spin" : ""}`} />
                <span>{isRestoring ? "Restoring..." : `Restore ${dismissedAlerts.length} reviewed alert${dismissedAlerts.length > 1 ? "s" : ""}`}</span>
              </button>
            </>
          ) : (
            <>
              <ShieldAlert className="h-8 w-8 text-primary" />
              <div className="mt-3 text-base font-semibold">{activeFarm ? "All clear — no active alerts" : "No farm to monitor yet"}</div>
              <p className="mt-1 text-xs text-muted-foreground max-w-sm leading-relaxed">
                {activeFarm
                  ? "KrishiMitra checks weather changes, crop growth milestones and farm schedules. New alerts appear here when risk conditions are detected."
                  : "Add your farm with its location, and weather and schedule alerts for it will appear here."}
              </p>
            </>
          )}
        </div>
      ) : (
        <div className="space-y-3.5">
          {visibleAlerts.map((a) => {
            const c = config[a.severity] || config.info;
            return (
              <div key={a._id} className={`glass rounded-2xl border p-5 ${c.ring} ${c.glow}`}>
                <div className="flex flex-wrap items-start gap-4">
                  <div className={`grid h-11 w-11 shrink-0 place-items-center rounded-xl ${c.icoBg}`}>
                    <c.icon className="h-5 w-5" />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="font-display text-sm font-semibold">{a.title}</h3>
                      <span className={`rounded-full px-2.5 py-0.5 text-[9px] font-bold uppercase tracking-widest ${c.chip}`}>
                        {a.severity}
                      </span>
                    </div>
                    <p className="mt-1.5 max-w-2xl text-xs leading-relaxed text-muted-foreground">
                      {a.detail || a.message}
                    </p>
                    <div className="mt-2.5 flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
                      <span>{a.source || "System"}</span>
                      <span>·</span>
                      <span>{a.createdAt ? new Date(a.createdAt).toLocaleDateString() : ""}</span>
                    </div>
                  </div>
                  <div className="flex shrink-0 gap-2">
                    <button className="rounded-lg bg-primary px-3.5 py-1.5 text-[11px] font-semibold text-primary-foreground transition-transform hover:scale-[1.03]">
                      Take action
                    </button>
                    <button
                      onClick={() => handleDismiss(a._id)}
                      className="rounded-lg border border-border px-3.5 py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
                    >
                      Dismiss
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

    </div>
  );
}
