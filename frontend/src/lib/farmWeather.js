import { fetchWeather } from "@/lib/api";

/** True when the farm's address was found on the map. */
export function farmHasCoords(farm) {
  return farm?.location?.lat != null && farm?.location?.lon != null;
}

/**
 * Live weather for a farm's own coordinates, in the shape the dashboard,
 * Alerts and AI Mitra use. Throws if the forecast can't be fetched.
 */
export async function fetchFarmWeatherSnapshot(farm, token) {
  const { lat, lon, address } = farm.location;
  const res = await fetchWeather(lat, lon, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) throw new Error("Weather unavailable");
  const data = await res.json();
  const description = data.current?.weather_description;
  return {
    temp: data.current?.temperature != null ? Math.round(data.current.temperature) : null,
    humidity: data.current?.humidity ?? null,
    wind: data.current?.wind_speed != null ? Math.round(data.current.wind_speed) : null,
    uv: data.daily_forecast?.[0]?.uv_index_max ?? null,
    rainChance: data.daily_forecast?.[0]?.precipitation_probability_max ?? null,
    todayRainMm: data.current?.precipitation ?? 0,
    condition: description && description !== "Unknown" ? description : null,
    cityName: address,
    alerts: data.alerts || [],
  };
}

function levelFor(score) {
  if (score > 60) return { level: "Elevated", tone: "warning" };
  if (score > 30) return { level: "Moderate", tone: "cyan" };
  return { level: "Low", tone: "primary" };
}

/**
 * Weather risk (0–100) from today's real conditions plus the farm's active
 * weather alerts. Returns null when there is no weather to judge from.
 */
export function weatherRisk(snap, activeWeatherAlerts = 0) {
  if (!snap || snap.temp == null) return null;
  const rain = Number(snap.rainChance) || 0;
  const wind = Number(snap.wind) || 0;
  const temp = Number(snap.temp);
  const humidity = Number(snap.humidity) || 0;
  let score = 0;
  if (rain > 80) score += 40;
  else if (rain > 50) score += 20;
  if (wind > 35) score += 30;
  if (temp > 40) score += 30;
  else if (temp < 5) score += 20;
  if (humidity > 85 && temp > 20 && temp < 32) score += 20; // fungal weather
  score = Math.min(100, score + activeWeatherAlerts * 15);
  const parts = [];
  if (snap.rainChance != null) parts.push(`rain ${rain}%`);
  if (snap.wind != null) parts.push(`wind ${wind} km/h`);
  parts.push(`${temp}°C`);
  if (snap.humidity != null) parts.push(`humidity ${humidity}%`);
  return { pct: score, ...levelFor(score), hint: `Today: ${parts.join(" · ")}` };
}

/** Crop health risk from the farm's active crop-health alerts. */
export function cropHealthRisk(activeCropAlerts) {
  if (!activeCropAlerts) {
    return { pct: 0, level: "None reported", tone: "primary", hint: "No crop problems reported. Check a sick leaf in AI Mitra → Disease." };
  }
  const score = Math.min(100, activeCropAlerts * 30 + 10);
  return {
    pct: score,
    ...levelFor(score),
    hint: `${activeCropAlerts} crop health ${activeCropAlerts === 1 ? "alert" : "alerts"} open`,
  };
}

/** Plan tasks due in the next 7 days (today included). */
export function tasksThisWeek(plan, today = new Date()) {
  if (!plan) return null;
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const end = new Date(start);
  end.setDate(end.getDate() + 7);
  const tasks = Array.isArray(plan.tasks) ? plan.tasks : [];
  return tasks.filter((t) => {
    if (!t?.date || t.status === "done") return false;
    const d = new Date(`${String(t.date).slice(0, 10)}T00:00:00`);
    return d >= start && d < end;
  });
}

/**
 * A Risk Alert for severe weather today, or null. `cur` needs rainChance,
 * wind and temp (both the Weather page and the farm snapshot have them).
 */
export function severeWeatherAlert(cur, place) {
  if (!cur) return null;
  const { rainChance, wind, temp } = cur;
  if (rainChance >= 80) {
    return { severity: "warning", riskScorePct: 60, title: "Heavy rain expected",
      message: `${rainChance}% chance of rain today near ${place}. Consider delaying spraying/irrigation and check drainage.` };
  }
  if (wind >= 35) {
    return { severity: "warning", riskScorePct: 60, title: "High wind advisory",
      message: `Winds around ${wind} km/h expected near ${place}. Avoid spraying and secure loose structures/equipment.` };
  }
  if (temp >= 42) {
    return { severity: "critical", riskScorePct: 85, title: "Extreme heat warning",
      message: `Temperature near ${temp}°C expected at ${place}. Increase irrigation frequency and protect young/sensitive crops.` };
  }
  return null;
}

/** Was this alert already raised for the farm today? */
export function alreadyRaisedToday(alerts, title) {
  const today = new Date().toDateString();
  return (alerts || []).some(
    (a) => a.category === "weather" && a.title === title &&
      new Date(a.createdAt || a.created_at).toDateString() === today
  );
}
