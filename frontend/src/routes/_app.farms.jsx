import { API_URL } from "@/lib/api";
import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { Sparkles, MapPin, Ruler, Droplets, Satellite, Plus, AlertCircle, Crosshair, Sprout, Loader2, CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useAppData } from "@/lib/AppDataContext";
import { PageHeader } from "@/components/app/AppShell";
import { RecommendationsView } from "./_app.recommendations";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from "@/components/ui/dialog";
import { toast } from "sonner";
import { FARM_LIMITS, apiErrorMessage } from "@/lib/validation";
import { currentSeason } from "@/lib/season";

const SOIL_FIELDS = [
  { key: "ph", label: "pH", hint: "6.5–7.5", step: "any" },
  { key: "nitrogen", label: "Nitrogen N (kg/ha)", hint: "280–560", step: "any" },
  { key: "phosphorus", label: "Phosphorus P (kg/ha)", hint: "22–56", step: "any" },
  { key: "potassium", label: "Potassium K (kg/ha)", hint: "120–340", step: "any" },
  { key: "organicCarbon", label: "Organic carbon (%)", hint: "0.75–1.5", step: "any" },
  { key: "ec", label: "EC (dS/m)", hint: "0–2", step: "any" },
];

/** Scroll the first invalid field into view (forms are long on phones). */
function focusFirstError(errors, idFor) {
  const first = Object.keys(errors).find((k) => errors[k]);
  if (!first || typeof document === "undefined") return;
  const el = document.getElementById(idFor(first));
  if (el) {
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.focus({ preventScroll: true });
  }
}

export const Route = createFileRoute("/_app/farms")({
  head: () => ({
    meta: [
      { title: "Farm Details — KrishiMitra" },
      {
        name: "description",
        content: "Manage your farm plots: area, soil type, irrigation source and season status.",
      },
    ],
  }),
  component: FarmsPage,
});

const emptyForm = {
  name: "",
  areaAcres: "",
  soilType: "other",
  waterResources: [],
  waterLevel: "medium",
  currentCrop: "",
  location: "",
  ph: "",
  nitrogen: "",
  phosphorus: "",
  potassium: "",
  ec: "",
  organicCarbon: "",
};

