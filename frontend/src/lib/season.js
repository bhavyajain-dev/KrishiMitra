/**
 * Current Indian cropping season, using the same rule as the crop
 * recommender (Recommendations page): June–October is Kharif, otherwise Rabi.
 * Rabi spans two calendar years (e.g. Nov 2026 – Mar 2027 → "Rabi 2026–27").
 */
export function currentSeason(date = new Date()) {
  const month = date.getMonth(); // 0 = January
  const year = date.getFullYear();
  if (month >= 5 && month <= 9) {
    return { key: "kharif", label: `Kharif ${year}` };
  }
  const start = month >= 10 ? year : year - 1;
  return { key: "rabi", label: `Rabi ${start}–${String(start + 1).slice(-2)}` };
}
