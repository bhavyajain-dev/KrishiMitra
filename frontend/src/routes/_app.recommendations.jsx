import { API_URL } from "@/lib/api";
import { createFileRoute, Link } from "@tanstack/react-router";
import {
  CloudSun, Crown, FlaskConical, Sparkles, Droplets,
  Loader2, RotateCcw, Leaf, Sprout,
} from "lucide-react";
import { PageHeader } from "@/components/app/AppShell";
import { useAppData } from "@/lib/AppDataContext";
import { useState, useEffect, useCallback, useRef } from "react";
import { toast } from "sonner";
import { subscribeAiSyncRefresh } from "@/lib/aiSyncEvents";

// The backend's fertilizer/irrigation fields come back as EITHER a plain string
// (error / "N/A ..." cases) OR a structured object (ML model or knowledge-base
// result). Normalize both to a display label so the UI never calls string
// methods on an object.
function recoLabel(value, key) {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "object") return value[key] || value.note || "";
  return String(value);
}

// Soil test value from the farm, or null when the farmer hasn't entered one.
// (Never substitute a made-up default: the backend handles missing soil data.)
function soilValue(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

function recoUnavailable(label) {
  return !label || label.includes("unavailable") || label.startsWith("N/A");
}

export const Route = createFileRoute("/_app/recommendations")({
  head: () => ({
    meta: [
      { title: "Crop Recommendations — KrishiMitra" },
      {
        name: "description",
        content:
          "Enter your soil data and get AI-powered crop recommendations ranked by suitability score.",
      },
    ],
  }),
  component: RecommendationsView,
});

const SOIL_TYPES = ["Black (Heavy)", "Red (Laterite)", "Sandy Loam", "Alluvial", "Clay", "Loamy", "Other"];
const SEASONS    = [{ value: "kharif", label: "Kharif (Jun–Oct)" }, { value: "rabi", label: "Rabi (Oct–Mar)" }];
const WATER_OPT  = [{ value: "low", label: "Low" }, { value: "medium", label: "Medium" }, { value: "high", label: "High" }];

const DEFAULT_FORM = {
  ph: "", nitrogen: "", phosphorus: "", potassium: "",
  organicCarbon: "", ec: "",
  startPreparationDate: new Date().toISOString().split("T")[0],
};

// Farm.soilType is stored as a lowercase slug ("black", "alluvial", ...);
// the recommendations form uses the display label instead. Maps one to the
// other so the farm's saved soil type prefills correctly.
const FARM_SOIL_TYPE_TO_LABEL = {
  black: "Black (Heavy)",
  red: "Red (Laterite)",
  laterite: "Red (Laterite)",
  sandy: "Sandy Loam",
  alluvial: "Alluvial",
  clay: "Clay",
  loamy: "Loamy",
  other: "Other",
};

function SoilInput({ label, id, value, placeholder, hint }) {
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
        {label}
      </label>
      <div className="rounded-xl border border-input bg-secondary/20 px-3 py-2.5 text-sm text-foreground/80">
        {value || <span className="text-muted-foreground/50">{placeholder}</span>}
      </div>
      {hint && <p className="text-[10px] text-muted-foreground/70">{hint}</p>}
    </div>
  );
}

