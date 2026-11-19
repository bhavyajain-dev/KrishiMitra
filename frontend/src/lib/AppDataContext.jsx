import { API_URL } from "@/lib/api";
import { createContext, useContext, useState, useEffect, useCallback } from "react";
import { useRouter } from "@tanstack/react-router";

const AppDataContext = createContext();


export function AppDataProvider({ children }) {
  const router = useRouter();
  const [token, setToken] = useState(() => {
    if (typeof window !== "undefined") return localStorage.getItem("krishimitra_token");
    return null;
  });
  
  const [userProfile, setUserProfile] = useState({ name: "Guest User", role: "farmer" });

  // --- Saved user location: city, state, district, lat, lon ---
  // This is the single source of truth that Weather and Market pages auto-fill from.
  const [userLocation, setUserLocationState] = useState(() => {
    try {
      const saved = localStorage.getItem("user_location");
      return saved ? JSON.parse(saved) : null;
    } catch { return null; }
  });

  const setUserLocation = (loc) => {
    setUserLocationState(loc);
    if (loc) localStorage.setItem("user_location", JSON.stringify(loc));
    else localStorage.removeItem("user_location");
  };

  // --- Multi-farm state ---
  const [farms, setFarms] = useState([]); // full list of the user's farms from the backend
  const [activeFarmId, setActiveFarmId] = useState(() => {
    if (typeof window !== "undefined") return localStorage.getItem("active_farm_id");
    return null;
  });

  // Live weather for the farm being viewed. Set by the dashboard and the
  // Weather page; stamped with the farm (and its coordinates) it belongs to,
  // so switching farms or editing a farm's location never shows another
  // place's weather on the dashboard or in AI Mitra.
  const [weatherSnapshotRaw, setWeatherSnapshotRaw] = useState(null);
  const [alerts, setAlerts] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);

  const logout = () => {
    setToken(null);
    setUserProfile({ name: "Guest User", role: "farmer" });
    setUserLocationState(null);
    setFarms([]);
    setActiveFarmId(null);
    setWeatherSnapshotRaw(null);
    setAlerts([]);
    setNotifications([]);

    localStorage.removeItem("krishimitra_token");
    localStorage.removeItem("krishimitra_refresh_token");
    localStorage.removeItem("user_location");
    localStorage.removeItem("active_farm_id");
    router.navigate({ to: "/auth" });
  };
  // Derived: the farm object currently selected. Falls back to the first farm
  // if nothing is selected yet (e.g. right after login).
  // Support both Django integer `id` and MongoDB `_id`
  const activeFarm = farms.find((f) => String(f._id) === String(activeFarmId) || String(f.id) === String(activeFarmId)) || farms[0] || null;

  // Alerts for the farm being viewed (plus any not tied to a farm), and the
  // ones still open. Badges and counts use the open ones only.
  const viewingFarmKey = activeFarm ? String(activeFarm._id || activeFarm.id) : null;
  const farmAlerts = alerts.filter((a) => a.farm == null || String(a.farm) === viewingFarmKey);
  const openFarmAlerts = farmAlerts.filter((a) => (a.status || "active") === "active");

  const activeFarmWeatherKey = activeFarm
    ? `${activeFarm._id || activeFarm.id}|${activeFarm.location?.lat ?? ""}|${activeFarm.location?.lon ?? ""}`
    : null;
  const weatherSnapshot =
    weatherSnapshotRaw && activeFarmWeatherKey && weatherSnapshotRaw.farmKey === activeFarmWeatherKey
      ? weatherSnapshotRaw
      : null;
  // Callers pass only weather for the viewing farm's own location.
  const setWeatherSnapshot = useCallback(
    (snap) => setWeatherSnapshotRaw(snap ? { ...snap, farmKey: activeFarmWeatherKey } : null),
    [activeFarmWeatherKey]
  );

  // Persist the selection so it survives a refresh
  useEffect(() => {
    if (activeFarmId) localStorage.setItem("active_farm_id", activeFarmId);
  }, [activeFarmId]);

  // If farms load and nothing is selected yet (or the selected id no longer exists), default to the first farm
  useEffect(() => {
    if (farms.length > 0 && !farms.find((f) => String(f._id) === String(activeFarmId) || String(f.id) === String(activeFarmId))) {
      setActiveFarmId(farms[0]._id || String(farms[0].id));
    }
  }, [farms]);

  useEffect(() => {
    if (token) {
      localStorage.setItem("krishimitra_token", token);
      fetchDashboardData();
    } else {
      localStorage.removeItem("krishimitra_token");
      setIsLoading(false);
    }
  }, [token]);

  const fetchDashboardData = async () => {
    try {
      // 1. Fetch Me
      const meRes = await fetch(`${API_URL}/auth/me`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (meRes.status === 401) {
        logout();
        return;
      }
      const meData = await meRes.json();
      if (meData.user) {
        setUserProfile({
          name: `${meData.user.firstName} ${meData.user.lastName || ""}`.trim(),
          email: meData.user.email,
          role: meData.user.role,
          farmingMode: meData.user.farmingMode,
          phone: meData.user.phone,
          hasPassword: meData.user.hasPassword !== false,
        });
        if (meData.user.location && typeof meData.user.location === "string") {
          setUserLocation(prev => ({
            ...(typeof prev === "object" ? prev : {}),
            query: meData.user.location,
            address: meData.user.location,
            source: "profile",
          }));
        } else if (meData.user.location && (meData.user.location.address || meData.user.location.query)) {
          setUserLocation(prev => ({
            ...(typeof prev === "object" ? prev : {}),
            ...(typeof meData.user.location === "object" ? meData.user.location : {}),
            query: meData.user.location.query || meData.user.location.address,
            address: meData.user.location.address || meData.user.location.query,
          }));
        }
      }

      // 2. Fetch ALL farms — no more grabbing just farms[0]
      const farmsRes = await fetch(`${API_URL}/farms`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      const farmsData = await farmsRes.json();
      // Normalize: Django uses `id`, frontend uses `_id`. Support both.
      const normalizedFarms = (Array.isArray(farmsData) ? farmsData : []).map(f => ({
        ...f,
        _id: f._id || String(f.id),
        id: f.id || f._id,
      }));
      setFarms(normalizedFarms);


      // 4. Fetch Alerts and Notifications
      const [alRes, noRes] = await Promise.all([
        fetch(`${API_URL}/alerts`, { headers: { Authorization: `Bearer ${token}` } }),
        fetch(`${API_URL}/notifications`, { headers: { Authorization: `Bearer ${token}` } })
      ]);
      const [alData, noData] = await Promise.all([alRes.json(), noRes.json()]);
      setAlerts(Array.isArray(alData) ? alData : []);
      setNotifications(Array.isArray(noData) ? noData : []);

      setLoadError(null);
    } catch (err) {
      console.error("Failed to load dashboard data", err);
      setLoadError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  // Helper for farm-scoped GET requests, e.g.:
  //   const soilReports = await fetchScoped("/soil-reports")
  // automatically appends ?farm=<activeFarmId>
  const fetchScoped = useCallback(async (path) => {
    if (!activeFarmId) return [];
    const res = await fetch(`${API_URL}${path}?farm=${activeFarmId}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (res.status === 401) {
      return [];
    }
    return res.json();
  }, [activeFarmId, token]);

  // Helper for farm-scoped POST requests — auto-injects `farm: activeFarmId`
  // so new records (crop plans, expenses) are always tagged
  // to whichever farm is currently selected.
  const postScoped = useCallback(async (path, body) => {
    const res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      // An explicit farm in the body wins (e.g. analysing a farm that is not
      // the active one); otherwise tag the record with the active farm.
      body: JSON.stringify({ ...body, farm: body?.farm ?? activeFarmId }),
    });
    if (res.status === 401) {
      return { error: "Unauthorized" };
    }
    return res.json();
  }, [activeFarmId, token]);

  // Generic PATCH helper (not farm-scoped — used for updating a specific
  // record by id, e.g. marking a notification/alert read).
  const patchRecord = useCallback(async (path, body) => {
    const res = await fetch(`${API_URL}${path}`, {
      method: "PATCH",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify(body),
    });
    if (res.status === 401) {
      return { error: "Unauthorized" };
    }
    return res.json();
  }, [token]);

  const login = (newToken) => {
    // Start every login clean: never show the previous user's location or
    // selected farm (e.g. if their session expired without a logout).
    setUserLocation(null);
    setActiveFarmId(null);
    localStorage.removeItem("active_farm_id");
    setToken(newToken);
  };

  return (
    <AppDataContext.Provider
      value={{
        userProfile,
        userLocation,
        setUserLocation,
        farms,
        activeFarm,
        activeFarmId,
        setActiveFarmId,

        weatherSnapshot,
        setWeatherSnapshot,
        farmAlerts,
        openFarmAlerts,
        alerts,
        setAlerts,
        notifications,
        setNotifications,
        token,
        login,
        logout,
        isLoading,
        loadError,
        fetchDashboardData,
        fetchScoped,
        postScoped,
        patchRecord,
      }}
    >
      {children}
    </AppDataContext.Provider>
  );
}

export function useAppData() {
  return useContext(AppDataContext);
}