function FarmsPage() {
  const { farms, token, fetchDashboardData, activeFarmId, setActiveFarmId, setUserLocation, postScoped, patchRecord } = useAppData();
  const [isAddOpen, setIsAddOpen] = useState(false);
  const [editingFarm, setEditingFarm] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formData, setFormData] = useState(emptyForm);
  const [formErrors, setFormErrors] = useState({});
  const [isLocating, setIsLocating] = useState(false);
  const [isAnalyzeOpen, setIsAnalyzeOpen] = useState(false);
  const [analyzingFarm, setAnalyzingFarm] = useState(null);
  const [isAnalyzing, setIsAnalyzing] = useState(false);

  // Edit specific state
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [targetEditFarm, setTargetEditFarm] = useState(null);
  const [editFormData, setEditFormData] = useState(emptyForm);
  const [editFormErrors, setEditFormErrors] = useState({});
  const [isEditSubmitting, setIsEditSubmitting] = useState(false);
  const [isEditLocating, setIsEditLocating] = useState(false);
  
  // Analysis specific inputs
  const initialDate = new Date().toISOString().split("T")[0];
  const [analysisDate, setAnalysisDate] = useState(initialDate);
  const [analysisSeason, setAnalysisSeason] = useState(() => {
    const month = new Date(initialDate).getMonth() + 1;
    if (month >= 6 && month <= 9) return "kharif";
    if (month >= 10 || month <= 2) return "rabi";
    if (month >= 3 && month <= 5) return "zaid";
    return "kharif";
  });
  const [analysisIrrigation, setAnalysisIrrigation] = useState("Drip");
  const [analysisFormData, setAnalysisFormData] = useState({});
  const [analysisFormErrors, setAnalysisFormErrors] = useState({});
  
  const navigate = useNavigate();


  const handleGetCurrentLocation = () => {
    if (!navigator.geolocation) {
      toast.error("Geolocation is not supported by your browser");
      return;
    }
    setIsLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const res = await fetch(
            `${API_URL}/geocode/reverse?lat=${pos.coords.latitude}&lon=${pos.coords.longitude}`
          );
          if (!res.ok) throw new Error("Geocoding failed");
          const data = await res.json();
          if (data && (data.address || data.city)) {
            const city = data.city || "";
            const state = data.state || "";
            const district = data.district || "";
            const locString = data.address || [city, state].filter(Boolean).join(", ");
            if (locString) {
              setFormData((prev) => ({ ...prev, location: locString }));
              setUserLocation({
                query: locString, address: locString, city, state, district,
                lat: pos.coords.latitude, lon: pos.coords.longitude,
              });
              toast.success("Location detected and saved!");
            } else {
              toast.error("Could not resolve city/state from location.");
            }
          }
        } catch (err) {
          console.error(err);
          toast.error("Failed to detect location address");
        } finally {
          setIsLocating(false);
        }
      },
      (err) => {
        console.error(err);
        toast.error("Could not get location. Please check browser permissions.");
        setIsLocating(false);
      }
    );
  };

  const validateFarmElements = (data, isAnalyze = false) => {
    const errs = {};
    if (data.areaAcres !== undefined) {
      const [minArea, maxArea] = FARM_LIMITS.areaAcres;
      const area = Number(data.areaAcres);
      if (data.areaAcres === "" || data.areaAcres === null) errs.areaAcres = "Area is required";
      else if (!Number.isFinite(area) || area < minArea || area > maxArea) errs.areaAcres = `Area must be between ${minArea} and ${maxArea.toLocaleString("en-IN")} acres`;
    }

    const checkRange = (val, min, max, name, req) => {
      if (val === "" || val === null || val === undefined) {
        if (req) errs[name] = "Required";
      } else {
        const num = Number(val);
        if (!Number.isFinite(num) || num < min || num > max) errs[name] = `Must be between ${min} and ${max}`;
      }
    };

    const req = isAnalyze;
    checkRange(data.nitrogen, ...FARM_LIMITS.nitrogen, "nitrogen", req);
    checkRange(data.phosphorus, ...FARM_LIMITS.phosphorus, "phosphorus", req);
    checkRange(data.potassium, ...FARM_LIMITS.potassium, "potassium", req);
    checkRange(data.ph, ...FARM_LIMITS.ph, "ph", req);
    checkRange(data.organicCarbon, ...FARM_LIMITS.organicCarbon, "organicCarbon", false);
    checkRange(data.ec, ...FARM_LIMITS.ec, "ec", false);

    return errs;
  };

  const handleEditSubmit = async (e) => {
    e.preventDefault();
    let errors = {};
    if (!editFormData.name?.trim()) errors.name = "Name is required";
    
    const elementErrs = validateFarmElements(editFormData, false);
    errors = { ...errors, ...elementErrs };
    if (Object.keys(errors).length > 0) {
      setEditFormErrors(errors);
      focusFirstError(errors, (k) => (k === "organicCarbon" ? "edit_carbon" : `edit_${k}`));
      return;
    }

    setIsEditSubmitting(true);
    try {
      const payload = {
        name: editFormData.name.trim(),
        areaAcres: Number(editFormData.areaAcres),
        waterResources: Array.isArray(editFormData.waterResources) ? editFormData.waterResources : [],
        waterLevel: editFormData.waterLevel,
        currentCrop: editFormData.currentCrop,
        ph: (!editFormData.ph && editFormData.ph !== 0) ? null : Number(editFormData.ph),
        nitrogen: (!editFormData.nitrogen && editFormData.nitrogen !== 0) ? null : Number(editFormData.nitrogen),
        phosphorus: (!editFormData.phosphorus && editFormData.phosphorus !== 0) ? null : Number(editFormData.phosphorus),
        potassium: (!editFormData.potassium && editFormData.potassium !== 0) ? null : Number(editFormData.potassium),
        ec: (!editFormData.ec && editFormData.ec !== 0) ? null : Number(editFormData.ec),
        organicCarbon: (!editFormData.organicCarbon && editFormData.organicCarbon !== 0) ? null : Number(editFormData.organicCarbon),
        isActive: true
      };

      const url = `${API_URL}/farms/${targetEditFarm._id || targetEditFarm.id}`;
      const res = await fetch(url, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify(payload)
      });
      
      if (res.ok) {
        const savedFarm = await res.json();
        
        await fetchDashboardData();
        toast.success("Farm updated");
        setIsEditModalOpen(false);
        setTargetEditFarm(null);
        setEditFormData(emptyForm);
      } else {
        const errorData = await res.json().catch(() => ({}));
        console.error("Farm edit error:", errorData);
        toast.error(`Could not save farm. ${apiErrorMessage(errorData)}`);
      }
    } catch (err) {
      console.error("Network error:", err);
      toast.error("Network error saving farm edit.");
    } finally {
      setIsEditSubmitting(false);
    }
  };

  const toggleEditWaterResource = (item) => {
    setEditFormData((prev) => {
      const arr = Array.isArray(prev.waterResources) ? prev.waterResources : [];
      if (arr.includes(item)) return { ...prev, waterResources: arr.filter((x) => x !== item) };
      return { ...prev, waterResources: [...arr, item] };
    });
  };

  const handleEditGetCurrentLocation = () => {
    if (!navigator.geolocation) {
      toast.error("Geolocation is not supported by your browser");
      return;
    }
    setIsEditLocating(true);
    navigator.geolocation.getCurrentPosition(
      async (position) => {
        try {
          const res = await fetch(`${API_URL}/geocode/reverse?lat=${position.coords.latitude}&lon=${position.coords.longitude}`);
          if (!res.ok) throw new Error("Geocoding failed");
          const data = await res.json();
          if (data && (data.address || data.city)) {
            const addressString = data.address || [data.city, data.state].filter(Boolean).join(", ");
            setEditFormData((prev) => ({ ...prev, location: addressString }));
          } else {
            toast.error("Could not determine address from coordinates");
          }
        } catch (err) {
          toast.error("Failed to fetch address");
        } finally {
          setIsEditLocating(false);
        }
      },
      (error) => {
        setIsEditLocating(false);
        if (error.code === 1) toast.error("Location permission denied.");
        else toast.error("Failed to get your location.");
      }
    );
  };

  const totalArea = farms.reduce((s, f) => s + (f.areaAcres || 0), 0);
  const activeCount = farms.filter((f) => f.isActive).length;

  const openAdd = () => {
    setEditingFarm(null);
    setFormData(emptyForm);
    setFormErrors({});
    setIsAddOpen(true);
  };

  const openAnalyzeModal = (f) => {
    setAnalyzingFarm(f);
    setAnalysisFormData({
      nitrogen: f.nitrogen ?? "",
      phosphorus: f.phosphorus ?? "",
      potassium: f.potassium ?? "",
      ph: f.ph ?? "",
      organicCarbon: f.organicCarbon ?? "",
      ec: f.ec ?? ""
    });
    setAnalysisFormErrors({});
    setIsAnalyzeOpen(true);
  };

  const openEditModal = (f) => {
    setTargetEditFarm(f);
    setEditFormData({
      name: f.name || "",
      areaAcres: f.areaAcres ?? "",
      waterResources: Array.isArray(f.waterResources) ? f.waterResources : [],
      waterLevel: f.waterLevel || "medium",
      currentCrop: f.currentCrop || "",
      ph: f.ph ?? "",
      nitrogen: f.nitrogen ?? "",
      phosphorus: f.phosphorus ?? "",
      potassium: f.potassium ?? "",
      ec: f.ec ?? "",
      organicCarbon: f.organicCarbon ?? "",
    });
    setEditFormErrors({});
    setIsEditModalOpen(true);
  };

  const openEdit = (f) => {
    setEditingFarm(f);
    setFormData({
      name: f.name || "",
      areaAcres: f.areaAcres ?? "",
      soilType: f.soilType || "other",
      waterResources: Array.isArray(f.waterResources) ? f.waterResources : (typeof f.waterResources === 'string' ? [f.waterResources] : []),
      waterLevel: f.waterLevel || "medium",
      currentCrop: f.currentCrop || "",
      location: f.location?.address || "",
      ph: f.ph ?? "", nitrogen: f.nitrogen ?? "", phosphorus: f.phosphorus ?? "", potassium: f.potassium ?? "", ec: f.ec ?? "", organicCarbon: f.organicCarbon ?? "",
    });
    setIsAddOpen(true);
  };

  const handleDelete = async (f) => {
    if (!window.confirm(`Delete "${f.name}"? This cannot be undone.`)) return;
    try {
      const res = await fetch(`${API_URL}/farms/${f._id || f.id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        await fetchDashboardData();
        toast.success("Farm deleted");
      } else {
        toast.error("Failed to delete farm");
      }
    } catch (err) {
      toast.error("Error deleting farm");
    }
  };

  const runAnalysisAndSave = async () => {
    const errors = validateFarmElements(analysisFormData, true);
    if (!analysisDate) {
      errors.date = "Required";
    } else if (analysisDate < initialDate) {
      errors.date = "Date cannot be in the past";
    }

    if (Object.keys(errors).length > 0) {
      setAnalysisFormErrors(errors);
      return;
    }
    setAnalysisFormErrors({});

    setIsAnalyzing(true);
    try {
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

      const payload = {
        ph:             Number(analysisFormData.ph),
        nitrogen:       Number(analysisFormData.nitrogen),
        phosphorus:     Number(analysisFormData.phosphorus),
        potassium:      Number(analysisFormData.potassium),
        // Optional: sent only when entered (never a made-up default).
        organicCarbon:  (analysisFormData.organicCarbon !== "" && analysisFormData.organicCarbon !== null && analysisFormData.organicCarbon !== undefined) ? Number(analysisFormData.organicCarbon) : null,
        ec:             (analysisFormData.ec !== "" && analysisFormData.ec !== null && analysisFormData.ec !== undefined) ? Number(analysisFormData.ec) : null,
        soilType:       FARM_SOIL_TYPE_TO_LABEL[analyzingFarm?.soilType] || "Black (Heavy)",
        season:         analysisSeason,
        areaAcres:      Number(analyzingFarm?.areaAcres) || 1,
        waterAvailability: analyzingFarm?.waterLevel || "medium",
        startPreparationDate: analysisDate,
        irrigationType: analysisIrrigation,
        // Real farm location (from geocoding at farm creation). Enables the
        // trained crop model, which needs season-aligned climate + state.
        // Sent only when present; when null/absent the backend skips the model
        // and uses the heuristic (it never fabricates these values).
        latitude:  analyzingFarm?.location?.lat ?? null,
        longitude: analyzingFarm?.location?.lon ?? null,
        state:     analyzingFarm?.location?.state || null,
        address:   analyzingFarm?.location?.address || null,
      };

      const res = await fetch(`${API_URL}/soil_recommend`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!res.ok) throw new Error("ML server error");
      const data = await res.json();
      
      const results = data.recommendations || [];
      const llmSummary = data.llm_summary || null;
      
      await postScoped("/recommendations", {
        farm:        analyzingFarm._id || analyzingFarm.id,
        season:      currentSeason().key === payload.season
                       ? currentSeason().label
                       : (payload.season === "kharif" ? "Kharif" : "Rabi"),
        cropOptions: results.map((r) => ({
          cropName:         r.cropName,
          suitabilityScore: r.suitabilityScore,
          weatherMatchPct:  r.weatherMatchPct,
          soilMatchPct:     r.soilMatchPct,
          expectedYieldKg:  r.expectedYieldKg,
          durationDays:     r.durationDays,
          expectedMarginRs: r.expectedMarginRs,
          isTopPick:        r.isTopPick,
          reason:           r.reason,
          suggestedFertilizer: r.suggestedFertilizer,
          irrigationPrediction: r.irrigationPrediction,
        })),
        llmSummary: llmSummary
      });
      
      toast.success("Analysis complete and saved!");
      setActiveFarmId(analyzingFarm._id || analyzingFarm.id);
      setIsAnalyzeOpen(false);
      navigate({ to: "/recommendations" });
      
    } catch (err) {
      toast.error("Analysis failed. Make sure backend is running on port 5001.");
      console.error(err);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    let newErrors = {};
    if (!formData.name.trim()) newErrors.name = "Farm name is required";
    
    const elementErrs = validateFarmElements(formData, false);
    newErrors = { ...newErrors, ...elementErrs };

    if (Object.keys(newErrors).length > 0) {
      setFormErrors(newErrors);
      focusFirstError(newErrors, (k) => (k === "name" || k === "areaAcres" ? k : `add_${k}`));
      return;
    }
    setFormErrors({});
    setIsSubmitting(true);
    try {
      const payload = {
        name: formData.name.trim(),
        areaAcres: Number(formData.areaAcres),
        soilType: formData.soilType,
        waterResources: formData.waterResources,
        waterLevel: formData.waterLevel,
        currentCrop: formData.currentCrop,
        location: { address: formData.location },
        ph: (!formData.ph && formData.ph !== 0) ? null : Number(formData.ph),
        nitrogen: (!formData.nitrogen && formData.nitrogen !== 0) ? null : Number(formData.nitrogen),
        phosphorus: (!formData.phosphorus && formData.phosphorus !== 0) ? null : Number(formData.phosphorus),
        potassium: (!formData.potassium && formData.potassium !== 0) ? null : Number(formData.potassium),
        ec: (!formData.ec && formData.ec !== 0) ? null : Number(formData.ec),
        organicCarbon: (!formData.organicCarbon && formData.organicCarbon !== 0) ? null : Number(formData.organicCarbon),
        isActive: true
      };

      const isEditing = Boolean(editingFarm);
      const url = isEditing ? `${API_URL}/farms/${editingFarm._id || editingFarm.id}` : `${API_URL}/farms`;
      const res = await fetch(url, {
        method: isEditing ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json", "Authorization": `Bearer ${token}` },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const savedFarm = await res.json();
        
        if (formData.location) {
          try {
            const geoRes = await fetch(`${API_URL}/geocode?q=${encodeURIComponent(formData.location)}&limit=1`);
            if (geoRes.ok) {
              const geoData = await geoRes.json();
              if (geoData && geoData.lat != null && geoData.lon != null) {
                const city = geoData.city || "";
                const state = geoData.state || "";
                const district = geoData.district || "";
                const lat = geoData.lat;
                const lon = geoData.lon;
                
                setUserLocation({ query: formData.location, address: formData.location, city, state, district, lat, lon });
                
                await patchRecord(`/farms/${savedFarm._id || savedFarm.id}`, {
                  location: { address: formData.location, city, state, district, lat, lon }
                });
              }
            }
          } catch (e) {
            console.error("Geocoding during save failed", e);
          }
        }

        await fetchDashboardData();
        toast.success(isEditing ? "Farm updated" : "Farm added");
        setIsAddOpen(false);
        setEditingFarm(null);
        setFormData(emptyForm);
      } else {
        const errorData = await res.json().catch(() => ({}));
        console.error("Farm save error:", errorData);
        toast.error(`Could not save farm. ${apiErrorMessage(errorData)}`);
      }
    } catch (err) {
      console.error("Network error:", err);
      toast.error("Network error saving farm.");
    } finally {
      setIsSubmitting(false);
    }
  };

  const toggleWaterResource = (item) => {
    setFormData((prev) => {
      const arr = Array.isArray(prev.waterResources) ? prev.waterResources : [];
      if (arr.includes(item)) return { ...prev, waterResources: arr.filter((x) => x !== item) };
      return { ...prev, waterResources: [...arr, item] };
    });
  };

  return (
    <div>
      <PageHeader
        title="Farm Details"
        subtitle={`${farms.length} plots · ${totalArea.toFixed(1)} acres total · ${activeCount} active this season`}
        action={
          <button onClick={openAdd} className="flex items-center gap-1.5 rounded-xl bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground shadow-[0_0_24px_-8px_var(--color-primary)] transition-transform hover:scale-[1.03]">
            <Plus className="h-3.5 w-3.5" /> Add farm
          </button>
        }
      />

      <section className="glass relative mb-5 overflow-hidden rounded-2xl">
        <div className="grid-pattern absolute inset-0" />
        <div className="relative flex flex-wrap items-center gap-6 p-6">
          <div className="grid h-14 w-14 place-items-center rounded-2xl bg-cyan/10 ring-1 ring-cyan/25">
            <MapPin className="h-6 w-6 text-cyan" />
          </div>
          <div className="min-w-0 flex-1">
            <h2 className="font-display text-base font-semibold">Your farms</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              Plots, total area and irrigation across all your farms
            </p>
          </div>
          <div className="flex gap-6 text-center">
            {[
              [String(farms.length), "Farms"],
              [`${totalArea.toFixed(1)} ac`, "Total area"],
              [String(farms.filter(f => f.waterResources?.length > 0).length), "Irrigated"],
            ].map(([v, l]) => (
              <div key={l}>
                <div className="font-display text-lg font-bold text-cyan">{v}</div>
                <div className="text-[10px] uppercase tracking-widest text-muted-foreground">
                  {l}
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {farms.map((f) => (
          <div
            key={f._id || f.id}
            className={`glass ring-glow relative overflow-hidden rounded-2xl p-5 ${activeFarmId === (f._id || f.id) ? "ring-2 ring-primary/50" : ""}`}
            onClick={() => setActiveFarmId(activeFarmId === (f._id || f.id) ? null : (f._id || f.id))}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <h3 className="truncate font-display text-sm font-semibold">{f.name}</h3>
                <div className="mt-1 flex items-center gap-1 text-[11px] text-muted-foreground">
                  <MapPin className="h-3 w-3" /> {f.location?.address || "Unknown"}
                </div>
              </div>
              <span
                className={`shrink-0 rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide ${
                  f.isActive
                    ? "bg-primary/12 text-primary ring-1 ring-primary/25"
                    : "bg-secondary text-muted-foreground"
                }`}
              >
                {f.isActive ? "active" : "inactive"}
              </span>
            </div>

            <div className="mt-4 grid grid-cols-2 gap-2.5 text-xs">
              <InfoChip icon={Ruler} label="Area" value={`${f.areaAcres} acres`} />
              <InfoChip icon={Droplets} label="Water Source" value={Array.isArray(f.waterResources) && f.waterResources.length > 0 ? f.waterResources.join(', ') : "Rainfed"} />
              <InfoChip icon={Sprout} label="Crop" value={f.currentCrop || "None (fallow)"} />
              <InfoChip icon={Satellite} label="Soil" value={f.soilType ? f.soilType.charAt(0).toUpperCase() + f.soilType.slice(1) : "Other"} />
            </div>

            {(() => {
              // Real data only: how much of the Soil Health Card is filled in.
              const soilKeys = ["ph", "nitrogen", "phosphorus", "potassium"];
              const filled = soilKeys.filter((k) => f[k] !== null && f[k] !== undefined && f[k] !== "").length;
              return (
                <div className="mt-4 flex items-center justify-between gap-2 rounded-xl border border-border/60 bg-secondary/30 px-3 py-2 text-[11px]">
                  <span className="text-muted-foreground">Soil test (pH, N, P, K)</span>
                  {filled === soilKeys.length ? (
                    <span className="font-semibold text-primary">Complete</span>
                  ) : filled > 0 ? (
                    <span className="font-semibold text-foreground">{filled} of 4 added</span>
                  ) : (
                    <button type="button" onClick={() => openEditModal(f)} className="font-semibold text-primary hover:underline">Add values</button>
                  )}
                </div>
              );
            })()}

            <div className="mt-4 flex gap-2">
              <button
                onClick={() => openEditModal(f)}
                className="flex-1 rounded-lg border border-border py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:border-primary/30 hover:text-primary"
              >
                Edit details
              </button>
              <button
                onClick={() => openAnalyzeModal(f)}
                className="flex-1 rounded-lg border border-border py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:border-cyan/30 hover:text-cyan"
              >
                Analyse & Recommend
              </button>
              <button
                onClick={() => handleDelete(f)}
                className="rounded-lg border border-border px-2.5 py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:border-destructive/40 hover:text-destructive"
              >
                Delete
              </button>
            </div>
          </div>
        ))}

        <button onClick={openAdd} className="ring-glow grid min-h-52 place-items-center rounded-2xl border border-dashed border-border text-muted-foreground transition-colors hover:text-primary">
          <div className="text-center">
            <Plus className="mx-auto h-6 w-6" />
            <div className="mt-2 text-xs font-medium">Add a new farm plot</div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">
              Area · soil · irrigation · season
            </div>
          </div>
        </button>
      </div>

      <Dialog open={isAddOpen} onOpenChange={(open) => { setIsAddOpen(open); if (!open) setEditingFarm(null); }}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>{editingFarm ? `Edit ${editingFarm.name}` : "Add a new farm"}</DialogTitle>
            <DialogDescription>
              {editingFarm
                ? "Update this farm plot's details below."
                : "Enter the details of your new farm plot below."}
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleSubmit} className="grid gap-4 py-4 max-h-[70vh] overflow-y-auto pr-2">
            <div>
              <label htmlFor="name" className="mb-1 block text-[11px] font-medium text-muted-foreground">Name *</label>
              <input
                id="name" maxLength={255}
                value={formData.name}
                onChange={(e) => { setFormData({...formData, name: e.target.value}); if (formErrors.name) setFormErrors(p => ({...p, name: ""})); }}
                className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${formErrors.name ? "border-destructive" : "border-input"}`}
              />
              {formErrors.name && <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive"><AlertCircle className="h-3 w-3" />{formErrors.name}</p>}
            </div>
            <div>
              <label htmlFor="areaAcres" className="mb-1 block text-[11px] font-medium text-muted-foreground">Area (Acres) *</label>
              <input
                type="number" step="any" id="areaAcres"
                value={formData.areaAcres}
                onChange={(e) => { setFormData({...formData, areaAcres: e.target.value}); if (formErrors.areaAcres) setFormErrors(p => ({...p, areaAcres: ""})); }}
                className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${formErrors.areaAcres ? "border-destructive" : "border-input"}`}
              />
              {formErrors.areaAcres && <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive"><AlertCircle className="h-3 w-3" />{formErrors.areaAcres}</p>}
            </div>
            <div>
              <label htmlFor="location" className="mb-1 block text-[11px] font-medium text-muted-foreground">Location</label>
              <div className="flex gap-2">
                <input id="location" placeholder="e.g. Pune, Maharashtra" value={formData.location} onChange={(e) => setFormData({...formData, location: e.target.value})} className="flex-1 rounded-xl border border-input bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50" />
                <button
                  type="button"
                  onClick={handleGetCurrentLocation}
                  disabled={isLocating}
                  className="flex shrink-0 items-center justify-center gap-1.5 rounded-xl bg-primary/10 px-3 py-2 text-xs font-semibold text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
                  title="Use my current location"
                >
                  <Crosshair className={`h-4 w-4 ${isLocating ? "animate-spin" : ""}`} />
                </button>
              </div>
            </div>
            <div>
              <label htmlFor="soilType" className="mb-1 block text-[11px] font-medium text-muted-foreground">Soil Type</label>
              <select id="soilType" value={formData.soilType} onChange={(e) => setFormData({...formData, soilType: e.target.value})} className="w-full rounded-xl border border-input bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50">
                <option value="alluvial">Alluvial</option>
                <option value="black">Black</option>
                <option value="red">Red</option>
                <option value="laterite">Laterite</option>
                <option value="sandy">Sandy</option>
                <option value="clay">Clay</option>
                <option value="loamy">Loamy</option>
                <option value="other">Other</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Water Resources</label>
              <div className="grid grid-cols-2 gap-2">
                {["Borewell", "Canal", "River", "Rainfed", "Drip System", "Sprinklers"].map(item => (
                  <button
                    type="button"
                    key={item}
                    onClick={() => toggleWaterResource(item)}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-medium transition-all ${
                      (Array.isArray(formData.waterResources) ? formData.waterResources : []).includes(item)
                        ? "border-primary bg-primary/10 text-primary shadow-[0_0_15px_-5px_var(--color-primary)]"
                        : "border-border text-muted-foreground hover:border-primary/50"
                    }`}
                  >
                    <div className={`h-3 w-3 rounded-full border flex items-center justify-center ${(Array.isArray(formData.waterResources) ? formData.waterResources : []).includes(item) ? "border-primary bg-primary" : "border-muted-foreground"}`}>
                      {(Array.isArray(formData.waterResources) ? formData.waterResources : []).includes(item) && <CheckCircle2 className="h-2 w-2 text-background" />}
                    </div>
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label htmlFor="waterLevel" className="mb-1 block text-[11px] font-medium text-muted-foreground">Water Availability</label>
              <select id="waterLevel" value={formData.waterLevel} onChange={(e) => setFormData({...formData, waterLevel: e.target.value})} className="w-full rounded-xl border border-input bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50">
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
              <p className="mt-4 mb-1.5 text-[11px] font-medium text-muted-foreground">
                Soil test <span className="font-normal">(optional, from your Soil Health Card)</span>
              </p>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                {SOIL_FIELDS.map(({ key, label, hint, step }) => (
                  <div key={key}>
                    <label htmlFor={`add_${key}`} className="mb-0.5 block text-[10px] text-muted-foreground">{label}</label>
                    <input
                      id={`add_${key}`}
                      type="number"
                      inputMode="decimal"
                      step={step}
                      min={FARM_LIMITS[key][0]}
                      max={FARM_LIMITS[key][1]}
                      placeholder={hint}
                      value={formData[key]}
                      onChange={(e) => { setFormData({ ...formData, [key]: e.target.value }); if (formErrors[key]) setFormErrors(p => ({ ...p, [key]: "" })); }}
                      className={`w-full rounded-xl border bg-secondary/40 px-3 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${formErrors[key] ? "border-destructive" : "border-input"}`}
                    />
                    {formErrors[key] && <p className="mt-0.5 text-[10px] leading-tight text-destructive">{formErrors[key]}</p>}
                  </div>
                ))}
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button disabled={isSubmitting} type="submit" className="w-full rounded-xl bg-primary py-2.5 text-xs font-semibold text-primary-foreground transition-transform hover:scale-[1.02]">
                {isSubmitting ? "Saving..." : editingFarm ? "Save changes" : "Add Farm"}
              </button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={isEditModalOpen} onOpenChange={(open) => { setIsEditModalOpen(open); if (!open) setTargetEditFarm(null); }}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Edit {targetEditFarm?.name || 'Farm'}</DialogTitle>
            <DialogDescription>
              Update your farm plot's details below.
            </DialogDescription>
          </DialogHeader>
          <form onSubmit={handleEditSubmit} className="grid gap-4 py-4 max-h-[70vh] overflow-y-auto pr-2">
            <div>
              <label htmlFor="edit_name" className="mb-1 block text-[11px] font-medium text-muted-foreground">Name *</label>
              <input
                id="edit_name" maxLength={255}
                value={editFormData.name}
                onChange={(e) => { setEditFormData({...editFormData, name: e.target.value}); if (editFormErrors.name) setEditFormErrors(p => ({...p, name: ""})); }}
                className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${editFormErrors.name ? "border-destructive" : "border-input"}`}
              />
              {editFormErrors.name && <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive"><AlertCircle className="h-3 w-3" />{editFormErrors.name}</p>}
            </div>
            <div>
              <label htmlFor="edit_areaAcres" className="mb-1 block text-[11px] font-medium text-muted-foreground">Area (Acres) *</label>
              <input
                type="number" step="any" id="edit_areaAcres"
                value={editFormData.areaAcres}
                onChange={(e) => { setEditFormData({...editFormData, areaAcres: e.target.value}); if (editFormErrors.areaAcres) setEditFormErrors(p => ({...p, areaAcres: ""})); }}
                className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${editFormErrors.areaAcres ? "border-destructive" : "border-input"}`}
              />
              {editFormErrors.areaAcres && <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive"><AlertCircle className="h-3 w-3" />{editFormErrors.areaAcres}</p>}
            </div>

            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Water Resources</label>
              <div className="grid grid-cols-2 gap-2">
                {["Borewell", "Canal", "River", "Rainfed", "Drip System", "Sprinklers"].map(item => (
                  <button
                    type="button"
                    key={item}
                    onClick={() => toggleEditWaterResource(item)}
                    className={`flex items-center gap-2 rounded-xl border px-3 py-2 text-xs font-medium transition-all ${
                      (Array.isArray(editFormData.waterResources) ? editFormData.waterResources : []).includes(item)
                        ? "border-primary bg-primary/10 text-primary shadow-[0_0_15px_-5px_var(--color-primary)]"
                        : "border-border text-muted-foreground hover:border-primary/50"
                    }`}
                  >
                    <div className={`h-3 w-3 rounded-full border flex items-center justify-center ${(Array.isArray(editFormData.waterResources) ? editFormData.waterResources : []).includes(item) ? "border-primary bg-primary" : "border-muted-foreground"}`}>
                      {(Array.isArray(editFormData.waterResources) ? editFormData.waterResources : []).includes(item) && <CheckCircle2 className="h-2 w-2 text-background" />}
                    </div>
                    {item}
                  </button>
                ))}
              </div>
            </div>
            <div>
              <label htmlFor="edit_waterLevel" className="mb-1 block text-[11px] font-medium text-muted-foreground">Water Availability</label>
              <select id="edit_waterLevel" value={editFormData.waterLevel} onChange={(e) => setEditFormData({...editFormData, waterLevel: e.target.value})} className="w-full rounded-xl border border-input bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50">
                <option value="low">Low</option>
                <option value="medium">Medium</option>
                <option value="high">High</option>
              </select>
            </div>
            
            <div>
              <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Soil Test Data (Optional)</label>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <label htmlFor="edit_ph" className="mb-1 block text-[10px] text-muted-foreground">pH (0-14)</label>
                  <input type="number" step="any" min={FARM_LIMITS.ph[0]} max={FARM_LIMITS.ph[1]} id="edit_ph" value={editFormData.ph} onChange={(e) => { setEditFormData({...editFormData, ph: e.target.value}); if (editFormErrors.ph) setEditFormErrors(p => ({...p, ph: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${editFormErrors.ph ? "border-destructive" : "border-input"}`} />
                  {editFormErrors.ph && <p className="mt-1 text-[10px] text-destructive">{editFormErrors.ph}</p>}
                </div>
                <div>
                  <label htmlFor="edit_ec" className="mb-1 block text-[10px] text-muted-foreground">EC (0-20 dS/m)</label>
                  <input type="number" step="any" min={FARM_LIMITS.ec[0]} max={FARM_LIMITS.ec[1]} id="edit_ec" value={editFormData.ec} onChange={(e) => { setEditFormData({...editFormData, ec: e.target.value}); if (editFormErrors.ec) setEditFormErrors(p => ({...p, ec: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${editFormErrors.ec ? "border-destructive" : "border-input"}`} />
                  {editFormErrors.ec && <p className="mt-1 text-[10px] text-destructive">{editFormErrors.ec}</p>}
                </div>
                <div>
                  <label htmlFor="edit_nitrogen" className="mb-1 block text-[10px] text-muted-foreground">Nitrogen (0-999 kg/ha)</label>
                  <input type="number" min={FARM_LIMITS.nitrogen[0]} max={FARM_LIMITS.nitrogen[1]} id="edit_nitrogen" value={editFormData.nitrogen} onChange={(e) => { setEditFormData({...editFormData, nitrogen: e.target.value}); if (editFormErrors.nitrogen) setEditFormErrors(p => ({...p, nitrogen: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${editFormErrors.nitrogen ? "border-destructive" : "border-input"}`} />
                  {editFormErrors.nitrogen && <p className="mt-1 text-[10px] text-destructive">{editFormErrors.nitrogen}</p>}
                </div>
                <div>
                  <label htmlFor="edit_phosphorus" className="mb-1 block text-[10px] text-muted-foreground">Phosphorus (0-999 kg/ha)</label>
                  <input type="number" min={FARM_LIMITS.phosphorus[0]} max={FARM_LIMITS.phosphorus[1]} id="edit_phosphorus" value={editFormData.phosphorus} onChange={(e) => { setEditFormData({...editFormData, phosphorus: e.target.value}); if (editFormErrors.phosphorus) setEditFormErrors(p => ({...p, phosphorus: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${editFormErrors.phosphorus ? "border-destructive" : "border-input"}`} />
                  {editFormErrors.phosphorus && <p className="mt-1 text-[10px] text-destructive">{editFormErrors.phosphorus}</p>}
                </div>
                <div>
                  <label htmlFor="edit_potassium" className="mb-1 block text-[10px] text-muted-foreground">Potassium (0-999 kg/ha)</label>
                  <input type="number" min={FARM_LIMITS.potassium[0]} max={FARM_LIMITS.potassium[1]} id="edit_potassium" value={editFormData.potassium} onChange={(e) => { setEditFormData({...editFormData, potassium: e.target.value}); if (editFormErrors.potassium) setEditFormErrors(p => ({...p, potassium: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${editFormErrors.potassium ? "border-destructive" : "border-input"}`} />
                  {editFormErrors.potassium && <p className="mt-1 text-[10px] text-destructive">{editFormErrors.potassium}</p>}
                </div>
                <div>
                  <label htmlFor="edit_carbon" className="mb-1 block text-[10px] text-muted-foreground">Organic Carbon (0-10 %)</label>
                  <input type="number" step="any" min={FARM_LIMITS.organicCarbon[0]} max={FARM_LIMITS.organicCarbon[1]} id="edit_carbon" value={editFormData.organicCarbon} onChange={(e) => { setEditFormData({...editFormData, organicCarbon: e.target.value}); if (editFormErrors.organicCarbon) setEditFormErrors(p => ({...p, organicCarbon: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${editFormErrors.organicCarbon ? "border-destructive" : "border-input"}`} />
                  {editFormErrors.organicCarbon && <p className="mt-1 text-[10px] text-destructive">{editFormErrors.organicCarbon}</p>}
                </div>
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button disabled={isEditSubmitting} type="submit" className="w-full rounded-xl bg-primary py-2.5 text-xs font-semibold text-primary-foreground transition-transform hover:scale-[1.02]">
                {isEditSubmitting ? "Saving..." : "Save changes"}
              </button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={isAnalyzeOpen} onOpenChange={setIsAnalyzeOpen}>
        <DialogContent className="sm:max-w-[425px]">
          <DialogHeader>
            <DialogTitle>Analyze Crop Plan</DialogTitle>
            <DialogDescription>
              Confirm your farm elements and set your planting parameters.
            </DialogDescription>
          </DialogHeader>
          {analyzingFarm && (
            <div className="py-2 space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="col-span-2">
                  <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Date to Plant *</label>
                  <input type="date" min={initialDate} value={analysisDate} onChange={(e) => {
                    const newDate = e.target.value;
                    setAnalysisDate(newDate);
                    if (analysisFormErrors.date) setAnalysisFormErrors(p => ({...p, date: ""}));
                    if (newDate) {
                      const month = new Date(newDate).getMonth() + 1;
                      if (month >= 6 && month <= 9) setAnalysisSeason("kharif");
                      else if (month >= 10 || month <= 2) setAnalysisSeason("rabi");
                      else if (month >= 3 && month <= 5) setAnalysisSeason("zaid");
                    }
                  }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${analysisFormErrors.date ? "border-destructive" : "border-input"}`} />
                  {analysisFormErrors.date && <p className="mt-1 text-[10px] text-destructive">{analysisFormErrors.date}</p>}
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Season</label>
                  <select value={analysisSeason} disabled className="w-full rounded-xl border border-input bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 opacity-70 cursor-not-allowed">
                    <option value="kharif">Kharif</option>
                    <option value="rabi">Rabi</option>
                    <option value="zaid">Zaid</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-[11px] font-medium text-muted-foreground">Irrigation Type</label>
                  <select value={analysisIrrigation} onChange={(e) => setAnalysisIrrigation(e.target.value)} className="w-full rounded-xl border border-input bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50">
                    <option value="Drip">Drip</option>
                    <option value="Sprinkler">Sprinkler</option>
                    <option value="Flood">Flood</option>
                    <option value="Manual">Manual</option>
                  </select>
                </div>
              </div>
              <h4 className="text-[12px] font-semibold text-foreground border-t border-border pt-4">Farm Elements (Required)</h4>
              <div className="grid grid-cols-2 gap-3 text-sm">
                <div>
                  <label htmlFor="analyze_nitrogen" className="mb-1 block text-[11px] font-medium text-muted-foreground">Nitrogen (kg/ha) *</label>
                  <input type="number" min={FARM_LIMITS.nitrogen[0]} max={FARM_LIMITS.nitrogen[1]} id="analyze_nitrogen" value={analysisFormData.nitrogen} onChange={(e) => { setAnalysisFormData({...analysisFormData, nitrogen: e.target.value}); if (analysisFormErrors.nitrogen) setAnalysisFormErrors(p => ({...p, nitrogen: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${analysisFormErrors.nitrogen ? "border-destructive" : "border-input"}`} />
                  {analysisFormErrors.nitrogen && <p className="mt-1 text-[10px] text-destructive">{analysisFormErrors.nitrogen}</p>}
                </div>
                <div>
                  <label htmlFor="analyze_phosphorus" className="mb-1 block text-[11px] font-medium text-muted-foreground">Phosphorus (kg/ha) *</label>
                  <input type="number" min={FARM_LIMITS.phosphorus[0]} max={FARM_LIMITS.phosphorus[1]} id="analyze_phosphorus" value={analysisFormData.phosphorus} onChange={(e) => { setAnalysisFormData({...analysisFormData, phosphorus: e.target.value}); if (analysisFormErrors.phosphorus) setAnalysisFormErrors(p => ({...p, phosphorus: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${analysisFormErrors.phosphorus ? "border-destructive" : "border-input"}`} />
                  {analysisFormErrors.phosphorus && <p className="mt-1 text-[10px] text-destructive">{analysisFormErrors.phosphorus}</p>}
                </div>
                <div>
                  <label htmlFor="analyze_potassium" className="mb-1 block text-[11px] font-medium text-muted-foreground">Potassium (kg/ha) *</label>
                  <input type="number" min={FARM_LIMITS.potassium[0]} max={FARM_LIMITS.potassium[1]} id="analyze_potassium" value={analysisFormData.potassium} onChange={(e) => { setAnalysisFormData({...analysisFormData, potassium: e.target.value}); if (analysisFormErrors.potassium) setAnalysisFormErrors(p => ({...p, potassium: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${analysisFormErrors.potassium ? "border-destructive" : "border-input"}`} />
                  {analysisFormErrors.potassium && <p className="mt-1 text-[10px] text-destructive">{analysisFormErrors.potassium}</p>}
                </div>
                <div>
                  <label htmlFor="analyze_ph" className="mb-1 block text-[11px] font-medium text-muted-foreground">pH Level *</label>
                  <input type="number" step="any" min={FARM_LIMITS.ph[0]} max={FARM_LIMITS.ph[1]} id="analyze_ph" value={analysisFormData.ph} onChange={(e) => { setAnalysisFormData({...analysisFormData, ph: e.target.value}); if (analysisFormErrors.ph) setAnalysisFormErrors(p => ({...p, ph: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${analysisFormErrors.ph ? "border-destructive" : "border-input"}`} />
                  {analysisFormErrors.ph && <p className="mt-1 text-[10px] text-destructive">{analysisFormErrors.ph}</p>}
                </div>
                <div>
                  <label htmlFor="analyze_carbon" className="mb-1 block text-[11px] font-medium text-muted-foreground">Organic Carbon (%)</label>
                  <input type="number" step="any" min={FARM_LIMITS.organicCarbon[0]} max={FARM_LIMITS.organicCarbon[1]} id="analyze_carbon" placeholder="Optional" value={analysisFormData.organicCarbon} onChange={(e) => { setAnalysisFormData({...analysisFormData, organicCarbon: e.target.value}); if (analysisFormErrors.organicCarbon) setAnalysisFormErrors(p => ({...p, organicCarbon: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${analysisFormErrors.organicCarbon ? "border-destructive" : "border-input"}`} />
                  {analysisFormErrors.organicCarbon && <p className="mt-1 text-[10px] text-destructive">{analysisFormErrors.organicCarbon}</p>}
                </div>
                <div>
                  <label htmlFor="analyze_ec" className="mb-1 block text-[11px] font-medium text-muted-foreground">EC (dS/m)</label>
                  <input type="number" step="any" min={FARM_LIMITS.ec[0]} max={FARM_LIMITS.ec[1]} id="analyze_ec" placeholder="Optional" value={analysisFormData.ec} onChange={(e) => { setAnalysisFormData({...analysisFormData, ec: e.target.value}); if (analysisFormErrors.ec) setAnalysisFormErrors(p => ({...p, ec: ""})); }} className={`w-full rounded-xl border bg-secondary/40 px-3.5 py-2 text-sm outline-none transition-colors focus:border-primary/50 ${analysisFormErrors.ec ? "border-destructive" : "border-input"}`} />
                  {analysisFormErrors.ec && <p className="mt-1 text-[10px] text-destructive">{analysisFormErrors.ec}</p>}
                </div>
              </div>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => {
                    setIsAnalyzeOpen(false);
                    openEditModal(analyzingFarm);
                  }}
                  className="rounded-xl border border-border px-4 py-2.5 text-xs font-semibold text-muted-foreground hover:bg-secondary"
                >
                  Edit Elements
                </button>
                <button
                  onClick={runAnalysisAndSave}
                  disabled={isAnalyzing}
                  className="rounded-xl bg-cyan px-4 py-2.5 text-xs font-semibold text-cyan-foreground transition-transform hover:scale-[1.02] flex items-center justify-center min-w-[120px]"
                >
                  {isAnalyzing ? "Processing..." : "Recommend"}
                </button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

function InfoChip({ icon: Icon, label, value }) {
  return (
    <div className="rounded-xl bg-secondary/40 px-3 py-2">
      <div className="flex items-center gap-1 text-[10px] uppercase tracking-widest text-muted-foreground">
        <Icon className="h-3 w-3" /> {label}
      </div>
      <div className="mt-0.5 truncate text-[11px] font-medium">{value}</div>
    </div>
  );
}