function ScoreBar({ value, color = "bg-primary" }) {
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-full bg-secondary">
      <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${value ?? 0}%` }} />
    </div>
  );
}

export function RecommendationsView() {
  const { activeFarmId, activeFarm, postScoped, fetchScoped, token, isLoading: isAppLoading } = useAppData();
  const [results, setResults] = useState(null);
  const [llmSummary, setLlmSummary] = useState(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState(null);

  const loadSavedRecommendations = useCallback(async () => {
    if (!activeFarmId || !token) {
      setResults(null);
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchScoped("/recommendations");
      const latest = Array.isArray(data) ? data.sort((a, b) => new Date(b.createdAt || 0) - new Date(a.createdAt || 0))[0] : null;
      if (latest?.cropOptions?.length) {
        setResults(latest.cropOptions);
        setLlmSummary(latest.llmSummary || null);
      } else {
        setResults(null);
        setLlmSummary(null);
      }
    } catch (err) {
      console.error("Failed to load saved recommendations", err);
      setError("Failed to load existing recommendations.");
    } finally {
      setIsLoading(false);
    }
  }, [activeFarmId, token, fetchScoped]);

  useEffect(() => {
    loadSavedRecommendations();
  }, [loadSavedRecommendations]);

  useEffect(() => {
    const unsubscribe = subscribeAiSyncRefresh(() => {
      loadSavedRecommendations();
    });
    return unsubscribe;
  }, [loadSavedRecommendations]);

  const handleGenerateRecommendations = async () => {
    // Recommendations are for a specific farm (location, soil, water).
    if (!activeFarm) return;
    setIsGenerating(true);
    setError(null);

    const month = new Date().getMonth(); // 0-11
    const season = (month >= 5 && month <= 9) ? "kharif" : "rabi";

    const payload = {
      // Real Soil Health Card values (kg/ha) or null. No invented defaults:
      // without a soil test the backend averages over typical soils instead.
      ph: soilValue(activeFarm?.ph),
      nitrogen: soilValue(activeFarm?.nitrogen),
      phosphorus: soilValue(activeFarm?.phosphorus),
      potassium: soilValue(activeFarm?.potassium),
      organicCarbon: soilValue(activeFarm?.organicCarbon),
      ec: soilValue(activeFarm?.ec),
      season,
      areaAcres: Number(activeFarm?.areaAcres) || 2.0,
      waterAvailability: (activeFarm?.waterLevel || activeFarm?.waterAvailability || "medium").toLowerCase(),
      // Real farm location: lets the backend run the trained crop model with
      // season-aligned climate data. If coordinates are missing, the backend
      // resolves them from the address. Never default to a fixed state.
      latitude: activeFarm?.location?.lat ?? null,
      longitude: activeFarm?.location?.lon ?? null,
      state: activeFarm?.location?.state || null,
      address: activeFarm?.location?.address || null,
    };

    try {
      const res = await fetch(`${API_URL}/soil_recommend`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          // Logged-out (guest) users have no token: sending "Bearer null"
          // made the API reject the request with 401.
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify(payload),
      });

      if (!res.ok) {
        throw new Error(`Recommendation engine returned status ${res.status}`);
      }

      const data = await res.json();
      const recs = data.recommendations || [];
      const summary = data.llm_summary || null;

      setResults(recs);
      setLlmSummary(summary);

      // Persist to user recommendations for the active farm
      if (recs.length > 0 && activeFarmId) {
        try {
          await postScoped("/recommendations", {
            farm: activeFarmId,
            season: payload.season,
            cropOptions: recs,
            llmSummary: summary,
          });
          toast.success(`Generated recommendations for ${activeFarm?.name || "your farm"}`);
        } catch (e) {
          // If saving fails, results are still displayed in view
        }
      }
    } catch (err) {
      console.error("Failed to generate crop recommendations:", err);
      setError("Unable to generate recommendations right now. Please check your network and try again.");
      toast.error("Failed to generate crop recommendations");
    } finally {
      setIsGenerating(false);
    }
  };

  const soilFilled = ["ph", "nitrogen", "phosphorus", "potassium"]
    .filter((k) => soilValue(activeFarm?.[k]) !== null).length;
  const farmHasSoilTest = soilFilled === 4;
  const showSoil = (v) => (soilValue(v) === null ? "—" : v);
  const primary = results?.find((r) => r.isTopPick) || results?.[0];
  const others = results?.filter((r) => !r.isTopPick) || [];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Crop Recommendations"
        subtitle={
          activeFarm
            ? `AI agronomic suitability analysis for ${activeFarm.name}${activeFarm.areaAcres ? ` (${activeFarm.areaAcres} ${Number(activeFarm.areaAcres) === 1 ? "acre" : "acres"})` : ""}`
            : "AI-powered crop suitability rankings based on soil, climate, and season"
        }
        action={
          <div className="flex flex-wrap items-center gap-2">
            {results && results.length > 0 && (
              <button
                type="button"
                onClick={handleGenerateRecommendations}
                disabled={isGenerating}
                className="flex items-center gap-1.5 rounded-xl border border-border bg-secondary/30 px-3 sm:px-4 py-2 text-xs font-semibold hover:bg-secondary transition-colors cursor-pointer disabled:opacity-60"
              >
                <Sparkles className={`h-3.5 w-3.5 text-primary ${isGenerating ? "animate-spin" : ""}`} />
                <span>{isGenerating ? "Analyzing..." : "Re-analyze Crops"}</span>
              </button>
            )}
          </div>
        }
      />

      <div className="flex justify-between items-center px-2">
        <h2 className="font-display text-lg font-semibold text-primary">Farm Suitability Analysis</h2>
      </div>

      {activeFarm && !farmHasSoilTest && (
        <div className="glass flex items-start gap-3 rounded-2xl border border-warning/30 bg-warning/5 p-4 text-xs leading-relaxed">
          <FlaskConical className="mt-0.5 h-4 w-4 shrink-0 text-warning" />
          <div>
            {soilFilled === 0 ? (
              <>
                <span className="font-semibold text-foreground">No soil test for this farm yet.</span>{" "}
                <span className="text-muted-foreground">
                  Recommendations use your local climate, season and region only. Add your Soil Health Card values
                  (pH, N, P, K) to get a soil-specific recommendation.
                </span>
              </>
            ) : (
              <>
                <span className="font-semibold text-foreground">Soil test incomplete ({soilFilled} of 4 values).</span>{" "}
                <span className="text-muted-foreground">
                  Recommendations use the values you entered and typical soils for the rest. Add all of pH, N, P and K
                  for a fully soil-specific recommendation.
                </span>
              </>
            )}{" "}
            <Link to="/farms" className="font-semibold text-primary hover:underline">
              {soilFilled === 0 ? "Add soil test →" : "Complete soil test →"}
            </Link>
          </div>
        </div>
      )}

      {/* Loading state while generating */}
      {isGenerating && (
        <div className="glass rounded-3xl p-10 sm:p-14 text-center">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/25">
            <Loader2 className="h-7 w-7 animate-spin text-primary" />
          </div>
          <h3 className="font-display text-base font-semibold text-foreground">
            Evaluating Farm Suitability & Soil Profile
          </h3>
          <p className="mt-2 text-xs text-muted-foreground max-w-md mx-auto leading-relaxed">
            Running Random Forest & agronomic compatibility models across pH, NPK levels, moisture index, and seasonal crop cycles for {activeFarm?.name || "your farm"}...
          </p>
        </div>
      )}

      {/* Error state */}
      {error && !isGenerating && (
        <div className="glass rounded-3xl p-8 text-center border border-destructive/30 bg-destructive/5">
          <div className="text-sm font-semibold text-destructive">{error}</div>
          <p className="mt-1 text-xs text-muted-foreground">
            Make sure your farm soil parameters are configured, or try again.
          </p>
          <button
            type="button"
            onClick={handleGenerateRecommendations}
            className="mt-4 inline-flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground hover:opacity-90"
          >
            <RotateCcw className="h-3.5 w-3.5" /> Try Again
          </button>
        </div>
      )}

      {/* Empty state: No recommendations yet */}
      {/* No farm yet: nothing to recommend for. Ask the user to add one. */}
      {!isAppLoading && !activeFarm && (
        <div className="glass rounded-3xl p-8 sm:p-12 text-center border border-border">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/25">
            <Sprout className="h-7 w-7 text-primary" />
          </div>
          <h3 className="font-display text-lg font-semibold text-foreground">Add your farm first</h3>
          <p className="mt-2 text-xs text-muted-foreground max-w-lg mx-auto leading-relaxed">
            Crop recommendations are based on your farm's location, soil test and water availability.
            Add your farm to get recommendations made for it.
          </p>
          <Link
            to="/farms"
            className="mt-6 inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
          >
            <Sprout className="h-4 w-4" /> Add your farm
          </Link>
        </div>
      )}

      {activeFarm && !isLoading && !isGenerating && !results && !error && (
        <div className="glass rounded-3xl p-8 sm:p-12 text-center border border-border">
          <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-primary/10 ring-1 ring-primary/30 shadow-sm">
            <Sprout className="h-7 w-7 text-primary" />
          </div>
          <h3 className="font-display text-lg font-semibold text-foreground">
            No Crop Recommendations Generated Yet
          </h3>
          <p className="mt-2 text-xs text-muted-foreground max-w-lg mx-auto leading-relaxed">
            KrishiMitra analyzes your farm's soil chemistry (pH, Nitrogen, Phosphorus, Potassium), water availability, and regional agricultural season to recommend high-yield crops with estimated margins.
          </p>

          {/* Active Farm Soil Parameters Summary */}
          {activeFarm && (
            <div className="mt-6 mb-8 max-w-md mx-auto grid grid-cols-3 gap-2.5 text-left text-xs bg-secondary/20 rounded-2xl p-4 border border-border/50">
              <div className="rounded-xl bg-background/50 p-2.5">
                <div className="text-[10px] text-muted-foreground uppercase font-semibold">Soil pH</div>
                <div className="mt-0.5 font-bold text-foreground">{showSoil(activeFarm.ph)}</div>
              </div>
              <div className="rounded-xl bg-background/50 p-2.5">
                <div className="text-[10px] text-muted-foreground uppercase font-semibold">NPK Balance</div>
                <div className="mt-0.5 font-bold text-foreground">
                  {showSoil(activeFarm.nitrogen)}:{showSoil(activeFarm.phosphorus)}:{showSoil(activeFarm.potassium)}
                </div>
              </div>
              <div className="rounded-xl bg-background/50 p-2.5">
                <div className="text-[10px] text-muted-foreground uppercase font-semibold">Water</div>
                <div className="mt-0.5 font-bold text-foreground capitalize">{activeFarm.waterLevel || "—"}</div>
              </div>
            </div>
          )}

          <button
            type="button"
            onClick={handleGenerateRecommendations}
            className="inline-flex items-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-primary-foreground shadow-[0_0_24px_-8px_var(--color-primary)] transition-transform hover:scale-[1.02] cursor-pointer"
          >
            <Sparkles className="h-4 w-4" /> Generate Crop Recommendations
          </button>
        </div>
      )}

      {/* Results */}
      {results && !isGenerating && primary && (
        <>
          {/* Top pick hero */}
          {llmSummary && (
            <div className="glass rounded-3xl p-6 sm:p-8 bg-primary/5 border border-primary/20 mb-6">
              <div className="flex items-center gap-2 mb-3 text-primary">
                <Sparkles className="h-5 w-5" />
                <h3 className="font-semibold">AI Agronomist Summary</h3>
              </div>
              <div className="text-sm text-foreground/80 leading-relaxed whitespace-pre-wrap">
                {llmSummary}
              </div>
            </div>
          )}
          <section className="glass-strong hero-ambient relative overflow-hidden rounded-3xl p-6 sm:p-8">
            <div className="grid-pattern pointer-events-none absolute inset-0" />
            <div className="relative grid gap-6 lg:grid-cols-[minmax(0,1fr)_220px] lg:items-start">
              <div>
                <div className="mb-4 inline-flex items-center gap-1.5 rounded-full bg-primary/10 px-3 py-1 text-xs font-semibold text-primary ring-1 ring-inset ring-primary/20">
                  <Crown className="h-3.5 w-3.5" /> Top Recommendation
                </div>
                <h2 className="mb-2 text-3xl font-bold tracking-tight">{primary.displayName || primary.cropName}</h2>
                <p className="mb-6 max-w-xl text-sm leading-relaxed text-muted-foreground">{primary.reason}</p>

                <div className="flex flex-wrap items-center gap-x-6 gap-y-4">
                  <div className="space-y-0.5">
                    <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Overall Match</div>
                    <div className="text-3xl font-bold text-primary">
                      {primary.suitabilityScore}<span className="text-lg font-medium text-muted-foreground">%</span>
                    </div>
                  </div>
                  <div className="h-10 w-px bg-border/50 hidden sm:block" />
                  <div className="space-y-0.5">
                    <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Expected Yield</div>
                    <div className="text-lg font-bold">{Number(primary.expectedYieldKg ?? 0).toLocaleString("en-IN")} kg</div>
                    <div className="text-[10px] text-muted-foreground">{(() => { const a = Number(activeFarm?.areaAcres) || 2; return `for ${a} ${a === 1 ? "acre" : "acres"}`; })()}</div>
                  </div>
                  <div className="space-y-0.5">
                    <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Est. Profit</div>
                    <div className="text-lg font-bold text-primary">₹{Number(primary.expectedMarginRs ?? 0).toLocaleString("en-IN")}</div>
                  </div>
                  <div className="space-y-0.5">
                    <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Duration</div>
                    <div className="text-lg font-bold">{primary.durationDays} days</div>
                  </div>
                </div>

                {/* Machine Learning Insights (Fertilizer and Irrigation) */}
                {(primary.suggestedFertilizer || primary.irrigationPrediction) && (() => {
                  const fertilizerLabel = recoLabel(primary.suggestedFertilizer, "recommended_fertilizer");
                  const irrigationLabel = recoLabel(primary.irrigationPrediction, "irrigation_need");
                  return (
                    <div className="mt-6 flex flex-wrap gap-4 pt-4 border-t border-border/40">
                      {primary.suggestedFertilizer && (
                        <div className="rounded-xl border border-border/50 bg-secondary/20 p-3">
                          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-1 flex items-center gap-1"><Sprout className="h-3 w-3"/> Suggested Fertilizer</div>
                          <div className={`text-sm font-semibold ${recoUnavailable(fertilizerLabel) ? 'text-muted-foreground italic' : ''}`}>
                            {recoUnavailable(fertilizerLabel) ? 'Unavailable' : fertilizerLabel}
                          </div>
                        </div>
                      )}
                      {primary.irrigationPrediction && (
                        <div className="rounded-xl border border-border/50 bg-secondary/20 p-3">
                          <div className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground mb-1 flex items-center gap-1"><Droplets className="h-3 w-3"/> AI Irrigation Pattern</div>
                          <div className={`text-sm font-semibold ${recoUnavailable(irrigationLabel) ? 'text-muted-foreground italic' : ''}`}>
                            {recoUnavailable(irrigationLabel) ? 'Unavailable' : irrigationLabel}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>

              {/* Score bars */}
              <div className="glass flex flex-col gap-4 rounded-2xl bg-background/40 p-5">
                <div className="text-[10px] font-bold uppercase tracking-widest text-muted-foreground">Factor Analysis</div>
                <div className="space-y-3">
                  <div>
                    <div className="mb-1.5 flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5 text-muted-foreground"><FlaskConical className="h-3.5 w-3.5" />Soil Match</span>
                      <span className="font-semibold">{primary.soilMatchPct != null ? `${primary.soilMatchPct}%` : "No soil test"}</span>
                    </div>
                    <ScoreBar value={primary.soilMatchPct} />
                  </div>
                  <div>
                    <div className="mb-1.5 flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5 text-muted-foreground"><Droplets className="h-3.5 w-3.5" />Water / Climate</span>
                      <span className="font-semibold">{primary.weatherMatchPct}%</span>
                    </div>
                    <ScoreBar value={primary.weatherMatchPct} color="bg-cyan" />
                  </div>
                  <div>
                    <div className="mb-1.5 flex items-center justify-between text-xs">
                      <span className="flex items-center gap-1.5 text-muted-foreground"><Sparkles className="h-3.5 w-3.5" />Overall Match</span>
                      <span className="font-semibold">{primary.suitabilityScore}%</span>
                    </div>
                    <ScoreBar value={primary.suitabilityScore} color="bg-gradient-to-r from-primary to-cyan" />
                  </div>
                </div>
                
                <div className="mt-4 pt-4 border-t border-border/50">
                  <Link 
                    to="/crop-plan" 
                    search={{ crop: primary.cropName }}
                    className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary px-4 py-3 text-sm font-semibold text-primary-foreground transition-all hover:bg-primary/90 hover:shadow-md hover:shadow-primary/20"
                  >
                    <Sprout className="h-4 w-4" />
                    Create Crop Plan for {primary.displayName || primary.cropName}
                  </Link>
                </div>
              </div>
            </div>
          </section>

          {/* Alternatives */}
          {others.length > 0 && (
            <>
              <div className="text-xs font-bold uppercase tracking-widest text-muted-foreground">Strong Alternatives</div>
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                {others.map((crop) => (
                  <div key={crop.cropName} className="glass group relative overflow-hidden rounded-2xl p-5 transition-all hover:bg-card/60 hover:shadow-md">
                    <div className="mb-3 flex items-start justify-between">
                      <div>
                        <h3 className="font-bold">{crop.displayName || crop.cropName}</h3>
                        <div className="mt-0.5 text-[11px] text-muted-foreground">
                          Confidence: <span className="font-semibold text-foreground">{crop.suitabilityScore}%</span>
                        </div>
                      </div>
                      <span className="rounded-lg bg-secondary/70 px-2 py-0.5 text-[10px] font-medium text-muted-foreground">
                        {crop.durationDays}d
                      </span>
                    </div>

                    <div className="mb-3 space-y-2">
                      <div>
                        <div className="mb-0.5 flex justify-between text-[10px] text-muted-foreground">
                          <span>Soil</span><span>{crop.soilMatchPct != null ? `${crop.soilMatchPct}%` : "No soil test"}</span>
                        </div>
                        <ScoreBar value={crop.soilMatchPct} />
                      </div>
                      <div>
                        <div className="mb-0.5 flex justify-between text-[10px] text-muted-foreground">
                          <span>Water</span><span>{crop.weatherMatchPct}%</span>
                        </div>
                        <ScoreBar value={crop.weatherMatchPct} color="bg-cyan" />
                      </div>
                    </div>

                    <p className="mb-3 text-[11px] leading-relaxed text-muted-foreground line-clamp-2">{crop.reason}</p>

                    {(crop.suggestedFertilizer || crop.irrigationPrediction) && (() => {
                      const fertilizerLabel = recoLabel(crop.suggestedFertilizer, "recommended_fertilizer");
                      const irrigationLabel = recoLabel(crop.irrigationPrediction, "irrigation_need");
                      return (
                        <div className="mb-3 space-y-2 border-t border-border/50 pt-3">
                          {crop.suggestedFertilizer && (
                            <div className="text-[10px] text-muted-foreground flex items-center justify-between">
                              <span className="flex items-center gap-1 font-semibold"><Sprout className="h-3 w-3"/> Fertilizer</span>
                              <span className={`font-semibold truncate pl-2 max-w-[120px] text-right ${recoUnavailable(fertilizerLabel) ? 'text-muted-foreground italic' : 'text-foreground'}`} title={fertilizerLabel}>
                                {recoUnavailable(fertilizerLabel) ? 'Unavailable' : fertilizerLabel}
                              </span>
                            </div>
                          )}
                          {crop.irrigationPrediction && (
                            <div className="text-[10px] text-muted-foreground flex items-center justify-between">
                              <span className="flex items-center gap-1 font-semibold"><Droplets className="h-3 w-3"/> Irrigation</span>
                              <span className={`font-semibold truncate pl-2 max-w-[120px] text-right ${recoUnavailable(irrigationLabel) ? 'text-muted-foreground italic' : 'text-foreground'}`} title={irrigationLabel}>
                                {recoUnavailable(irrigationLabel) ? 'Unavailable' : irrigationLabel}
                              </span>
                            </div>
                          )}
                        </div>
                      );
                    })()}

                    <div className="flex items-center justify-between border-t border-border/50 pb-3 pt-3 text-xs font-semibold">
                      <div>{Number(crop.expectedYieldKg ?? 0).toLocaleString("en-IN")} kg</div>
                      <div className="text-primary">₹{Number(crop.expectedMarginRs ?? 0).toLocaleString("en-IN")}</div>
                    </div>
                    
                    <div className="border-t border-border/50 pt-3">
                      <Link 
                        to="/crop-plan" 
                        search={{ crop: crop.cropName }}
                        className="flex w-full items-center justify-center gap-2 rounded-xl bg-primary/10 px-4 py-2.5 text-xs font-semibold text-primary transition-all hover:bg-primary/20"
                      >
                        <Sprout className="h-3.5 w-3.5" />
                        Create Crop Plan
                      </Link>
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </>
      )}

      {results && results.length === 0 && (
        <div className="glass rounded-3xl py-16 text-center text-sm text-muted-foreground">
          No suitable crops found for the given inputs. Try adjusting the season or soil values.
        </div>
      )}
    </div>
  );
}
