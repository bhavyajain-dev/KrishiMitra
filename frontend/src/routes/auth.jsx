import { API_URL } from "@/lib/api";
import { Link, createFileRoute, useNavigate, redirect } from "@tanstack/react-router";
import { useState, useEffect, useRef } from "react";
import {
  Lock,
  Mail,
  Phone,
  UserRound,
  ShieldCheck,
  BarChart3,
  CheckCircle2,
  AlertCircle,
  Eye,
  EyeOff,
  Loader2,
  KeyRound,
  Sparkles,
  ArrowLeft,
  TrendingUp,
} from "lucide-react";
import { GoogleOAuthProvider, useGoogleOAuth } from "@react-oauth/google";

import { BrandMark, ThemeToggle } from "@/components/app/AppShell";
import { useAppData } from "@/lib/AppDataContext";
import { useTheme } from "@/components/theme-provider";

export const Route = createFileRoute("/auth")({
  validateSearch: (search) => ({
    mode: typeof search?.mode === "string" ? search.mode : undefined,
  }),
  beforeLoad: () => {
    if (typeof window !== "undefined") {
      const token = localStorage.getItem("krishimitra_token");
      if (token) {
        throw redirect({ to: "/dashboard" });
      }
    }
  },
  head: () => ({
    meta: [
      { title: "Sign in — KrishiMitra" },
      {
        name: "description",
        content: "Sign in or create your KrishiMitra account for AI-driven farming intelligence.",
      },
    ],
  }),
  component: AuthPageWrapper,
});

// Email syntax validator requiring valid local part, @, domain with dot and at least 2 alpha char TLD
const isValidEmail = (email) => {
  if (!email || typeof email !== "string") return false;
  const cleaned = email.trim();
  return /^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}$/.test(cleaned);
};

// Password policy validator:
// - Between 8 and 128 characters
// - At least one uppercase letter (A-Z)
// - At least one lowercase letter (a-z)
// - At least one digit (0-9)
// - At least one special character
const validatePasswordPolicy = (pwd) => {
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

const getApiUrl = () => API_URL;

// Resilient fetch wrapper with client-side abort timeout.
// 60 s: the free Render backend sleeps when idle and takes ~15-50 s to wake,
// so a shorter timeout made the first sign-in/sign-up after a quiet period fail.
async function fetchWithTimeout(url, options = {}, timeoutMs = 60000) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    return response;
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("Request timed out. Please check your internet connection or try again.");
    }
    throw err;
  } finally {
    clearTimeout(id);
  }
}

// Helper to mask email (e.g. b***9@gmail.com)
function maskEmail(email) {
  if (!email || !email.includes("@")) return email;
  const [local, domain] = email.split("@");
  if (local.length <= 2) return `${local[0]}***@${domain}`;
  return `${local[0]}***${local[local.length - 1]}@${domain}`;
}

// Google SVG Icon for instant placeholder rendering
function GoogleIcon({ className = "h-4 w-4" }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
      <path
        d="M23.745 12.27c0-.7-.06-1.4-.19-2.07H12v4.51h6.6c-.29 1.52-1.14 2.82-2.4 3.68v3.05h3.88c2.27-2.09 3.66-5.17 3.66-9.17z"
        fill="#4285F4"
      />
      <path
        d="M12 24c3.24 0 5.95-1.08 7.93-2.91l-3.88-3.05c-1.08.72-2.45 1.16-4.05 1.16-3.12 0-5.77-2.1-6.72-4.93H1.26v3.15C3.25 21.36 7.33 24 12 24z"
        fill="#34A853"
      />
      <path
        d="M5.28 14.27c-.25-.72-.38-1.49-.38-2.27s.13-1.55.38-2.27V6.58H1.26C.46 8.16 0 9.94 0 12s.46 3.84 1.26 5.42l4.02-3.15z"
        fill="#FBBC05"
      />
      <path
        d="M12 4.75c1.77 0 3.35.61 4.6 1.8l3.42-3.42C17.95 1.19 15.24 0 12 0 7.33 0 3.25 2.64 1.26 6.58l4.02 3.15c.95-2.83 3.6-4.98 6.72-4.98z"
        fill="#EA4335"
      />
    </svg>
  );
}

// useGoogleOAuth() throws outside <GoogleOAuthProvider>, and __root only adds
// that provider when VITE_GOOGLE_CLIENT_ID is set. Check first, so a missing
// client ID shows a note instead of crashing the whole sign-in page.
function GoogleAuthSection(props) {
  if (!import.meta.env.VITE_GOOGLE_CLIENT_ID) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface-2 p-3 text-center text-xs text-muted-foreground min-h-[40px] flex items-center justify-center">
        Google Sign-In is not configured on this site.
      </div>
    );
  }
  return <GoogleAuthSectionInner {...props} />;
}

