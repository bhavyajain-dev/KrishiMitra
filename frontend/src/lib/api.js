/**
 * Centralized API configuration for the KrishiMitra frontend.
 *
 * Single source of truth for the backend API base URL. Resolution order
 * (identical to the behaviour previously inlined across every route/component):
 *
 *   1. import.meta.env.VITE_API_URL   — set this for any deployed build
 *                                        (e.g. https://<backend>.onrender.com/api)
 *   2. http://<current-host>:5001/api — local development in the browser,
 *                                        so the API follows whatever host the
 *                                        dev frontend is opened on
 *   3. http://localhost:5001/api      — non-browser / SSR fallback
 *
 * The local development port is 5001 (Django dev server). Production MUST set
 * VITE_API_URL — the localhost fallback is insecure (plain http) off-device.
 */

const LOCAL_API_FALLBACK = "http://localhost:5001/api";

export function getApiBaseUrl() {
  const configured = import.meta.env.VITE_API_URL;
  if (configured) return configured;
  if (typeof window !== "undefined") {
    return `http://${window.location.hostname}:5001/api`;
  }
  return LOCAL_API_FALLBACK;
}

/** Resolved API base URL (no trailing slash). */
export const API_URL = getApiBaseUrl();

/** JWT access token stored at login, or null if signed out. */
export function getAuthToken() {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem("krishimitra_token");
  } catch {
    return null;
  }
}

/**
 * Authorization header object for authenticated requests.
 * Returns {} when no token is present so callers can spread it unconditionally.
 */
export function authHeaders() {
  const token = getAuthToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/**
 * Optional thin fetch wrapper that prepends the API base URL and attaches the
 * auth header. `path` should start with "/". Provided for future use; existing
 * callers that construct requests manually continue to work unchanged.
 */
export function apiFetch(path, options = {}) {
  const { auth = true, headers, ...rest } = options;
  const url = path.startsWith("http") ? path : `${API_URL}${path}`;
  return fetch(url, {
    ...rest,
    headers: {
      ...(auth ? authHeaders() : {}),
      ...headers,
    },
  });
}

/**
 * Weather for a location, with a browser fallback.
 *
 * Normally the backend fetches the forecast from Open-Meteo. On shared hosting
 * the server's IP can be rate-limited by Open-Meteo; the backend then replies
 * 502 with `fallbackUrl`. In that case the browser fetches the forecast itself
 * (the visitor's own IP) and sends it to the backend, which formats it and adds
 * alerts exactly as usual. Returns a fetch Response either way.
 */
export async function fetchWeather(lat, lon, init = {}) {
  const res = await fetch(`${API_URL}/weather?latitude=${lat}&longitude=${lon}`, init);
  if (res.ok) return res;

  let fallbackUrl;
  try {
    fallbackUrl = (await res.clone().json()).fallbackUrl;
  } catch {
    return res;
  }
  if (typeof fallbackUrl !== "string" || !fallbackUrl.startsWith("https://api.open-meteo.com/")) {
    return res;
  }
  try {
    const raw = await fetch(fallbackUrl);
    if (!raw.ok) return res;
    return await fetch(`${API_URL}/weather`, {
      method: "POST",
      headers: { ...(init.headers || {}), "Content-Type": "application/json" },
      body: JSON.stringify({ raw: await raw.json() }),
    });
  } catch {
    return res;
  }
}
