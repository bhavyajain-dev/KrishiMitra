/**
 * Safe, single-use contextual handoff helper for AI Mitra.
 * Allows feature pages (Market Prices, Weather, Crop Plan, etc.) to initiate
 * a feature-specific AI analysis without exposing private data in URLs or
 * triggering duplicate prompt submissions on page refresh / remount.
 */

const STORAGE_KEY = "krishimitra_ai_handoff";
const MAX_AGE_MS = 60 * 1000; // 1-minute expiration

/**
 * Stores a contextual task in sessionStorage for AI Mitra to consume on mount.
 * @param {Object} options
 * @param {string} options.source - Source feature (e.g. 'market', 'weather', 'crop-plan')
 * @param {string} [options.taskName] - Human-readable name of the originating task (e.g. 'Market Prices', 'Weather & Advisory', 'Crop Plan')
 * @param {string} [options.actionLabel] - Present-tense action label (e.g. 'Analyzing Market Prices', 'Preparing Weather Advisory', 'Reviewing Crop Plan')
 * @param {string} [options.completedLabel] - Past-tense completion label (e.g. 'Market analysis complete', 'Weather advisory complete', 'Crop plan review complete')
 * @param {string} options.contextTitle - Short user-facing label (e.g. 'Market Analysis — Ahmedabad APMC')
 * @param {string} options.prompt - Full instruction and data prompt sent to AI Mitra
 * @param {Object} [options.metadata] - Optional non-sensitive metadata for UI display
 * @param {Object} [options.data] - Alternative alias for metadata
 */
export function setAiHandoff({
  source = "feature",
  taskName,
  actionLabel,
  completedLabel,
  contextTitle = "Feature Analysis",
  prompt,
  metadata = {},
  data,
}) {
  if (typeof window === "undefined" || !prompt) return;
  try {
    const meta = metadata && Object.keys(metadata).length > 0 ? metadata : data || {};
    const payload = {
      source,
      taskName: taskName || null,
      actionLabel: actionLabel || null,
      completedLabel: completedLabel || null,
      contextTitle,
      prompt,
      metadata: meta,
      timestamp: Date.now(),
    };
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(payload));
    window.dispatchEvent(
      new CustomEvent("krishi:ai-handoff", { detail: { source, contextTitle } }),
    );
  } catch (err) {
    console.error("Failed to store AI handoff context:", err);
  }
}

/**
 * Retrieves and immediately clears the contextual handoff from sessionStorage.
 * Guarantees that the analysis is submitted exactly once.
 * @returns {Object|null} The handoff payload, or null if absent / expired.
 */
export function consumeAiHandoff() {
  if (typeof window === "undefined") return null;
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;

    // Immediately remove to prevent reuse on refresh, remount, or back-navigation
    sessionStorage.removeItem(STORAGE_KEY);

    const data = JSON.parse(raw);
    if (!data || !data.prompt) return null;

    // Ignore expired handoffs (> 60s)
    if (Date.now() - (data.timestamp || 0) > MAX_AGE_MS) {
      return null;
    }

    return data;
  } catch (err) {
    console.error("Failed to consume AI handoff context:", err);
    return null;
  }
}

/**
 * Resolves full, feature-specific task metadata and labels for display.
 * @param {Object} handoff
 * @returns {Object|null} Clean task descriptors
 */
export function resolveTaskDescriptor(handoff) {
  if (!handoff) return null;
  const source = handoff.source || "feature";
  const meta = handoff.metadata || handoff.data || {};

  let taskName = handoff.taskName;
  let actionLabel = handoff.actionLabel;
  let completedLabel = handoff.completedLabel;
  let detail = "";

  if (source === "market") {
    taskName = taskName || "Market Prices";
    actionLabel = actionLabel || "Analyzing Market Prices";
    completedLabel = completedLabel || "Market analysis complete";
    const commodity = meta.commodity || "";
    const loc = meta.location || meta.district || meta.state || "";
    detail =
      commodity && loc ? `${commodity} · ${loc}` : commodity || loc || handoff.contextTitle || "";
  } else if (source === "weather") {
    taskName = taskName || "Weather & Advisory";
    actionLabel = actionLabel || "Preparing Weather Advisory";
    completedLabel = completedLabel || "Weather advisory complete";
    const city = meta.cityName || "";
    const cond = meta.condition || "";
    detail = city && cond ? `${city} (${cond})` : city || cond || handoff.contextTitle || "";
  } else if (source === "crop-plan") {
    taskName = taskName || "Crop Plan";
    actionLabel = actionLabel || "Reviewing Crop Plan";
    completedLabel = completedLabel || "Crop plan review complete";
    const crop = meta.cropName || "";
    const stage = meta.stage || "";
    detail = crop && stage ? `${crop} (${stage})` : crop || stage || handoff.contextTitle || "";
  } else {
    taskName = taskName || handoff.contextTitle || "Feature Task";
    actionLabel = actionLabel || `Analyzing ${taskName}`;
    completedLabel = completedLabel || `${taskName} complete`;
    detail = handoff.contextTitle || "";
  }

  const chips = [];
  if (source === "weather") {
    if (meta.cityName) chips.push({ label: meta.cityName, type: "location" });
    if (meta.temp !== undefined && meta.temp !== null) chips.push({ label: `${meta.temp}°C`, type: "temp" });
    if (meta.condition) chips.push({ label: meta.condition, type: "condition" });
    if (meta.rainChance !== undefined && meta.rainChance !== null) chips.push({ label: `${meta.rainChance}% rain`, type: "rain" });
  } else if (source === "market") {
    if (meta.commodity) chips.push({ label: meta.commodity, type: "commodity" });
    const loc = meta.district || meta.state || meta.location;
    if (loc && loc !== "all" && loc !== "Agmarknet") chips.push({ label: loc, type: "location" });
    if (meta.recordsCount) chips.push({ label: `${meta.recordsCount} mandis`, type: "count" });
  } else if (source === "crop-plan") {
    if (meta.cropName) chips.push({ label: meta.cropName, type: "crop" });
    if (meta.stage) chips.push({ label: meta.stage, type: "stage" });
    if (meta.currentDay) chips.push({ label: `Day ${meta.currentDay}`, type: "day" });
  }

  return {
    id: `task-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    source,
    taskName,
    actionLabel,
    completedLabel,
    detail,
    chips,
    contextTitle: handoff.contextTitle || taskName,
    metadata: meta,
    prompt: handoff.prompt,
  };
}
