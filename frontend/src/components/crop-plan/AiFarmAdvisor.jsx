import React, { useEffect, useState } from "react";
import { Sparkles, CloudRain, Droplet, Sprout, ShieldAlert, Thermometer } from "lucide-react";
import { fetchWeather } from "@/lib/api";

/**
 * Farm advisor for the active crop plan. Shows only real information:
 * the current stage from the plan, what to watch for (stage tips), and the
 * farm's actual 2-day forecast. Nothing here is invented.
 */
export function AiFarmAdvisor({ cropName, stageName, stageTips, lat, lon, onConsultAi }) {
  const [forecast, setForecast] = useState(null); // { rainPct, rainMm, maxTemp } | null
  const [weatherState, setWeatherState] = useState(lat != null && lon != null ? "loading" : "none");

  useEffect(() => {
    if (lat == null || lon == null) {
      setWeatherState("none");
      return;
    }
    let cancelled = false;
    setWeatherState("loading");
    fetchWeather(lat, lon)
      .then((res) => (res.ok ? res.json() : Promise.reject(new Error(`HTTP ${res.status}`))))
      .then((data) => {
        if (cancelled) return;
        const next = (data.daily_forecast || []).slice(0, 2);
        if (!next.length) throw new Error("no forecast");
        const nums = (k) => next.map((d) => Number(d?.[k])).filter(Number.isFinite);
        const rainPct = Math.max(...nums("precipitation_probability_max"), 0);
        const rainMm = nums("precipitation_sum").reduce((a, b) => a + b, 0);
        const maxTemp = Math.max(...nums("temp_max"), -Infinity);
        setForecast({ rainPct, rainMm, maxTemp: Number.isFinite(maxTemp) ? maxTemp : null });
        setWeatherState("ok");
      })
      .catch(() => !cancelled && setWeatherState("error"));
    return () => {
      cancelled = true;
    };
  }, [lat, lon]);

  const insights = [];
  if (stageName) {
    insights.push({
      icon: <Sprout className="w-3.5 h-3.5 text-emerald-500" />,
      text: `${cropName || "Your crop"} is in the ${stageName} stage.`,
    });
  }
  if (weatherState === "ok" && forecast) {
    if (forecast.rainPct >= 60) {
      insights.push({
        icon: <CloudRain className="w-3.5 h-3.5 text-cyan-400" />,
        text: `Rain likely in the next 2 days (${Math.round(forecast.rainPct)}% chance${forecast.rainMm ? `, about ${forecast.rainMm.toFixed(1)} mm` : ""}). Hold irrigation and spraying.`,
      });
    } else {
      insights.push({
        icon: <Droplet className="w-3.5 h-3.5 text-warning" />,
        text: `Mostly dry for the next 2 days (rain chance up to ${Math.round(forecast.rainPct)}%). Irrigate as scheduled.`,
      });
    }
    if (forecast.maxTemp != null && forecast.maxTemp >= 35) {
      insights.push({
        icon: <Thermometer className="w-3.5 h-3.5 text-destructive" />,
        text: `Hot days ahead (up to ${Math.round(forecast.maxTemp)}°C). Irrigate early morning or evening.`,
      });
    }
  } else if (weatherState === "none") {
    insights.push({
      icon: <CloudRain className="w-3.5 h-3.5 text-muted-foreground" />,
      text: "Add your farm's location to get weather-based advice here.",
    });
  } else if (weatherState === "error") {
    insights.push({
      icon: <CloudRain className="w-3.5 h-3.5 text-muted-foreground" />,
      text: "Weather is unavailable right now. Check the Weather page before irrigating or spraying.",
    });
  }
  if (stageTips?.watch_for) {
    insights.push({
      icon: <ShieldAlert className="w-3.5 h-3.5 text-primary" />,
      text: `Watch for: ${stageTips.watch_for}`,
    });
  }

  return (
    <div className="glass rounded-2xl p-5 border border-primary/20 shadow-sm relative overflow-hidden bg-gradient-to-br from-background via-background to-primary/5">
      <div className="flex justify-between items-center mb-4 relative z-10">
        <h3 className="text-sm font-bold text-foreground flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-primary" /> Farm Advisor
        </h3>
        <span className="text-[10px] uppercase font-bold tracking-widest text-primary/80 bg-primary/10 px-2 py-0.5 rounded-full">
          This week
        </span>
      </div>

      <div className="space-y-3 relative z-10">
        {weatherState === "loading" && (
          <p className="text-xs text-muted-foreground">Checking your farm's forecast…</p>
        )}
        {insights.map((insight, idx) => (
          <div key={idx} className="flex items-start gap-2.5">
            <div className="mt-0.5 p-1 bg-secondary/80 rounded-md shrink-0 border border-border/50">{insight.icon}</div>
            <p className="text-xs text-muted-foreground leading-snug">{insight.text}</p>
          </div>
        ))}

        {onConsultAi && (
          <button
            type="button"
            onClick={onConsultAi}
            className="mt-4 flex w-full items-center justify-center gap-2 rounded-xl bg-primary/10 border border-primary/25 px-3 py-2 text-xs font-semibold text-primary hover:bg-primary/20 transition-all cursor-pointer shadow-sm"
          >
            <Sparkles className="w-3.5 h-3.5" /> Ask AI Mitra about this Plan
          </button>
        )}
      </div>
    </div>
  );
}
