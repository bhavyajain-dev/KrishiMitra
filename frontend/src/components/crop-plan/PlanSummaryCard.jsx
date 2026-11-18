import React from 'react';
import { ClipboardList } from 'lucide-react';

export function PlanSummaryCard({ activePlan, durationDays, harvestDate, farmName, advancedPredictions }) {
  if (!activePlan) return null;

  const data = [
    { label: "Crop", value: activePlan.cropName || "Not Available" },
    { label: "Farm Name", value: farmName || "Not Available" },
    { label: "Area", value: activePlan.areaAcres ? `${activePlan.areaAcres} ${Number(activePlan.areaAcres) === 1 ? "acre" : "acres"}` : "Not Available" },
    { label: "Season", value: activePlan.season || "Not Available" },
    { label: "Harvest Date", value: harvestDate || "Not Available" },
    { label: "Crop Duration", value: durationDays ? `${durationDays} days` : "Not Available" },
  ];

  if (advancedPredictions?.yield) {
    data.push({ label: "Yield prediction (ML model)", value: `${advancedPredictions.yield} t/ha` });
  }
  if (advancedPredictions?.fertilizer) {
    data.push({ label: "Recommended fertilizer", value: advancedPredictions.fertilizer });
  }
  if (advancedPredictions?.irrigation) {
    data.push({ label: "Irrigation need", value: advancedPredictions.irrigation });
  }

  return (
    <div className="glass rounded-2xl p-5 shadow-sm h-full flex flex-col">
      <div className="flex items-center gap-2 mb-4">
        <ClipboardList className="w-4 h-4 text-primary" />
        <h3 className="text-sm font-semibold text-foreground">Plan Summary</h3>
      </div>
      <dl className="space-y-3 flex-1 overflow-y-auto pr-2 scrollbar-thin">
        {data.map((item, idx) => (
          <div key={idx} className="flex justify-between items-center text-xs border-b border-border/50 pb-2 last:border-0 last:pb-0">
            <dt className="text-muted-foreground">{item.label}</dt>
            <dd className="font-semibold text-foreground text-right">{item.value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