// Reusable Google Auth Section with Idempotent Initialization and Zero Layout Shifts
function GoogleAuthSectionInner({ onSuccess, onError, disabled }) {
  const { clientId, scriptLoadedSuccessfully } = useGoogleOAuth();
  const containerRef = useRef(null);
  const renderedRef = useRef(false);
  const onSuccessRef = useRef(onSuccess);
  const onErrorRef = useRef(onError);

  useEffect(() => {
    onSuccessRef.current = onSuccess;
  }, [onSuccess]);

  useEffect(() => {
    onErrorRef.current = onError;
  }, [onError]);

  useEffect(() => {
    if (!scriptLoadedSuccessfully || !window.google?.accounts?.id || !containerRef.current) {
      return;
    }

    if (renderedRef.current && containerRef.current.hasChildNodes()) {
      return;
    }

    try {
      window.google.accounts.id.initialize({
        client_id: clientId,
        callback: (credentialResponse) => {
          if (credentialResponse?.credential) {
            onSuccessRef.current?.(credentialResponse.credential);
          } else {
            onErrorRef.current?.("Google sign-in completed, but no ID token was returned.");
          }
        },
        auto_select: false,
        use_fedcm_for_button: false,
      });

      const buttonWidth = window.innerWidth < 400 ? 280 : 340;

      window.google.accounts.id.renderButton(containerRef.current, {
        type: "standard",
        theme: "filled_black",
        size: "large",
        text: "continue_with",
        shape: "rectangular",
        logo_alignment: "left",
        width: buttonWidth,
      });

      renderedRef.current = true;
    } catch (err) {
      console.error("[GoogleAuthSection] Failed to render Google button:", err);
    }
  }, [scriptLoadedSuccessfully, clientId]);

  if (!clientId) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface-2 p-3 text-center text-xs text-muted-foreground min-h-[40px] flex items-center justify-center">
        Google Sign-In requires <code className="font-mono text-primary ml-1">VITE_GOOGLE_CLIENT_ID</code>.
      </div>
    );
  }

  return (
    <div className="w-full flex justify-center py-0.5">
      {/* Fade the whole button (placeholder + Google iframe) together; fading
          only the iframe let the placeholder show through as a ghost label. */}
      <div className={`relative w-full max-w-[340px] h-[40px] flex justify-center items-center ${
        disabled ? "opacity-50 pointer-events-none" : ""
      }`}>
        {/* Instant zero-flash baseline placeholder */}
        <div
          aria-hidden="true"
          className="absolute inset-0 w-full h-[40px] rounded bg-[#131314] border border-[#31382F] flex items-center justify-center gap-3 px-4 pointer-events-none select-none z-0 shadow-sm"
        >
          <div className="w-5 h-5 flex items-center justify-center shrink-0">
            <GoogleIcon className="w-4 h-4" />
          </div>
          <span className="text-[14px] font-medium text-white tracking-normal font-sans antialiased">
            Continue with Google
          </span>
        </div>

        {/* Live Google Identity Services button container (renders directly in place) */}
        <div
          ref={containerRef}
          className="relative z-10 w-full h-[40px] flex justify-center items-center"
        />
      </div>
    </div>
  );
}

// Reusable Right-Side Marketing Card (Equal Height & Perfectly Balanced with Left Auth Card)
function AuthMarketingCard({ mode = "login" }) {
  const isCompact = mode === "login" || mode === "forgot-password";

  return (
    <div className="w-full max-w-[440px] rounded-2xl border border-border bg-surface/50 backdrop-blur-sm p-6 sm:p-7 shadow-card relative overflow-hidden flex flex-col h-full">
      <div className="absolute -right-10 -top-10 h-36 w-36 rounded-full bg-primary/10 blur-3xl pointer-events-none" />

      <div className="relative flex-1 flex flex-col justify-between h-full">
        <div>
          <div>
            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-primary/10 text-primary border border-primary/20">
              <Sparkles className="h-3 w-3" /> AI-Powered Smart Agriculture Platform
            </span>
            <h2 className="text-lg sm:text-xl font-bold tracking-tight text-foreground mt-2 leading-snug">
              Precision farming intelligence for every harvest.
            </h2>
            <p className="text-xs text-muted-foreground mt-1 leading-relaxed">
              Predictive crop models, microclimate advisories, mandi intelligence, and instant agronomy insights.
            </p>
          </div>

          {/* 4 Core Platform Feature Highlights (Compact & Consistent) */}
          <div className={isCompact ? "space-y-2 pt-3" : "space-y-3 pt-3.5"}>
            <div className={`flex items-center gap-2.5 rounded-xl border border-border bg-surface/80 px-3 ${isCompact ? "py-1.5 sm:py-2" : "py-2.5 sm:py-3"}`}>
              <div className="rounded-lg bg-primary/15 p-1.5 text-primary shrink-0">
                <BarChart3 className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0">
                <h3 className="text-xs font-semibold text-foreground leading-tight">
                  Machine Learning Crop Plans
                </h3>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                  Tailored N-P-K nutrient & rainfall optimization algorithms.
                </p>
              </div>
            </div>

            <div className={`flex items-center gap-2.5 rounded-xl border border-border bg-surface/80 px-3 ${isCompact ? "py-1.5 sm:py-2" : "py-2.5 sm:py-3"}`}>
              <div className="rounded-lg bg-primary/15 p-1.5 text-primary shrink-0">
                <ShieldCheck className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0">
                <h3 className="text-xs font-semibold text-foreground leading-tight">
                  Real-Time Risk Advisories
                </h3>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                  Preemptive microclimate alerts and disease prevention guidance.
                </p>
              </div>
            </div>

            <div className={`flex items-center gap-2.5 rounded-xl border border-border bg-surface/80 px-3 ${isCompact ? "py-1.5 sm:py-2" : "py-2.5 sm:py-3"}`}>
              <div className="rounded-lg bg-primary/15 p-1.5 text-primary shrink-0">
                <TrendingUp className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0">
                <h3 className="text-xs font-semibold text-foreground leading-tight">
                  Mandi Market Intelligence
                </h3>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                  Live wholesale prices and historical rate trends for maximum profit.
                </p>
              </div>
            </div>

            <div className={`flex items-center gap-2.5 rounded-xl border border-border bg-surface/80 px-3 ${isCompact ? "py-1.5 sm:py-2" : "py-2.5 sm:py-3"}`}>
              <div className="rounded-lg bg-primary/15 p-1.5 text-primary shrink-0">
                <Sparkles className="h-3.5 w-3.5" />
              </div>
              <div className="min-w-0">
                <h3 className="text-xs font-semibold text-foreground leading-tight">
                  AI Mitra 24/7 Advisor
                </h3>
                <p className="text-[11px] text-muted-foreground mt-0.5 leading-snug">
                  Contextual conversational advisory for daily farm decision-making.
                </p>
              </div>
            </div>
          </div>
        </div>

        {/* Bottom Platform Note - Anchored to bottom border */}
        <div className={`border-t border-border ${isCompact ? "pt-3 mt-3.5" : "pt-3.5 mt-4 sm:mt-5"}`}>
          <p className="text-[11px] sm:text-xs text-muted-foreground leading-relaxed">
            Secure, verified agronomy recommendations tailored to your local soil, weather, and seasonal crop cycles.
          </p>
        </div>
      </div>
    </div>
  );
}

