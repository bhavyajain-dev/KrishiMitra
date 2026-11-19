import { API_URL } from "@/lib/api";
import { fetchFarmWeatherSnapshot, farmHasCoords as hasCoords } from "@/lib/farmWeather";
import { currentSeason } from "@/lib/season";
import { Link, createFileRoute } from "@tanstack/react-router";
import {
  ArrowRight,
  ArrowUpRight,
  CloudSun,
  Droplets,
  LineChart,
  MapPinned,
  Sparkles,
  Sun,
  Wallet,
  Wind,
} from "lucide-react";
import { useState, useEffect } from "react";
import { useAppData } from "@/lib/AppDataContext";

export const Route = createFileRoute("/_app/dashboard")({
  head: () => ({
    meta: [
      { title: "Dashboard — KrishiMitra" },
      {
        name: "description",
        content:
          "Your farm at a glance: weather, tasks, crop plan progress, risk alerts and expenses.",
      },
    ],
  }),
  component: Dashboard,
});

const severityStyles = {
  critical: "border-destructive/40 bg-destructive/8 text-destructive",
  warning: "border-warning/40 bg-warning/8 text-warning",
  info: "border-cyan/30 bg-cyan/8 text-cyan",
};


function Dashboard() {
  const { token, userProfile, farms, activeFarm, weatherSnapshot, setWeatherSnapshot, fetchScoped, openFarmAlerts: alerts = [] } = useAppData();

  const [cropPlan, setCropPlan] = useState(null);

  // The viewing farm's active crop plan. Cleared on every farm switch so a
  // farm without a plan never shows the previous farm's plan.
  useEffect(() => {
    let cancelled = false;
    setCropPlan(null);
    if (!activeFarm) return;
    fetchScoped("/crop-plans")
      .then((plans) => {
        if (cancelled || !Array.isArray(plans)) return;
        setCropPlan(plans.find((p) => p.status === "active") || null);
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [activeFarm, fetchScoped]);

  const cropIntro = (() => {
    if (cropPlan?.cropName) {
      const sow = cropPlan.sowingDate ? new Date(cropPlan.sowingDate) : null;
      const day = sow ? Math.floor((Date.now() - sow.getTime()) / 86400000) + 1 : null;
      if (sow && day < 1) {
        return `has ${cropPlan.cropName} planned, sowing on ${sow.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}. Get the field ready.`;
      }
      return `has ${cropPlan.cropName} growing${day ? ` (day ${day})` : ""}. Stay on top of today's tasks to keep the season on track.`;
    }
    if (activeFarm?.currentCrop) {
      return `has ${activeFarm.currentCrop} growing. Make a crop plan to get a day-by-day schedule.`;
    }
    return "has no active crop yet. Get crop recommendations or make a crop plan to start the season.";
  })();

  // Pre-load weather from the backend DB cache on mount so the weather widget
  // shows real data even without the user ever visiting the Weather page.
  // "loading" | "ready" | "no-location" (address not found on the map) |
  // "unavailable" (forecast service could not be reached).
  const [weatherStatus, setWeatherStatus] = useState("loading");
  const farmHasCoords = hasCoords(activeFarm);
  useEffect(() => {
    if (weatherSnapshot) { setWeatherStatus("ready"); return; }
    if (!token || !activeFarm) return;
    if (!farmHasCoords) { setWeatherStatus("no-location"); return; }
    setWeatherStatus("loading");
    let cancelled = false;

    const locationKey = activeFarm.location.address
      .toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");

    const fetchLiveWeather = async () => {
      try {
        const snap = await fetchFarmWeatherSnapshot(activeFarm, token);
        if (!cancelled) setWeatherSnapshot(snap);
        // Not saved to the shared weather cache: that cache holds the Weather
        // page's format, and writing the raw API format here broke that page.
      } catch (e) { if (!cancelled) setWeatherStatus("unavailable"); }
    };

    fetch(`${API_URL}/weather/cache/${locationKey}?query=${encodeURIComponent(activeFarm.location.address)}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.ok ? r.json() : null)
      .then(cached => {
        if (cancelled) return;
        // Use the cache only if it's in the Weather page's format.
        const near = (a, b) => a == null || b == null || Math.abs(Number(a) - Number(b)) < 0.05;
        if (cached?.data?.current && cached.data.current.temp != null && Array.isArray(cached.data.daily) &&
            near(cached.lat, activeFarm.location.lat) && near(cached.lon, activeFarm.location.lon)) {
          setWeatherSnapshot({
            temp: cached.data.current.temp,
            humidity: cached.data.current.humidity,
            wind: cached.data.current.wind,
            uv: cached.data.current.uv,
            rainChance: cached.data.current.rainChance,
            todayRainMm: cached.data.current.precipitation,
            condition: null,
            cityName: cached.cityName,
            alerts: cached.data.alerts || [],
          });
        } else {
          // If cache miss, fetch live
          fetchLiveWeather();
        }
      })
      .catch(() => { if (!cancelled) fetchLiveWeather(); });
    return () => { cancelled = true; };
  }, [token, activeFarm, weatherSnapshot, farmHasCoords, setWeatherSnapshot]);

  const totalArea = farms.reduce((s, f) => s + (f.areaAcres || 0), 0);
  // This season's spend on the farm being viewed (real expenses only).
  const [seasonSpend, setSeasonSpend] = useState(null);
  const viewingFarmId = activeFarm?._id || activeFarm?.id || null;
  useEffect(() => {
    if (!viewingFarmId) { setSeasonSpend(null); return; }
    let cancelled = false;
    fetchScoped("/expenses")
      .then((list) => {
        if (cancelled || !Array.isArray(list)) return;
        setSeasonSpend(list.reduce((sum, e) => sum + (Number(e.amountRs) || 0), 0));
      })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [viewingFarmId, fetchScoped]);
  const firstName = userProfile?.name?.split(" ")[0] || "Farmer";
  const today = new Date().toLocaleDateString("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  // Compute real crop plan progress based on dates
  // Stages in date order; the current one is the latest that has started.
  const stageTime = (s) => (s?.plannedDate ? new Date(`${String(s.plannedDate).slice(0, 10)}T00:00:00`).getTime() : NaN);
  const stages = [...(cropPlan?.milestones || [])].sort((a, b) => (stageTime(a) || 0) - (stageTime(b) || 0));
  const nowMs = Date.now();
  let currentIdx = -1;
  stages.forEach((s, i) => { if (stageTime(s) <= nowMs) currentIdx = i; });
  const stagePhase = (i) => (stages[i]?.status === "done" ? "done" : i === currentIdx ? "current" : i < currentIdx ? "passed" : "upcoming");
  const shownStages = stages.slice(Math.max(0, Math.min(currentIdx - 1, stages.length - 5)), Math.max(0, Math.min(currentIdx - 1, stages.length - 5)) + 5);
  const doneStages = stages.filter(s => s.status === "done").length;
  let cropProgress = 0;
  let cropProgressHint = "No active crop plan";
  
  if (cropPlan?.sowingDate && cropPlan?.expectedHarvestDate) {
    const todayDate = new Date();
    const sowing = new Date(cropPlan.sowingDate);
    const harvest = new Date(cropPlan.expectedHarvestDate);
    
    const durationDays = Math.max(1, Math.round((harvest - sowing) / (1000 * 60 * 60 * 24)));
    const elapsedDays = Math.max(0, Math.round((todayDate - sowing) / (1000 * 60 * 60 * 24)));
    
    cropProgress = Math.min(100, Math.round((elapsedDays / durationDays) * 100));
    
    const activeStage = elapsedDays > 0 ? stages[currentIdx] : null;
    cropProgressHint = sowing > todayDate
      ? `Sowing on ${sowing.toLocaleDateString("en-IN", { day: "numeric", month: "short" })}`
      : activeStage ? `${activeStage.stage} · Day ${elapsedDays} of ${durationDays}` : `Day ${elapsedDays} of ${durationDays}`;
  } else if (stages.length > 0) {
    cropProgress = Math.round((doneStages / stages.length) * 100);
    const activeStage = stages.find(s => s.status === "in-progress" || s.status === "pending");
    cropProgressHint = activeStage ? `${activeStage.stage} · Stage ${doneStages + 1} of ${stages.length}` : `${doneStages} of ${stages.length} stages done`;
  }


  // Only give weather-based advice when there is real weather data. Before,
  // a missing forecast counted as 0% rain and the card advised spraying.
  const hasWeather = weatherSnapshot?.rainChance != null;
  const rainChance = weatherSnapshot?.rainChance ?? 0;
  const humidity = weatherSnapshot?.humidity ?? 0;

  // Fallback to static rules if the backend didn't generate any AI alerts
  const staticAdvisories = [
    !hasWeather
      ? {
          title: "Weather-based advice",
          body: !activeFarm
            ? "Add a farm with its location to get spraying and irrigation advice based on live weather."
            : weatherStatus === "no-location"
            ? `We couldn't find "${activeFarm.location?.address || "your farm"}" on the map, so there is no forecast. Edit the farm's location on the Farms page to get spraying and irrigation advice.`
            : weatherStatus === "unavailable"
            ? "The weather service could not be reached just now. Open the Weather page or try again in a few minutes."
            : "Loading live weather for your farm. Spraying and irrigation timing will appear here.",
          tone: "text-muted-foreground",
        }
      : rainChance > 60
      ? { title: "Rain alert: delay spraying", body: `Rain probability is ${rainChance}%. Avoid spraying operations until dry weather returns to ensure full crop absorption.`, tone: "text-warning" }
      : { title: "Good spraying window ahead", body: `Rain chance is only ${rainChance}%. This is a good window for micronutrient or pesticide spraying operations.`, tone: "text-primary" },
    humidity > 80
      ? { title: "High humidity risk", body: `Humidity at ${humidity}% — ideal conditions for fungal disease. Inspect leaves and consider preventive fungicide application.`, tone: "text-warning" }
      : { title: "Irrigation efficiency tip", body: `${activeFarm ? `${activeFarm.name}: i` : "I"}rrigate in the early morning, when less water is lost to evaporation than in the heat of the day.`, tone: "text-cyan" },
    { title: "Market timing signal", body: "Check the Market Prices page for today's Mandi rates and compare with your expected harvest value to plan selling strategy.", tone: "text-primary" },
  ];

  const dynamicAlerts = weatherSnapshot?.alerts?.map(alert => ({
    title: alert.type === "critical" ? "Critical Weather Alert" : "Weather Advisory",
    body: alert.message,
    tone: alert.type === "critical" ? "text-destructive" : (alert.type === "warning" ? "text-warning" : "text-cyan")
  })) || [];

  const aiAdvisories = dynamicAlerts.length > 0 ? dynamicAlerts : staticAdvisories;

  return (
    <div className="space-y-5">
      {/* Welcome band */}
      <section className="glass-strong hero-ambient relative overflow-hidden rounded-3xl p-6 sm:p-8">
        <div className="grid-pattern pointer-events-none absolute inset-0" />
        <div className="relative grid gap-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
          <div className="min-w-0">
            <div className="text-xs font-medium uppercase tracking-[0.18em] text-primary">
              {today}
            </div>
            <h1 className="mt-2 font-display text-2xl font-bold tracking-tight sm:text-3xl">
              Good {new Date().getHours() < 12 ? "morning" : new Date().getHours() < 17 ? "afternoon" : "evening"}, {firstName}
            </h1>
            <p className="mt-2 max-w-lg text-sm text-muted-foreground">
              {activeFarm
                ? <><span className="font-semibold text-foreground">{activeFarm.name}</span> {cropIntro}</>
                : "Welcome back! Add your first farm to get started with your personalized dashboard."}
            </p>
            <div className="mt-5 flex flex-wrap gap-2.5">
              <Link
                to="/recommendations"
                className="glass flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-semibold transition-colors hover:border-primary/30"
              >
                <Sparkles className="h-3.5 w-3.5 text-primary" /> AI recommendations
              </Link>
            </div>
          </div>

          {/* Weather widget */}
          <div className="glass w-full rounded-2xl p-5 lg:w-72">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] uppercase tracking-widest text-muted-foreground">
                  {activeFarm?.location?.address || "Your Farm"} · Now
                </div>
                <div className="mt-1 flex items-end gap-1">
                  <span className="font-display text-4xl font-bold">{weatherSnapshot?.temp ?? "--"}°</span>
                  <span className="mb-1.5 text-xs text-muted-foreground">
                    {weatherSnapshot?.condition ||
                      (weatherStatus === "no-location" ? "Location not on map"
                        : weatherStatus === "unavailable" ? "Forecast unavailable"
                        : weatherStatus === "loading" && activeFarm ? "Loading…" : "")}
                  </span>
                </div>
              </div>
              <CloudSun className="h-10 w-10 text-warning float-slow" />
            </div>
            <div className="mt-4 grid grid-cols-3 gap-2 text-center">
              {[
                [Droplets, `${weatherSnapshot?.humidity ?? "--"}%`, "Humidity"],
                [Wind, `${weatherSnapshot?.wind ?? "--"} km/h`, "Wind"],
                [Sun, `UV ${weatherSnapshot?.uv ?? "--"}`, "UV Index"],
              ].map(([Icon, v, l]) => (
                <div key={l} className="rounded-xl bg-secondary/50 py-2">
                  <Icon className="mx-auto h-3.5 w-3.5 text-cyan" />
                  <div className="mt-1 text-xs font-semibold">{v}</div>
                  <div className="text-[10px] text-muted-foreground">{l}</div>
                </div>
              ))}
            </div>
            {activeFarm ? (
              <Link
                to="/weather"
                className="mt-3 flex items-center justify-center gap-1 text-[11px] font-medium text-cyan hover:underline"
              >
                7-day forecast <ArrowUpRight className="h-3 w-3" />
              </Link>
            ) : (
              <Link
                to="/farms"
                className="mt-3 flex items-center justify-center gap-1 text-[11px] font-medium text-cyan hover:underline"
              >
                Add a farm to see your local weather <ArrowUpRight className="h-3 w-3" />
              </Link>
            )}
          </div>
        </div>
      </section>

      {/* Stat cards */}
      <section className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard to="/farms" label="Total farms" value={String(farms.length)} hint={farms.length ? `${totalArea.toFixed(1)} acres in total` : "Add your first farm"} tone="primary" bar={farms.length > 0 ? 100 : 0} />
        <StatCard to="/crop-plan" label="Crop plan progress" value={`${cropProgress}%`} hint={cropPlan?.cropName ? `${cropPlan.cropName} · ${cropProgressHint}` : cropProgressHint} tone="cyan" bar={cropProgress} />
        <StatCard to="/alerts" label="Risk alerts" value={String(alerts.length)} hint={alerts.length > 0 ? `${alerts.filter(a => a.severity === "critical").length} critical` : "No alerts"} tone="warning" />
        <StatCard
          to="/expenses"
          label="Season spend"
          value={seasonSpend == null ? "—" : `₹${seasonSpend.toLocaleString("en-IN", { maximumFractionDigits: 2 })}`}
          hint={activeFarm ? `${activeFarm.name} · ${currentSeason().label}` : "Add a farm to track expenses"}
          tone="foreground"
        />
      </section>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Quick links */}
        <section className={`glass rounded-2xl p-5 ${alerts.length > 0 ? "lg:col-span-2" : "lg:col-span-3"}`}>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-sm font-semibold">Quick actions</h2>
          </div>
          <div className={`grid gap-3 sm:grid-cols-2 ${alerts.length > 0 ? "" : "lg:grid-cols-4"}`}>
            {[
              { to: "/expenses", label: "Expense Tracker", sub: "Log farm expenses", icon: Wallet },
              { to: "/market", label: "Market Prices", sub: "Check today's mandi rates", icon: LineChart },
              { to: "/farms", label: "Farm Details", sub: "Manage your farm plots", icon: MapPinned },
              { to: "/weather", label: "Weather", sub: "Check weekly forecast", icon: CloudSun },
            ].map(({ to, label, sub, icon: Icon }) => (
              <Link
                key={to}
                to={to}
                className="ring-glow flex items-center gap-3 rounded-xl border border-border bg-secondary/30 px-4 py-3 transition-colors hover:border-primary/30 hover:bg-secondary/50"
              >
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary ring-1 ring-inset ring-primary/20">
                  <Icon className="h-4 w-4" />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="text-sm font-medium">{label}</div>
                  <div className="text-[11px] text-muted-foreground">{sub}</div>
                </div>
                <ArrowRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              </Link>
            ))}
          </div>
        </section>

        {/* Alert details: only when there is something to list (the count is
            already in the Risk alerts card above). */}
        {alerts.length > 0 && (
        <section className="glass rounded-2xl p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-sm font-semibold">Risk alerts</h2>
            <Link to="/alerts" className="text-xs font-medium text-primary hover:underline">
              All alerts
            </Link>
          </div>
          <div className="space-y-2.5">
            {alerts.slice(0, 3).map((a) => (
              <div
                key={a._id || a.id}
                className={`rounded-xl border px-3.5 py-3 ${severityStyles[a.severity] || severityStyles.info}`}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-semibold">{a.title}</span>
                  <span className="shrink-0 text-[10px] opacity-70">
                    {a.createdAt ? new Date(a.createdAt).toLocaleDateString() : ""}
                  </span>
                </div>
                <p className="mt-1 line-clamp-2 text-[11px] leading-relaxed text-foreground/70">
                  {a.detail || a.message}
                </p>
              </div>
            ))}
          </div>
        </section>
        )}
      </div>

      {/* AI advisory + crop progress */}
      <div className="grid gap-5 lg:grid-cols-3">
        <section className="glass relative overflow-hidden rounded-2xl p-5 lg:col-span-2">
          <div className="absolute -right-10 -top-10 h-32 w-32 rounded-full bg-primary/15 blur-3xl" />
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-primary" />
            <h2 className="font-display text-sm font-semibold">AI recommendation highlights</h2>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {aiAdvisories.map((r) => (
              <div key={r.title} className="rounded-xl border border-border bg-secondary/30 p-4">
                <div className={`text-xs font-semibold ${r.tone}`}>{r.title}</div>
                <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">{r.body}</p>
              </div>
            ))}
          </div>
        </section>

        <section className="glass rounded-2xl p-5">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-sm font-semibold">Crop plan progress</h2>
            {cropPlan?.cropName && (
              <span className="rounded-lg bg-primary/10 px-2.5 py-0.5 text-xs font-semibold text-primary">
                {cropPlan.cropName}
              </span>
            )}
          </div>
          <div className="space-y-3">
            {shownStages.map((s) => {
              const phase = stagePhase(stages.indexOf(s));
              return (
              <div key={s._id || s.stage} className="flex items-center gap-3">
                <span
                  className={`grid h-5 w-5 shrink-0 place-items-center rounded-full text-[9px] font-bold ${
                    phase === "done"
                      ? "bg-primary text-primary-foreground"
                      : phase === "current"
                        ? "bg-primary/15 text-primary ring-1 ring-primary pulse-dot"
                        : "bg-secondary text-muted-foreground"
                  }`}
                >
                  {phase === "done" ? "✓" : ""}
                </span>
                <div className="min-w-0 flex-1">
                  <div
                    className={`truncate text-xs ${phase === "current" ? "font-semibold text-primary" : phase === "upcoming" ? "" : "text-muted-foreground"}`}
                  >
                    {s.stage}
                  </div>
                  <div className="text-[10px] text-muted-foreground">
                    {s.plannedDate ? new Date(`${String(s.plannedDate).slice(0, 10)}T00:00:00`).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : ""}
                    {phase === "current" ? " · now" : phase === "passed" ? " · passed" : ""}
                  </div>
                </div>
              </div>
              );
            })}
            {stages.length === 0 && (
              <div className="text-xs text-muted-foreground">No active crop plan</div>
            )}
          </div>
          <Link
            to="/crop-plan"
            className="mt-4 flex items-center justify-center gap-1 rounded-xl border border-border py-2 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/30 hover:text-primary"
          >
            Full crop roadmap <ArrowRight className="h-3 w-3" />
          </Link>
        </section>
      </div>
    </div>
  );
}

function StatCard({ label, value, hint, tone, bar, to }) {
  const toneClass =
    tone === "primary"
      ? "text-primary"
      : tone === "cyan"
        ? "text-cyan"
        : tone === "warning"
          ? "text-warning"
          : "text-foreground";
  const Wrapper = to ? Link : "div";
  return (
    <Wrapper
      {...(to ? { to } : {})}
      className="glass hover-lift block rounded-2xl p-5 transition-colors hover:border-primary/30 focus:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-medium uppercase tracking-widest text-muted-foreground">
          {label}
        </span>
        {to ? <ArrowRight className="h-3.5 w-3.5 text-muted-foreground" /> : null}
      </div>
      <div className={`mt-2 font-display text-2xl font-bold ${toneClass}`}>{value}</div>
      <div className="mt-1 text-[11px] text-muted-foreground">{hint}</div>
      {bar !== undefined && (
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-secondary">
          <div
            className="h-full rounded-full bg-gradient-to-r from-primary to-cyan"
            style={{ width: `${Math.min(bar, 100)}%` }}
          />
        </div>
      )}
    </Wrapper>
  );
}
