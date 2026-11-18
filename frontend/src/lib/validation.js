/**
 * Input limits shared by forms. Keep in sync with the backend
 * (backend/krishi_core/serializers.py FARM_LIMITS and views._clean_phone).
 */

// Soil Health Card ranges (N, P, K in kg/ha). Values outside are typos.
export const FARM_LIMITS = {
  areaAcres: [0.01, 10000],
  ph: [3, 11],
  nitrogen: [0, 1000],
  phosphorus: [0, 300],
  potassium: [0, 1500],
  organicCarbon: [0, 10],
  ec: [0, 20],
};

/** 10-digit Indian mobile number (accepts +91 / 0 prefix and spaces). */
export function normalizeIndianPhone(raw) {
  let digits = String(raw ?? "").replace(/[\s\-()]/g, "");
  if (digits.startsWith("+91")) digits = digits.slice(3);
  else if (digits.startsWith("91") && digits.length === 12) digits = digits.slice(2);
  else if (digits.startsWith("0") && digits.length === 11) digits = digits.slice(1);
  return /^[6-9]\d{9}$/.test(digits) ? digits : null;
}

const FIELD_LABELS = {
  areaAcres: "Area", ph: "pH", nitrogen: "Nitrogen", phosphorus: "Phosphorus", potassium: "Potassium",
  organicCarbon: "Organic carbon", ec: "EC", name: "Name", farm: "Farm", amountRs: "Amount",
  label: "Description", category: "Category", cropName: "Crop", sowingDate: "Sowing date",
  expectedHarvestDate: "Harvest date", location: "Location", waterResources: "Water source",
  non_field_errors: "",
};

/**
 * Turn an API error body into one readable sentence.
 * Handles {message}, {error}, {detail} and DRF field errors {field: ["..."]}.
 */
export function apiErrorMessage(data, fallback = "Something went wrong. Please try again.") {
  if (!data || typeof data !== "object") return fallback;
  for (const key of ["message", "error", "detail"]) {
    if (typeof data[key] === "string" && data[key]) return data[key];
  }
  const parts = Object.entries(data)
    .filter(([, v]) => v)
    .map(([field, v]) => {
      const text = Array.isArray(v) ? v.join(" ") : typeof v === "string" ? v : "";
      if (!text) return "";
      const label = FIELD_LABELS[field] ?? field;
      return label ? `${label}: ${text}` : text;
    })
    .filter(Boolean);
  return parts.length ? parts.join(" ") : fallback;
}

/** Same rules as the backend password validators. Returns an error string or null. */
export const validatePasswordPolicy = (pwd) => {
  if (!pwd || pwd.length < 8) {
    return "Password must be at least 8 characters long.";
  }
  if (pwd.length > 128) {
    return "Password cannot exceed 128 characters.";
  }
  if (!/[A-Z]/.test(pwd)) {
    return "Password must contain at least one uppercase letter (A-Z).";
  }
  if (!/[a-z]/.test(pwd)) {
    return "Password must contain at least one lowercase letter (a-z).";
  }
  if (!/[0-9]/.test(pwd)) {
    return "Password must contain at least one digit (0-9).";
  }
  if (!/[!@#$%^&*(),.?":{}|<>\-_+=\[\]\\/'~`;]/.test(pwd)) {
    return "Password must contain at least one special character (e.g. !@#$%^&*).";
  }
  const lower = pwd.toLowerCase();
  const base = lower.replace(/[\d!@#$%^&*(),.?":{}|<>\-_+=\[\]\\/'~`;]+$/, "");
  const commonWords = ["password", "password123", "admin", "admin123", "qwerty", "123456", "12345678", "welcome", "welcome123", "letmein", "krishimitra"];
  if (commonWords.includes(lower) || commonWords.includes(base)) {
    return "Password is too common or easily guessable. Please choose a more unique password.";
  }
  return null;
};