function AuthPageWrapper() {
  return <AuthPage />;
}

function AuthPage() {
  const navigate = useNavigate();
  const search = Route.useSearch();
  const { login } = useAppData();
  const API_URL = getApiUrl();

  // Active request token to prevent race conditions and mode snaps
  const activeRequestRef = useRef(null);

  // Mode: "login" | "signup" | "verify-otp" | "forgot-password" | "reset-password-otp"
  const [mode, setMode] = useState(() => {
    const validModes = ["login", "signup", "verify-otp", "forgot-password", "reset-password-otp"];
    if (search?.mode && validModes.includes(search.mode)) {
      return search.mode;
    }
    return "login";
  });

  useEffect(() => {
    const validModes = ["login", "signup", "verify-otp", "forgot-password", "reset-password-otp"];
    if (search?.mode && validModes.includes(search.mode)) {
      setMode(search.mode);
    }
  }, [search?.mode]);

  // Form inputs (Login)
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [showLoginPassword, setShowLoginPassword] = useState(false);

  // Form inputs (Signup)
  const [signupName, setSignupName] = useState("");
  const [signupEmail, setSignupEmail] = useState("");
  const [signupPassword, setSignupPassword] = useState("");
  const [signupConfirmPassword, setSignupConfirmPassword] = useState("");
  const [signupPhone, setSignupPhone] = useState("");
  const [showSignupPassword, setShowSignupPassword] = useState(false);
  const [showSignupConfirmPassword, setShowSignupConfirmPassword] = useState(false);

  // OTP State (Signup verification)
  const [otpCode, setOtpCode] = useState("");
  const [resendCooldown, setResendCooldown] = useState(0);

  // Forgot password & reset state
  const [forgotEmail, setForgotEmail] = useState(() => {
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      return params.get("email") || "";
    }
    return "";
  });
  const [resetOtpCode, setResetOtpCode] = useState("");
  const [resetNewPassword, setResetNewPassword] = useState("");
  const [resetConfirmPassword, setResetConfirmPassword] = useState("");
  const [showResetPassword, setShowResetPassword] = useState(false);
  const [showResetConfirmPassword, setShowResetConfirmPassword] = useState(false);

  // Feedback states
  const [loading, setLoading] = useState(false);
  const [apiError, setApiError] = useState("");
  const [apiSuccess, setApiSuccess] = useState("");

  // Input refs for autofocus
  const loginEmailRef = useRef(null);
  const signupNameRef = useRef(null);
  const otpInputRef = useRef(null);
  const forgotEmailRef = useRef(null);
  const resetOtpRef = useRef(null);

  // Cooldown timer interval (reliable 1s countdown)
  useEffect(() => {
    if (resendCooldown <= 0) return;
    const interval = setInterval(() => {
      setResendCooldown((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);
    return () => clearInterval(interval);
  }, [resendCooldown > 0]);

  // Synchronize state with browser Back/Forward (popstate)
  useEffect(() => {
    const handlePopState = () => {
      activeRequestRef.current = null;
      setApiError("");
      setApiSuccess("");
      setLoading(false);
      const params = new URLSearchParams(window.location.search);
      const urlMode = params.get("mode") || "login";
      const stateEmail = window.history.state?.email || params.get("email") || "";
      if (["login", "signup", "verify-otp", "forgot-password", "reset-password-otp"].includes(urlMode)) {
        setMode(urlMode);
      } else {
        setMode("login");
      }
      if (stateEmail) {
        if (urlMode === "signup" || urlMode === "verify-otp") setSignupEmail(stateEmail);
        else if (urlMode === "forgot-password" || urlMode === "reset-password-otp") setForgotEmail(stateEmail);
        else if (urlMode === "login") setLoginEmail(stateEmail);
      }
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Mode switcher with history and URL synchronization
  const switchMode = (newMode, newEmail = null) => {
    // Invalidate any in-flight request callback to prevent race conditions
    activeRequestRef.current = null;
    setApiError("");
    setApiSuccess("");
    setLoading(false);

    let resolvedEmail = newEmail;
    if (resolvedEmail === null) {
      if (newMode === "forgot-password") {
        resolvedEmail = forgotEmail || loginEmail;
        if (loginEmail && !forgotEmail) setForgotEmail(loginEmail);
      } else if (newMode === "verify-otp") {
        resolvedEmail = signupEmail;
      } else if (newMode === "reset-password-otp") {
        resolvedEmail = forgotEmail;
      } else if (newMode === "login") {
        resolvedEmail = loginEmail || forgotEmail;
      }
    } else {
      if (newMode === "signup" || newMode === "verify-otp") setSignupEmail(resolvedEmail);
      if (newMode === "forgot-password" || newMode === "reset-password-otp") setForgotEmail(resolvedEmail);
      if (newMode === "login") setLoginEmail(resolvedEmail);
    }

    setMode(newMode);

    // Sync mode to URL so browser Back/Forward works, but never expose email in query params
    if (typeof window !== "undefined") {
      const url = new URL(window.location.href);
      if (newMode === "login") {
        url.searchParams.delete("mode");
      } else {
        url.searchParams.set("mode", newMode);
      }
      // Security: strip plaintext email from URL parameters to prevent PII leakage
      url.searchParams.delete("email");
      window.history.pushState({ mode: newMode, email: resolvedEmail }, "", url.toString());
    }
  };

  // Autofocus according to mode
  useEffect(() => {
    if (mode === "login") loginEmailRef.current?.focus();
    else if (mode === "signup") signupNameRef.current?.focus();
    else if (mode === "verify-otp") otpInputRef.current?.focus();
    else if (mode === "forgot-password") forgotEmailRef.current?.focus();
    else if (mode === "reset-password-otp") resetOtpRef.current?.focus();
  }, [mode]);

  // Store auth tokens & complete login using AppDataContext login()
  const completeAuth = (data) => {
    const accessToken = data.token?.access || data.token;
    const refreshToken = data.token?.refresh;

    if (accessToken) {
      localStorage.setItem("krishimitra_token", accessToken);
      if (typeof login === "function") {
        login(accessToken);
      }
    }
    if (refreshToken) {
      localStorage.setItem("krishimitra_refresh_token", refreshToken);
    }
    navigate({ to: "/dashboard" });
  };

  // 1. Handle Direct Password Login
  const handleLoginSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    setApiSuccess("");

    const email = loginEmail.trim().toLowerCase();
    if (!email || !loginPassword) {
      setApiError("Please enter your email and password.");
      return;
    }
    if (!isValidEmail(email)) {
      setApiError("Please enter a valid email address (e.g., name@example.com).");
      return;
    }

    const reqId = Symbol();
    activeRequestRef.current = reqId;
    setLoading(true);

    try {
      const res = await fetchWithTimeout(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password: loginPassword }),
      });

      const data = await res.json().catch(() => ({}));

      if (activeRequestRef.current !== reqId) return;

      if (!res.ok) {
        if (data.accountNotFound) {
          setApiError(
            <span>
              No account found for <strong>{email}</strong>.{" "}
              <button
                type="button"
                onClick={() => {
                  setSignupEmail(email);
                  switchMode("signup", email);
                }}
                className="font-semibold underline hover:text-foreground cursor-pointer"
              >
                Sign up now
              </button>
            </span>
          );
          return;
        }

        if (data.requiresVerification) {
          setSignupEmail(data.email || email);
          setApiSuccess("Your email is not verified yet. We are sending you a verification code.");
          fetchWithTimeout(`${API_URL}/auth/otp/request`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email, purpose: "register" }),
          }).catch(() => {});
          setResendCooldown(60);
          switchMode("verify-otp", data.email || email);
          return;
        }

        throw new Error(data.message || "Invalid email or password.");
      }

      completeAuth(data);
    } catch (err) {
      if (activeRequestRef.current === reqId) {
        setApiError(err.message || "Failed to sign in. Please check your credentials.");
      }
    } finally {
      if (activeRequestRef.current === reqId) {
        setLoading(false);
      }
    }
  };

  // 2. Handle Initial Signup Form Submit -> Send OTP
  const handleSignupSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    setApiSuccess("");

    const name = signupName.trim();
    const email = signupEmail.trim().toLowerCase();
    const phone = signupPhone.trim();

    if (!name) {
      setApiError("Please enter your full name.");
      return;
    }
    if (!isValidEmail(email)) {
      setApiError("Please enter a valid email address (e.g., name@example.com).");
      return;
    }
    const pwdErr = validatePasswordPolicy(signupPassword);
    if (pwdErr) {
      setApiError(pwdErr);
      return;
    }
    if (signupPassword !== signupConfirmPassword) {
      setApiError("Passwords do not match. Please re-enter.");
      return;
    }

    const reqId = Symbol();
    activeRequestRef.current = reqId;
    setLoading(true);

    try {
      const checkRes = await fetchWithTimeout(`${API_URL}/auth/check-exists`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, phone: phone || undefined }),
      });
      const checkData = await checkRes.json().catch(() => ({}));

      if (checkData.exists) {
        throw new Error("An account with this email already exists. Please sign in instead.");
      }

      const otpRes = await fetchWithTimeout(`${API_URL}/auth/otp/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, purpose: "register" }),
      });
      const otpData = await otpRes.json().catch(() => ({}));

      if (activeRequestRef.current !== reqId) return;

      if (!otpRes.ok) {
        if (otpRes.status === 429 && otpData.retryAfter) {
          setResendCooldown(otpData.retryAfter);
          switchMode("verify-otp", email);
          return;
        }
        throw new Error(otpData.message || "Failed to send verification code. Please try again.");
      }

      setResendCooldown(60);
      switchMode("verify-otp", email);
      setApiSuccess(`We've sent a 6-digit verification code to ${maskEmail(email)}.`);
    } catch (err) {
      if (activeRequestRef.current === reqId) {
        setApiError(err.message || "An error occurred during registration. Please try again.");
      }
    } finally {
      if (activeRequestRef.current === reqId) {
        setLoading(false);
      }
    }
  };

  // 3. Handle Email OTP Verification -> Complete Registration
  const handleVerifyOtpSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    setApiSuccess("");

    const code = otpCode.trim();
    if (!code || code.length < 6) {
      setApiError("Please enter the complete 6-digit verification code.");
      return;
    }

    const reqId = Symbol();
    activeRequestRef.current = reqId;
    setLoading(true);

    try {
      const nameParts = signupName.trim().split(" ");
      const firstName = nameParts[0] || signupName.trim();
      const lastName = nameParts.slice(1).join(" ");

      const regRes = await fetchWithTimeout(`${API_URL}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: signupEmail.trim().toLowerCase(),
          password: signupPassword,
          firstName,
          lastName,
          phone: signupPhone.trim() || undefined,
          otp: code,
          role: "farmer",
          farmingMode: "moderate",
        }),
      });

      const regData = await regRes.json().catch(() => ({}));

      if (activeRequestRef.current !== reqId) return;

      if (!regRes.ok) {
        throw new Error(regData.message || "Invalid or expired verification code.");
      }

      completeAuth(regData);
    } catch (err) {
      if (activeRequestRef.current === reqId) {
        setApiError(err.message || "Verification failed. Please try again.");
      }
    } finally {
      if (activeRequestRef.current === reqId) {
        setLoading(false);
      }
    }
  };

  // Resend OTP for signup
  const handleResendOtp = async () => {
    if (resendCooldown > 0 || loading) return;
    setApiError("");
    setApiSuccess("");
    setLoading(true);

    try {
      const res = await fetchWithTimeout(`${API_URL}/auth/otp/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: signupEmail.trim().toLowerCase(),
          purpose: "register",
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        if (res.status === 429 && data.retryAfter) {
          setResendCooldown(data.retryAfter);
          return;
        }
        throw new Error(data.message || "Failed to resend code.");
      }

      setResendCooldown(60);
      setApiSuccess(`A new verification code has been sent to ${maskEmail(signupEmail)}.`);
    } catch (err) {
      setApiError(err.message || "Unable to resend verification code.");
    } finally {
      setLoading(false);
    }
  };

  // 4. Handle Forgot Password Request
  const handleForgotPasswordSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    setApiSuccess("");

    const email = forgotEmail.trim().toLowerCase();
    if (!isValidEmail(email)) {
      setApiError("Please enter a valid email address (e.g., name@example.com).");
      return;
    }

    const reqId = Symbol();
    activeRequestRef.current = reqId;
    setLoading(true);

    try {
      const res = await fetchWithTimeout(`${API_URL}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email }),
      });
      const data = await res.json().catch(() => ({}));

      if (activeRequestRef.current !== reqId) return;

      if (!res.ok) {
        if (res.status === 429 && data.retryAfter) {
          setResendCooldown(data.retryAfter);
          switchMode("reset-password-otp", email);
          setApiError(data.message || `Please wait ${data.retryAfter} seconds before requesting a new code.`);
          return;
        }
        throw new Error(data.message || "Failed to initiate password reset.");
      }

      setResendCooldown(60);
      switchMode("reset-password-otp", email);
      setApiSuccess("If that email is registered, we've sent a 6-digit verification code.");
    } catch (err) {
      if (activeRequestRef.current === reqId) {
        setApiError(err.message || "Unable to process request. Please try again.");
      }
    } finally {
      if (activeRequestRef.current === reqId) {
        setLoading(false);
      }
    }
  };

  // 5. Handle Reset Password with OTP
  const handleResetPasswordSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    setApiSuccess("");

    const code = resetOtpCode.trim();
    if (!code || code.length < 6) {
      setApiError("Please enter the complete 6-digit code.");
      return;
    }
    const pwdErr = validatePasswordPolicy(resetNewPassword);
    if (pwdErr) {
      setApiError(pwdErr);
      return;
    }
    if (resetNewPassword !== resetConfirmPassword) {
      setApiError("Passwords do not match. Please re-enter.");
      return;
    }

    const reqId = Symbol();
    activeRequestRef.current = reqId;
    setLoading(true);

    try {
      const res = await fetchWithTimeout(`${API_URL}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: forgotEmail.trim().toLowerCase(),
          otp: code,
          newPassword: resetNewPassword,
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (activeRequestRef.current !== reqId) return;

      if (!res.ok) {
        throw new Error(data.message || "Password reset failed. Please check the code and try again.");
      }

      setLoginEmail(forgotEmail);
      setLoginPassword("");
      setResetOtpCode("");
      setResetNewPassword("");
      setResetConfirmPassword("");
      switchMode("login", forgotEmail);
      setApiSuccess("Password reset successfully! You can now sign in with your new password.");
    } catch (err) {
      if (activeRequestRef.current === reqId) {
        setApiError(err.message || "Password reset failed. Please check the code and try again.");
      }
    } finally {
      if (activeRequestRef.current === reqId) {
        setLoading(false);
      }
    }
  };

  // 6. Handle Google Credential Response (ID Token)
  const handleGoogleSuccess = async (idToken) => {
    setApiError("");
    setApiSuccess("");
    setLoading(true);

    try {
      const res = await fetchWithTimeout(`${API_URL}/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ credential: idToken }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.message || "Google sign-in could not be completed. Please try again.");
      }

      completeAuth(data);
    } catch (err) {
      setApiError(err.message || "Google sign-in could not be completed. Please try again.");
    } finally {
      setLoading(false);
    }
  };

  const handleGoogleError = (errorMessage) => {
    setApiError(errorMessage || "Google sign-in was cancelled or encountered an error.");
  };

  return (
    <div className="min-h-screen bg-background text-foreground flex flex-col justify-between selection:bg-primary selection:text-primary-foreground">
      {/* Top Navigation Bar */}
      <header className="w-full border-b border-border bg-surface/80 backdrop-blur-md sticky top-0 z-30 px-4 sm:px-6 py-3 sm:py-4 flex items-center justify-between">
        <Link to="/" className="flex items-center gap-2 group shrink-0">
          <BrandMark />
        </Link>
        <div className="flex items-center gap-2 sm:gap-3 shrink-0">
          <ThemeToggle />
        </div>
      </header>

      {/* Main Content Area: Equal-Height Symmetrical Auth Grid */}
      <main className="flex-1 flex items-center justify-center p-4 sm:p-6 lg:p-10">
        <div className="w-full max-w-5xl grid grid-cols-1 lg:grid-cols-2 gap-8 lg:gap-10 items-stretch justify-center">

          {/* Left Column: Shared Auth Card Shell */}
          <div className="flex justify-center lg:justify-end w-full h-full">
            <div className="w-full max-w-[440px] p-6 sm:p-7 bg-surface border border-border rounded-2xl shadow-card transition-colors duration-150 flex flex-col h-full">

              {/* Status Alert Notifications */}
              {loading && !apiError && !apiSuccess && (
                <div className="mb-4 flex items-center gap-3 rounded-xl border border-primary/30 bg-primary/10 p-3.5 text-sm text-primary animate-in fade-in slide-in-from-top-1 shrink-0">
                  <Loader2 className="h-4 w-4 animate-spin shrink-0" />
                  <p className="leading-snug font-medium">
                    {mode === "signup"
                      ? "Creating your account..."
                      : mode === "verify-otp"
                      ? "Verifying code & activating account..."
                      : mode === "forgot-password"
                      ? "Sending verification code..."
                      : mode === "reset-password-otp"
                      ? "Updating your password..."
                      : "Signing you in..."}
                  </p>
                </div>
              )}

              {apiError && (
                <div className="mb-4 flex items-start gap-3 rounded-xl border border-error/30 bg-error/10 p-3.5 text-sm text-error animate-in fade-in slide-in-from-top-1 shrink-0">
                  <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
                  <p className="leading-snug">{apiError}</p>
                </div>
              )}

              {apiSuccess && (
                <div className="mb-4 flex items-start gap-3 rounded-xl border border-primary/30 bg-primary/10 p-3.5 text-sm text-primary animate-in fade-in slide-in-from-top-1 shrink-0">
                  <CheckCircle2 className="h-4 w-4 shrink-0 mt-0.5" />
                  <p className="leading-snug">{apiSuccess}</p>
                </div>
              )}

              {/* MODES 1 & 2: LOGIN & SIGNUP (Unified layout with persistent Google button) */}
              {(mode === "login" || mode === "signup") && (
                <div>
                  {mode === "login" ? (
                    <div className="mb-5 sm:mb-6">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-primary/10 text-primary border border-primary/20 mb-2 sm:mb-2.5">
                        <Sparkles className="h-3 w-3" /> Agri Intelligence
                      </span>
                      <h1 className="text-2xl font-bold tracking-tight text-foreground">
                        Welcome back
                      </h1>
                      <p className="text-xs sm:text-sm text-muted-foreground mt-1">
                        Sign in to your KrishiMitra account.
                      </p>
                    </div>
                  ) : (
                    <div className="mb-3.5">
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-primary/10 text-primary border border-primary/20 mb-1.5">
                        <Sparkles className="h-3 w-3" /> Agri Intelligence
                      </span>
                      <h1 className="text-2xl font-bold tracking-tight text-foreground">
                        Create your account
                      </h1>
                      <p className="text-xs sm:text-sm text-muted-foreground mt-0.5">
                        Start growing smarter with KrishiMitra.
                      </p>
                    </div>
                  )}

                  {mode === "login" ? (
                    <form onSubmit={handleLoginSubmit} className="space-y-4">
                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1.5">
                          Email
                        </label>
                        <div className="relative">
                          <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            ref={loginEmailRef}
                            type="email"
                            autoComplete="email"
                            required
                            value={loginEmail}
                            onChange={(e) => setLoginEmail(e.target.value)}
                            placeholder="farmer@example.com"
                            className="w-full rounded-xl border border-border bg-surface pl-10 pr-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                        </div>
                      </div>

                      <div>
                        <div className="flex items-center justify-between mb-1.5">
                          <label className="text-xs font-medium text-foreground">
                            Password
                          </label>
                          <button
                            type="button"
                            onClick={() => switchMode("forgot-password")}
                            className="text-xs font-medium text-primary hover:underline cursor-pointer"
                          >
                            Forgot password?
                          </button>
                        </div>
                        <div className="relative">
                          <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            type={showLoginPassword ? "text" : "password"}
                            autoComplete="current-password"
                            required
                            value={loginPassword}
                            onChange={(e) => setLoginPassword(e.target.value)}
                            placeholder="••••••••"
                            className="w-full rounded-xl border border-border bg-surface pl-10 pr-10 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                          <button
                            type="button"
                            onClick={() => setShowLoginPassword(!showLoginPassword)}
                            className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                            aria-label={showLoginPassword ? "Hide password" : "Show password"}
                          >
                            {showLoginPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          </button>
                        </div>
                      </div>

                      <button
                        type="submit"
                        disabled={loading}
                        className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-2.5 px-4 text-sm transition-all shadow-sm cursor-pointer disabled:opacity-50 mt-2"
                      >
                        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Sign in"}
                      </button>
                    </form>
                  ) : (
                    <form onSubmit={handleSignupSubmit} className="space-y-2.5">
                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1">
                          Full name *
                        </label>
                        <div className="relative">
                          <UserRound className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            ref={signupNameRef}
                            type="text"
                            autoComplete="name"
                            required
                            value={signupName}
                            onChange={(e) => setSignupName(e.target.value)}
                            placeholder="Ramesh Patel"
                            className="w-full rounded-xl border border-border bg-surface pl-10 pr-4 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                        </div>
                      </div>

                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1">
                          Email *
                        </label>
                        <div className="relative">
                          <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            type="email"
                            autoComplete="email"
                            required
                            value={signupEmail}
                            onChange={(e) => setSignupEmail(e.target.value)}
                            placeholder="farmer@example.com"
                            className="w-full rounded-xl border border-border bg-surface pl-10 pr-4 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                        </div>
                      </div>

                      <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5">
                        <div>
                          <label className="block text-xs font-medium text-foreground mb-1">
                            Password *
                          </label>
                          <div className="relative">
                            <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                            <input
                              type={showSignupPassword ? "text" : "password"}
                              autoComplete="new-password"
                              required
                              value={signupPassword}
                              onChange={(e) => setSignupPassword(e.target.value)}
                              placeholder="••••••••"
                              className="w-full rounded-xl border border-border bg-surface pl-10 pr-9 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                            />
                            <button
                              type="button"
                              onClick={() => setShowSignupPassword(!showSignupPassword)}
                              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                              aria-label={showSignupPassword ? "Hide password" : "Show password"}
                            >
                              {showSignupPassword ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                            </button>
                          </div>
                        </div>

                        <div>
                          <label className="block text-xs font-medium text-foreground mb-1">
                            Confirm password *
                          </label>
                          <div className="relative">
                            <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                            <input
                              type={showSignupConfirmPassword ? "text" : "password"}
                              autoComplete="new-password"
                              required
                              value={signupConfirmPassword}
                              onChange={(e) => setSignupConfirmPassword(e.target.value)}
                              placeholder="••••••••"
                              className="w-full rounded-xl border border-border bg-surface pl-10 pr-9 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                            />
                            <button
                              type="button"
                              onClick={() => setShowSignupConfirmPassword(!showSignupConfirmPassword)}
                              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                              aria-label={showSignupConfirmPassword ? "Hide password" : "Show password"}
                            >
                              {showSignupConfirmPassword ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
                            </button>
                          </div>
                        </div>
                      </div>

                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1">
                          Mobile number <span className="text-muted-foreground font-normal">(optional)</span>
                        </label>
                        <div className="relative">
                          <Phone className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            type="tel"
                            autoComplete="tel"
                            value={signupPhone}
                            onChange={(e) => setSignupPhone(e.target.value)}
                            placeholder="9876543210"
                            className="w-full rounded-xl border border-border bg-surface pl-10 pr-4 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                        </div>
                      </div>

                      <button
                        type="submit"
                        disabled={loading}
                        className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-2.5 px-4 text-sm transition-all shadow-sm cursor-pointer disabled:opacity-50 mt-1"
                      >
                        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Create account"}
                      </button>
                    </form>
                  )}

                  {/* Stable Bottom Section: Divider, Persistent Google Auth & Account Switching Footer */}
                  <div className={mode === "login" ? "mt-4 sm:mt-5" : "mt-3.5 sm:mt-4"}>
                    <div className={mode === "login" ? "relative mb-4" : "relative mb-3.5"}>
                      <div className="absolute inset-0 flex items-center">
                        <div className="w-full border-t border-border" />
                      </div>
                      <div className="relative flex justify-center text-xs uppercase">
                        <span className="bg-surface px-3 text-muted-foreground font-medium">
                          OR
                        </span>
                      </div>
                    </div>

                    {/* Google Sign In (Preserved across login and signup) */}
                    <GoogleAuthSection
                      onSuccess={handleGoogleSuccess}
                      onError={handleGoogleError}
                      disabled={loading}
                    />

                    {/* Account-Switching Footer (Visually connected directly below Google button with 16-20px spacing) */}
                    <p className={mode === "login" ? "mt-4.5 sm:mt-5 text-center text-xs text-muted-foreground" : "mt-4 text-center text-xs text-muted-foreground"}>
                      {mode === "login" ? (
                        <>
                          Don't have an account?{" "}
                          <button
                            type="button"
                            onClick={() => switchMode("signup")}
                            className="font-semibold text-primary hover:underline cursor-pointer"
                          >
                            Sign up
                          </button>
                        </>
                      ) : (
                        <>
                          Already have an account?{" "}
                          <button
                            type="button"
                            onClick={() => switchMode("login")}
                            className="font-semibold text-primary hover:underline cursor-pointer"
                          >
                            Sign in
                          </button>
                        </>
                      )}
                    </p>
                  </div>
                </div>
              )}

              {/* MODE 3: VERIFY EMAIL OTP */}
              {mode === "verify-otp" && (
                <div className="flex-1 flex flex-col justify-between h-full">
                  <div>
                    <div className="mb-6">
                      <button
                        type="button"
                        onClick={() => switchMode("signup")}
                        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3 transition-colors cursor-pointer"
                      >
                        <ArrowLeft className="h-3.5 w-3.5" /> Back to edit details
                      </button>
                      <h1 className="text-2xl font-bold tracking-tight text-foreground">
                        Verify your email
                      </h1>
                      <p className="text-sm text-muted-foreground mt-1.5">
                        We sent a 6-digit verification code to{" "}
                        <span className="font-semibold text-foreground">{maskEmail(signupEmail)}</span>
                      </p>
                    </div>

                    <form onSubmit={handleVerifyOtpSubmit} className="space-y-4">
                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1.5">
                          Verification Code (OTP)
                        </label>
                        <div className="relative">
                          <KeyRound className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            ref={otpInputRef}
                            type="text"
                            inputMode="numeric"
                            pattern="[0-9]*"
                            maxLength={6}
                            autoComplete="one-time-code"
                            required
                            value={otpCode}
                            onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ""))}
                            placeholder="123456"
                            className="w-full tracking-widest text-center text-lg font-mono font-bold rounded-xl border border-border bg-surface pl-10 pr-4 py-2.5 text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                        </div>
                      </div>

                      <button
                        type="submit"
                        disabled={loading || otpCode.length < 6}
                        className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-2.5 px-4 text-sm transition-all shadow-sm cursor-pointer disabled:opacity-50 mt-2"
                      >
                        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Verify email"}
                      </button>
                    </form>
                  </div>

                  <div className="mt-6 flex items-center justify-between text-xs border-t border-border pt-3.5 shrink-0">
                    <button
                      type="button"
                      onClick={handleResendOtp}
                      disabled={resendCooldown > 0 || loading}
                      className="font-medium text-xs sm:text-sm text-primary hover:underline disabled:text-muted-foreground disabled:no-underline disabled:cursor-not-allowed transition-colors"
                    >
                      {resendCooldown > 0 ? `Resend OTP in ${resendCooldown}s` : "Resend OTP"}
                    </button>
                    <button
                      type="button"
                      onClick={() => switchMode("signup")}
                      className="text-muted-foreground hover:text-foreground cursor-pointer text-xs sm:text-sm"
                    >
                      Change email
                    </button>
                  </div>
                </div>
              )}

              {/* MODE 4: FORGOT PASSWORD */}
              {mode === "forgot-password" && (
                <div className="flex-1 flex flex-col justify-between h-full">
                  <div>
                    <div className="mb-6">
                      <button
                        type="button"
                        onClick={() => switchMode("login")}
                        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-3 transition-colors cursor-pointer"
                      >
                        <ArrowLeft className="h-3.5 w-3.5" /> Back to sign in
                      </button>
                      <h1 className="text-2xl font-bold tracking-tight text-foreground">
                        Reset your password
                      </h1>
                      <p className="text-sm text-muted-foreground mt-1.5">
                        Enter your email address and we'll send a verification code to reset your password.
                      </p>
                    </div>

                    <form onSubmit={handleForgotPasswordSubmit} className="space-y-4">
                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1.5">
                          Account Email
                        </label>
                        <div className="relative">
                          <Mail className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            ref={forgotEmailRef}
                            type="email"
                            autoComplete="email"
                            required
                            value={forgotEmail}
                            onChange={(e) => setForgotEmail(e.target.value)}
                            placeholder="farmer@example.com"
                            className="w-full rounded-xl border border-border bg-surface pl-10 pr-4 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                        </div>
                      </div>

                      <button
                        type="submit"
                        disabled={loading}
                        className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-2.5 px-4 text-sm transition-all shadow-sm cursor-pointer disabled:opacity-50 mt-2"
                      >
                        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Send verification code"}
                      </button>
                    </form>
                  </div>

                  <div className="mt-6 flex items-center justify-center text-xs border-t border-border pt-3.5 text-muted-foreground shrink-0">
                    Remember your password?{" "}
                    <button
                      type="button"
                      onClick={() => switchMode("login")}
                      className="ml-1 font-semibold text-primary hover:underline cursor-pointer"
                    >
                      Sign in
                    </button>
                  </div>
                </div>
              )}

              {/* MODE 5: RESET PASSWORD WITH OTP */}
              {mode === "reset-password-otp" && (
                <div className="flex-1 flex flex-col justify-between h-full">
                  <div>
                    <div className="mb-5">
                      <button
                        type="button"
                        onClick={() => switchMode("forgot-password")}
                        className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground mb-2.5 transition-colors cursor-pointer"
                      >
                        <ArrowLeft className="h-3.5 w-3.5" /> Change email
                      </button>
                      <h1 className="text-2xl font-bold tracking-tight text-foreground">
                        Enter new password
                      </h1>
                      <p className="text-xs sm:text-sm text-muted-foreground mt-1">
                        Enter the 6-digit code sent to{" "}
                        <span className="font-semibold text-foreground">{maskEmail(forgotEmail)}</span> and choose a new password.
                      </p>
                    </div>

                    <form onSubmit={handleResetPasswordSubmit} className="space-y-3.5">
                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1">
                          6-Digit Code
                        </label>
                        <div className="relative">
                          <KeyRound className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            ref={resetOtpRef}
                            type="text"
                            inputMode="numeric"
                            pattern="[0-9]*"
                            maxLength={6}
                            autoComplete="one-time-code"
                            required
                            value={resetOtpCode}
                            onChange={(e) => setResetOtpCode(e.target.value.replace(/\D/g, ""))}
                            placeholder="123456"
                            className="w-full tracking-widest text-center text-lg font-mono font-bold rounded-xl border border-border bg-surface pl-10 pr-4 py-2.5 text-foreground placeholder:text-muted-foreground/40 focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                        </div>
                      </div>

                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1">
                          New Password
                        </label>
                        <div className="relative">
                          <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            type={showResetPassword ? "text" : "password"}
                            autoComplete="new-password"
                            required
                            value={resetNewPassword}
                            onChange={(e) => setResetNewPassword(e.target.value)}
                            placeholder="••••••••"
                            className="w-full rounded-xl border border-border bg-surface pl-10 pr-10 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                          <button
                            type="button"
                            onClick={() => setShowResetPassword(!showResetPassword)}
                            className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                            aria-label={showResetPassword ? "Hide password" : "Show password"}
                          >
                            {showResetPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          </button>
                        </div>
                        <p className="text-[11px] text-muted-foreground mt-1">
                          Must be 8–128 characters with uppercase, lowercase, number, and special character.
                        </p>
                      </div>

                      <div>
                        <label className="block text-xs font-medium text-foreground mb-1">
                          Confirm New Password
                        </label>
                        <div className="relative">
                          <Lock className="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
                          <input
                            type={showResetConfirmPassword ? "text" : "password"}
                            autoComplete="new-password"
                            required
                            value={resetConfirmPassword}
                            onChange={(e) => setResetConfirmPassword(e.target.value)}
                            placeholder="••••••••"
                            className="w-full rounded-xl border border-border bg-surface pl-10 pr-10 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/25 focus:border-primary transition-all"
                          />
                          <button
                            type="button"
                            onClick={() => setShowResetConfirmPassword(!showResetConfirmPassword)}
                            className="absolute right-3.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
                            aria-label={showResetConfirmPassword ? "Hide password" : "Show password"}
                          >
                            {showResetConfirmPassword ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                          </button>
                        </div>
                      </div>

                      <button
                        type="submit"
                        disabled={loading || resetOtpCode.length < 6}
                        className="w-full flex items-center justify-center gap-2 rounded-xl bg-primary hover:bg-primary/90 text-primary-foreground font-semibold py-2.5 px-4 text-sm transition-all shadow-sm cursor-pointer disabled:opacity-50 mt-2"
                      >
                        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Reset password"}
                      </button>
                    </form>
                  </div>

                  <div className="mt-6 flex items-center justify-between text-xs border-t border-border pt-3.5 shrink-0">
                    <button
                      type="button"
                      onClick={handleForgotPasswordSubmit}
                      disabled={resendCooldown > 0 || loading}
                      className="font-medium text-xs sm:text-sm text-primary hover:underline disabled:text-muted-foreground disabled:no-underline disabled:cursor-not-allowed transition-colors"
                    >
                      {resendCooldown > 0 ? `Resend OTP in ${resendCooldown}s` : "Resend OTP"}
                    </button>
                    <button
                      type="button"
                      onClick={() => switchMode("login")}
                      className="text-muted-foreground hover:text-foreground cursor-pointer text-xs sm:text-sm"
                    >
                      Back to sign in
                    </button>
                  </div>
                </div>
              )}

            </div>
          </div>

          {/* Right Column: Shared Marketing Card */}
          <div className="flex justify-center lg:justify-start w-full h-full">
            <AuthMarketingCard mode={mode} />
          </div>

        </div>
      </main>

      {/* Footer */}
      <footer className="w-full border-t border-border py-4 px-4 sm:px-6 text-center text-xs text-muted-foreground">
        &copy; {new Date().getFullYear()} KrishiMitra — AI-Powered Smart Agriculture Platform.{" "}
        <span className="whitespace-nowrap inline-block">All rights reserved.</span>
      </footer>
    </div>
  );
}
