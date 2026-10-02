import { Link, createFileRoute, useNavigate, redirect } from "@tanstack/react-router";
import { useState, useEffect, useRef } from "react";
import {
  ArrowRight,
  ArrowLeft,
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
} from "lucide-react";
import { GoogleOAuthProvider, useGoogleLogin } from "@react-oauth/google";

import { BrandMark, ThemeToggle } from "@/components/app/AppShell";
import { useAppData } from "@/lib/AppDataContext";

export const Route = createFileRoute("/auth")({
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
        content: "Sign in or create your KrishiMitra account to start AI-powered farm planning.",
      },
    ],
  }),
  component: AuthPageWrapper,
});

const getApiUrl = () =>
  import.meta.env.VITE_API_URL ||
  (typeof window !== "undefined"
    ? `http://${window.location.hostname}:5001/api`
    : "http://localhost:5001/api");

// Google SVG Icon
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

function GoogleAuthButton({ onStart, onSuccess, onError, disabled }) {
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;

  if (!googleClientId) {
    return (
      <button
        type="button"
        onClick={() => {
          onError(
            "Google Sign-In requires VITE_GOOGLE_CLIENT_ID in your environment. Please sign in with email and password.",
          );
        }}
        disabled={disabled}
        className="flex w-full items-center justify-center gap-2.5 rounded-xl border border-border bg-surface hover:bg-surface-2 py-3 px-4 text-sm font-semibold text-foreground transition-all shadow-sm cursor-pointer disabled:opacity-50"
      >
        <GoogleIcon className="h-4 w-4 shrink-0" />
        Continue with Google
      </button>
    );
  }

  return (
    <ActiveGoogleLoginButton
      onStart={onStart}
      onSuccess={onSuccess}
      onError={onError}
      disabled={disabled}
    />
  );
}

function ActiveGoogleLoginButton({ onStart, onSuccess, onError, disabled }) {
  const triggerGoogleLogin = useGoogleLogin({
    onSuccess: (tokenResponse) => {
      if (tokenResponse?.access_token) {
        onSuccess(tokenResponse.access_token);
      } else {
        onError("Google authorization succeeded, but no access token was returned.");
      }
    },
    onError: (errorResponse) => {
      console.warn("Google sign-in error or cancelled:", errorResponse);
      onError("Google sign-in was cancelled or encountered an error.");
    },
  });

  return (
    <button
      type="button"
      onClick={() => {
        onStart();
        triggerGoogleLogin();
      }}
      disabled={disabled}
      className="flex w-full items-center justify-center gap-2.5 rounded-xl border border-border bg-surface hover:bg-surface-2 py-3 px-4 text-sm font-semibold text-foreground transition-all shadow-sm cursor-pointer disabled:opacity-50"
    >
      <GoogleIcon className="h-4 w-4 shrink-0" />
      Continue with Google
    </button>
  );
}

function AuthPageWrapper() {
  const googleClientId = import.meta.env.VITE_GOOGLE_CLIENT_ID;
  if (googleClientId) {
    return (
      <GoogleOAuthProvider clientId={googleClientId}>
        <AuthPage />
      </GoogleOAuthProvider>
    );
  }
  return <AuthPage />;
}

function AuthPage() {
  const navigate = useNavigate();
  const { login } = useAppData();

  // Steps: 'initial' | 'password' | 'create-account' | 'verify-email' | 'otp-login' | 'forgot-password'
  const [step, setStep] = useState("initial");

  // Input fields
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [fullName, setFullName] = useState("");
  const [phone, setPhone] = useState("");
  const [otp, setOtp] = useState("");

  // Password visibility
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirmPassword, setShowConfirmPassword] = useState(false);

  // Forgot password sub-state: 'email' | 'otp' | 'success'
  const [forgotStep, setForgotStep] = useState("email");
  const [forgotOtp, setForgotOtp] = useState("");
  const [forgotNewPassword, setForgotNewPassword] = useState("");
  const [forgotConfirmPassword, setForgotConfirmPassword] = useState("");

  // Status & Feedback
  const [isLoading, setIsLoading] = useState(false);
  const [apiError, setApiError] = useState("");
  const [fieldErrors, setFieldErrors] = useState({});
  const [resendTimer, setResendTimer] = useState(0);
  const [googleNotice, setGoogleNotice] = useState("");

  const otpInputRef = useRef(null);

  // Resend cooldown timer
  useEffect(() => {
    if (resendTimer <= 0) return;
    const interval = setInterval(() => {
      setResendTimer((prev) => (prev <= 1 ? 0 : prev - 1));
    }, 1000);
    return () => clearInterval(interval);
  }, [resendTimer]);

  // Focus OTP input on otp steps
  useEffect(() => {
    if ((step === "verify-email" || step === "otp-login") && otpInputRef.current) {
      otpInputRef.current.focus();
    }
  }, [step]);

  const clearError = (field) => {
    if (fieldErrors[field]) {
      setFieldErrors((prev) => {
        const next = { ...prev };
        delete next[field];
        return next;
      });
    }
    setApiError("");
  };

  const maskEmail = (str) => {
    if (!str || !str.includes("@")) return str;
    const [local, domain] = str.split("@");
    if (local.length <= 2) return `${local[0]}*@${domain}`;
    return `${local.slice(0, 2)}${"*".repeat(Math.max(1, local.length - 4))}${local.slice(-2)}@${domain}`;
  };

  // 1. Initial Step: Email / Username Entry
  const handleInitialSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    setFieldErrors({});

    const cleanIdentifier = identifier.trim().toLowerCase();
    if (!cleanIdentifier) {
      setFieldErrors({ identifier: "Please enter your email or username." });
      return;
    }

    setIsLoading(true);
    const API_URL = getApiUrl();

    try {
      const res = await fetch(`${API_URL}/auth/check-exists`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: cleanIdentifier }),
      });
      const data = await res.json().catch(() => ({}));

      if (data.exists) {
        // User exists -> go to password login
        setStep("password");
      } else {
        // New user -> go to account creation form with pre-filled identifier
        setStep("create-account");
      }
    } catch (err) {
      // If network fails, offer password login or retry
      setApiError("Unable to reach server. Please check your connection and try again.");
    } finally {
      setIsLoading(false);
    }
  };

  // 2. Existing User: Password Login
  const handlePasswordSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    setFieldErrors({});

    if (!password) {
      setFieldErrors({ password: "Password is required." });
      return;
    }

    setIsLoading(true);
    const API_URL = getApiUrl();

    try {
      const res = await fetch(`${API_URL}/auth/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: identifier.trim().toLowerCase(),
          password,
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        if (res.status === 403 && data.requiresVerification) {
          // Account unverified -> trigger OTP and route to verify
          await fetch(`${API_URL}/auth/otp/request`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ email: identifier.trim().toLowerCase(), purpose: "login" }),
          });
          setResendTimer(60);
          setStep("otp-login");
          return;
        }
        throw new Error(data.message || "Invalid email or password.");
      }

      if (data.token) {
        login(data.token);
        navigate({ to: "/dashboard" });
      } else {
        throw new Error("No token returned by server.");
      }
    } catch (err) {
      setApiError(err.message || "Sign in failed. Please check your credentials.");
    } finally {
      setIsLoading(false);
    }
  };

  // 3. New User: Create Account Submission (validates -> sends OTP)
  const handleCreateAccountSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    const errors = {};

    const cleanName = fullName.trim();
    const cleanEmail = identifier.trim().toLowerCase();
    const cleanPhone = phone.trim();

    if (!cleanName || cleanName.length < 2) {
      errors.fullName = "Full name must be at least 2 characters.";
    }
    if (!cleanEmail || !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(cleanEmail)) {
      errors.email = "Enter a valid email address.";
    }
    if (!password || password.length < 6) {
      errors.password = "Password must be at least 6 characters.";
    }
    if (password !== confirmPassword) {
      errors.confirmPassword = "Passwords do not match.";
    }
    if (cleanPhone && !/^\d{10}$/.test(cleanPhone)) {
      errors.phone = "Enter a valid 10-digit mobile number.";
    }

    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors);
      return;
    }

    setIsLoading(true);
    const API_URL = getApiUrl();

    try {
      // Send 6-digit verification code to email
      const res = await fetch(`${API_URL}/auth/otp/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: cleanEmail,
          purpose: "register",
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        if (res.status === 429) {
          const remaining = data.retryAfter || 60;
          setResendTimer(remaining);
        }
        throw new Error(data.message || "Failed to send verification code.");
      }

      setResendTimer(60);
      setOtp("");
      setStep("verify-email");
    } catch (err) {
      setApiError(err.message || "Could not send verification code. Please try again.");
    } finally {
      setIsLoading(false);
    }
  };

  // 4. New User: OTP Email Verification & Final Registration
  const handleVerifyEmailSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    setFieldErrors({});

    const cleanOtp = otp.trim();
    if (!cleanOtp || !/^\d{6}$/.test(cleanOtp)) {
      setFieldErrors({ otp: "Please enter the complete 6-digit OTP." });
      return;
    }

    setIsLoading(true);
    const API_URL = getApiUrl();

    try {
      const cleanName = fullName.trim();
      const parts = cleanName.split(" ");
      const firstName = parts[0] || "Farmer";
      const lastName = parts.slice(1).join(" ") || "";

      const res = await fetch(`${API_URL}/auth/register`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: identifier.trim().toLowerCase(),
          password,
          name: cleanName,
          firstName,
          lastName,
          phone: phone.trim() || undefined,
          otp: cleanOtp,
          role: "farmer",
          farmingMode: "moderate",
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.message || "Verification failed. Please check the code.");
      }

      if (data.token) {
        login(data.token);
        navigate({ to: "/dashboard" });
      } else {
        throw new Error("Missing authentication token.");
      }
    } catch (err) {
      setApiError(err.message || "Email verification failed.");
    } finally {
      setIsLoading(false);
    }
  };

  // 5. Existing User: Direct OTP Login Submission
  const handleOtpLoginSubmit = async (e) => {
    e.preventDefault();
    setApiError("");
    setFieldErrors({});

    const cleanOtp = otp.trim();
    if (!cleanOtp || !/^\d{6}$/.test(cleanOtp)) {
      setFieldErrors({ otp: "Please enter the complete 6-digit OTP." });
      return;
    }

    setIsLoading(true);
    const API_URL = getApiUrl();

    try {
      const res = await fetch(`${API_URL}/auth/otp/verify`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: identifier.trim().toLowerCase(),
          otp: cleanOtp,
          purpose: "login",
        }),
      });
      const data = await res.json().catch(() => ({}));

      if (!res.ok) {
        throw new Error(data.message || "Invalid or expired OTP.");
      }

      if (data.token) {
        login(data.token);
        navigate({ to: "/dashboard" });
      } else {
        throw new Error("Unable to complete login.");
      }
    } catch (err) {
      setApiError(err.message || "OTP verification failed.");
    } finally {
      setIsLoading(false);
    }
  };

  // Resend OTP handler for both new & existing users
  const handleResendOtp = async (purpose = "register") => {
    if (resendTimer > 0 || isLoading) return;
    setApiError("");
    setIsLoading(true);
    const API_URL = getApiUrl();
    try {
      const res = await fetch(`${API_URL}/auth/otp/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: identifier.trim().toLowerCase(),
          purpose,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "Failed to resend OTP.");
      setResendTimer(60);
    } catch (err) {
      setApiError(err.message || "Failed to resend code.");
    } finally {
      setIsLoading(false);
    }
  };

  // Switch to OTP Login flow
  const handleRequestOtpLogin = async () => {
    setApiError("");
    setIsLoading(true);
    const API_URL = getApiUrl();
    try {
      const res = await fetch(`${API_URL}/auth/otp/request`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: identifier.trim().toLowerCase(),
          purpose: "login",
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "Failed to send OTP.");
      setResendTimer(60);
      setOtp("");
      setStep("otp-login");
    } catch (err) {
      setApiError(err.message || "Could not send OTP.");
    } finally {
      setIsLoading(false);
    }
  };

  // 6. Forgot Password Handlers
  const handleForgotRequestOtp = async (e) => {
    e.preventDefault();
    setApiError("");
    const cleanEmail = identifier.trim().toLowerCase();
    if (!cleanEmail) {
      setFieldErrors({ identifier: "Email address is required." });
      return;
    }
    setIsLoading(true);
    const API_URL = getApiUrl();
    try {
      const res = await fetch(`${API_URL}/auth/forgot-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: cleanEmail }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "Failed to send reset code.");
      setForgotStep("otp");
    } catch (err) {
      setApiError(err.message || "Failed to send reset code.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleForgotResetPassword = async (e) => {
    e.preventDefault();
    setApiError("");
    if (!forgotOtp.trim()) {
      setApiError("Please enter the 6-digit reset OTP.");
      return;
    }
    if (!forgotNewPassword || forgotNewPassword.length < 6) {
      setApiError("New password must be at least 6 characters.");
      return;
    }
    if (forgotNewPassword !== forgotConfirmPassword) {
      setApiError("Passwords do not match.");
      return;
    }

    setIsLoading(true);
    const API_URL = getApiUrl();
    try {
      const res = await fetch(`${API_URL}/auth/reset-password`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          email: identifier.trim().toLowerCase(),
          otp: forgotOtp.trim(),
          newPassword: forgotNewPassword,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.message || "Failed to reset password.");
      setForgotStep("success");
    } catch (err) {
      setApiError(err.message || "Failed to reset password.");
    } finally {
      setIsLoading(false);
    }
  };

  // 7. Google OAuth Handlers
  const handleGoogleSuccess = async (accessToken) => {
    setIsLoading(true);
    setApiError("");
    setGoogleNotice("");
    const API_URL = getApiUrl();
    try {
      const res = await fetch(`${API_URL}/auth/google`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ accessToken }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.message || "Google sign-in failed.");
      }
      if (data.token) {
        login(data.token);
        navigate({ to: "/dashboard" });
      } else {
        throw new Error("No token returned from Google authentication.");
      }
    } catch (err) {
      setApiError(err.message || "Google authentication failed.");
    } finally {
      setIsLoading(false);
    }
  };

  const handleGoogleError = (errorMessage) => {
    setGoogleNotice(errorMessage);
    setTimeout(() => setGoogleNotice(""), 6000);
  };

  return (
    <div className="grid min-h-screen bg-background lg:grid-cols-2 overflow-x-hidden">
      {/* Left: Authentication Interaction Column */}
      <div className="hero-ambient relative flex flex-col px-5 py-6 sm:px-10 min-h-screen overflow-y-auto">
        <div className="flex items-center justify-between w-full">
          <Link to="/" className="w-fit">
            <BrandMark />
          </Link>
          <ThemeToggle />
        </div>

        <div className="flex flex-1 items-center justify-center py-8">
          <div className="w-full max-w-md">
            {/* Step Navigation Back Button */}
            {step !== "initial" && (
              <button
                type="button"
                onClick={() => {
                  if (step === "forgot-password") {
                    setStep("password");
                    setForgotStep("email");
                  } else if (step === "verify-email") {
                    setStep("create-account");
                  } else {
                    setStep("initial");
                  }
                  setApiError("");
                  setFieldErrors({});
                }}
                className="mb-4 text-xs font-medium text-muted-foreground hover:text-foreground flex items-center gap-1.5 transition-colors cursor-pointer"
              >
                <ArrowLeft className="h-3.5 w-3.5" /> Back
              </button>
            )}

            {/* Elevated Auth Card with 5-Level Surface Hierarchy */}
            <div className="glass-strong rounded-3xl p-6 sm:p-8 shadow-xl border border-border">
              {/* Notifications & Error Alerts */}
              {googleNotice && (
                <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-warning/40 bg-warning/10 px-3.5 py-3 text-xs text-foreground">
                  <AlertCircle className="h-4 w-4 text-warning mt-0.5 shrink-0" />
                  <p className="leading-snug">{googleNotice}</p>
                </div>
              )}

              {apiError && (
                <div className="mb-4 flex items-start gap-2.5 rounded-xl border border-destructive/30 bg-destructive/10 px-3.5 py-3 text-sm text-destructive">
                  <AlertCircle className="h-4 w-4 mt-0.5 shrink-0" />
                  <p className="leading-snug text-xs sm:text-sm">{apiError}</p>
                </div>
              )}

              {/* ─────────────────────────────────────────────────────────────
                  STEP 1: INITIAL SCREEN (Email or username first)
                  ───────────────────────────────────────────────────────────── */}
              {step === "initial" && (
                <div>
                  <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
                    Welcome to KrishiMitra
                  </h1>
                  <p className="mt-1.5 text-sm text-muted-foreground">
                    Smart farming intelligence for every growing season.
                  </p>

                  <form className="mt-6 space-y-4" onSubmit={handleInitialSubmit}>
                    <div>
                      <label
                        htmlFor="identifier-input"
                        className="mb-1.5 block text-xs font-medium text-foreground"
                      >
                        Email or username
                      </label>
                      <div
                        className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-3 transition-all bg-background/80 focus-within:ring-2 focus-within:ring-primary/20 ${
                          fieldErrors.identifier
                            ? "border-destructive focus-within:border-destructive"
                            : "border-input focus-within:border-primary focus-within:bg-background"
                        }`}
                      >
                        <Mail
                          className={`h-4 w-4 shrink-0 ${fieldErrors.identifier ? "text-destructive" : "text-muted-foreground"}`}
                        />
                        <input
                          id="identifier-input"
                          type="text"
                          name="identifier"
                          autoFocus
                          autoComplete="username"
                          value={identifier}
                          onChange={(e) => {
                            setIdentifier(e.target.value);
                            clearError("identifier");
                          }}
                          placeholder="name@example.com or username"
                          className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                        />
                      </div>
                      {fieldErrors.identifier && (
                        <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" /> {fieldErrors.identifier}
                        </p>
                      )}
                    </div>

                    <button
                      type="submit"
                      disabled={isLoading}
                      className="group flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-sm font-bold text-primary-foreground shadow-md hover:bg-primary-hover transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-60 cursor-pointer"
                    >
                      {isLoading ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" /> Continuing...
                        </>
                      ) : (
                        <>
                          Continue
                          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                        </>
                      )}
                    </button>
                  </form>

                  {/* Divider */}
                  <div className="relative my-6 flex items-center justify-center">
                    <div className="w-full border-t border-border" />
                    <span className="absolute bg-surface px-3 text-xs uppercase tracking-wider text-muted-foreground font-medium">
                      or
                    </span>
                  </div>

                  {/* Google OAuth Button */}
                  <GoogleAuthButton
                    onStart={() => setIsLoading(true)}
                    onSuccess={handleGoogleSuccess}
                    onError={handleGoogleError}
                    disabled={isLoading}
                  />

                  {/* Direct New User Switch */}
                  <div className="mt-6 text-center text-xs text-muted-foreground">
                    New to KrishiMitra?{" "}
                    <button
                      type="button"
                      onClick={() => {
                        setStep("create-account");
                        setApiError("");
                        setFieldErrors({});
                      }}
                      className="font-semibold text-primary hover:underline cursor-pointer"
                    >
                      Create account
                    </button>
                  </div>
                </div>
              )}

              {/* ─────────────────────────────────────────────────────────────
                  STEP 2: EXISTING USER PASSWORD LOGIN
                  ───────────────────────────────────────────────────────────── */}
              {step === "password" && (
                <div>
                  <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
                    Welcome back
                  </h1>
                  <p className="mt-1.5 text-sm text-muted-foreground">
                    Sign in to your account for{" "}
                    <span className="font-semibold text-foreground">{identifier}</span>.
                  </p>

                  <form className="mt-6 space-y-4" onSubmit={handlePasswordSubmit}>
                    <div>
                      <div className="flex items-center justify-between mb-1.5">
                        <label
                          htmlFor="password-input"
                          className="block text-xs font-medium text-foreground"
                        >
                          Password
                        </label>
                        <button
                          type="button"
                          onClick={() => {
                            setStep("forgot-password");
                            setForgotStep("email");
                            setApiError("");
                          }}
                          className="text-xs text-muted-foreground hover:text-primary transition-colors cursor-pointer"
                        >
                          Forgot password?
                        </button>
                      </div>
                      <div
                        className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-3 transition-all bg-background/80 focus-within:ring-2 focus-within:ring-primary/20 ${
                          fieldErrors.password
                            ? "border-destructive focus-within:border-destructive"
                            : "border-input focus-within:border-primary focus-within:bg-background"
                        }`}
                      >
                        <Lock
                          className={`h-4 w-4 shrink-0 ${fieldErrors.password ? "text-destructive" : "text-muted-foreground"}`}
                        />
                        <input
                          id="password-input"
                          type={showPassword ? "text" : "password"}
                          name="password"
                          autoFocus
                          autoComplete="current-password"
                          value={password}
                          onChange={(e) => {
                            setPassword(e.target.value);
                            clearError("password");
                          }}
                          placeholder="Enter your password"
                          className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword((prev) => !prev)}
                          className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer"
                          aria-label={showPassword ? "Hide password" : "Show password"}
                        >
                          {showPassword ? (
                            <EyeOff className="h-4 w-4" />
                          ) : (
                            <Eye className="h-4 w-4" />
                          )}
                        </button>
                      </div>
                      {fieldErrors.password && (
                        <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" /> {fieldErrors.password}
                        </p>
                      )}
                    </div>

                    <button
                      type="submit"
                      disabled={isLoading}
                      className="group flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-sm font-bold text-primary-foreground shadow-md hover:bg-primary-hover transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-60 cursor-pointer"
                    >
                      {isLoading ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" /> Signing in...
                        </>
                      ) : (
                        <>
                          Sign in
                          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                        </>
                      )}
                    </button>
                  </form>

                  {/* Passwordless OTP alternative */}
                  <div className="mt-4 pt-3 border-t border-border/60 text-center">
                    <button
                      type="button"
                      onClick={handleRequestOtpLogin}
                      disabled={isLoading}
                      className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-primary transition-colors cursor-pointer"
                    >
                      <KeyRound className="h-3.5 w-3.5" /> Sign in with OTP code instead
                    </button>
                  </div>

                  {/* Divider */}
                  <div className="relative my-5 flex items-center justify-center">
                    <div className="w-full border-t border-border" />
                    <span className="absolute bg-surface px-3 text-xs uppercase tracking-wider text-muted-foreground font-medium">
                      or
                    </span>
                  </div>

                  {/* Google OAuth Button */}
                  <GoogleAuthButton
                    onStart={() => setIsLoading(true)}
                    onSuccess={handleGoogleSuccess}
                    onError={handleGoogleError}
                    disabled={isLoading}
                  />
                </div>
              )}

              {/* ─────────────────────────────────────────────────────────────
                  STEP 3: NEW USER REGISTRATION FORM
                  ───────────────────────────────────────────────────────────── */}
              {step === "create-account" && (
                <div>
                  <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
                    Create your KrishiMitra account
                  </h1>
                  <p className="mt-1.5 text-sm text-muted-foreground">
                    Start AI-powered farm planning in minutes.
                  </p>

                  <form className="mt-6 space-y-3.5" onSubmit={handleCreateAccountSubmit}>
                    {/* Full Name */}
                    <div>
                      <label
                        htmlFor="fullname-input"
                        className="mb-1 block text-xs font-medium text-foreground"
                      >
                        Full Name <span className="text-primary">*</span>
                      </label>
                      <div
                        className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 transition-all bg-background/80 focus-within:ring-2 focus-within:ring-primary/20 ${
                          fieldErrors.fullName
                            ? "border-destructive focus-within:border-destructive"
                            : "border-input focus-within:border-primary focus-within:bg-background"
                        }`}
                      >
                        <UserRound
                          className={`h-4 w-4 shrink-0 ${fieldErrors.fullName ? "text-destructive" : "text-muted-foreground"}`}
                        />
                        <input
                          id="fullname-input"
                          type="text"
                          name="fullName"
                          autoFocus
                          autoComplete="name"
                          value={fullName}
                          onChange={(e) => {
                            setFullName(e.target.value);
                            clearError("fullName");
                          }}
                          placeholder="e.g. Ramesh Patil"
                          className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                        />
                      </div>
                      {fieldErrors.fullName && (
                        <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" /> {fieldErrors.fullName}
                        </p>
                      )}
                    </div>

                    {/* Email */}
                    <div>
                      <label
                        htmlFor="email-input"
                        className="mb-1 block text-xs font-medium text-foreground"
                      >
                        Email Address <span className="text-primary">*</span>
                      </label>
                      <div
                        className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 transition-all bg-background/80 focus-within:ring-2 focus-within:ring-primary/20 ${
                          fieldErrors.email
                            ? "border-destructive focus-within:border-destructive"
                            : "border-input focus-within:border-primary focus-within:bg-background"
                        }`}
                      >
                        <Mail
                          className={`h-4 w-4 shrink-0 ${fieldErrors.email ? "text-destructive" : "text-muted-foreground"}`}
                        />
                        <input
                          id="email-input"
                          type="email"
                          name="email"
                          autoComplete="email"
                          value={identifier}
                          onChange={(e) => {
                            setIdentifier(e.target.value);
                            clearError("email");
                          }}
                          placeholder="you@example.com"
                          className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                        />
                      </div>
                      {fieldErrors.email && (
                        <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" /> {fieldErrors.email}
                        </p>
                      )}
                    </div>

                    {/* Password */}
                    <div>
                      <label
                        htmlFor="new-password-input"
                        className="mb-1 block text-xs font-medium text-foreground"
                      >
                        Password <span className="text-primary">*</span>
                      </label>
                      <div
                        className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 transition-all bg-background/80 focus-within:ring-2 focus-within:ring-primary/20 ${
                          fieldErrors.password
                            ? "border-destructive focus-within:border-destructive"
                            : "border-input focus-within:border-primary focus-within:bg-background"
                        }`}
                      >
                        <Lock
                          className={`h-4 w-4 shrink-0 ${fieldErrors.password ? "text-destructive" : "text-muted-foreground"}`}
                        />
                        <input
                          id="new-password-input"
                          type={showPassword ? "text" : "password"}
                          name="password"
                          autoComplete="new-password"
                          value={password}
                          onChange={(e) => {
                            setPassword(e.target.value);
                            clearError("password");
                          }}
                          placeholder="At least 6 characters"
                          className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                        />
                        <button
                          type="button"
                          onClick={() => setShowPassword((p) => !p)}
                          className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer"
                        >
                          {showPassword ? (
                            <EyeOff className="h-4 w-4" />
                          ) : (
                            <Eye className="h-4 w-4" />
                          )}
                        </button>
                      </div>
                      {fieldErrors.password && (
                        <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" /> {fieldErrors.password}
                        </p>
                      )}
                    </div>

                    {/* Confirm Password */}
                    <div>
                      <label
                        htmlFor="confirm-password-input"
                        className="mb-1 block text-xs font-medium text-foreground"
                      >
                        Confirm Password <span className="text-primary">*</span>
                      </label>
                      <div
                        className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 transition-all bg-background/80 focus-within:ring-2 focus-within:ring-primary/20 ${
                          fieldErrors.confirmPassword
                            ? "border-destructive focus-within:border-destructive"
                            : "border-input focus-within:border-primary focus-within:bg-background"
                        }`}
                      >
                        <Lock
                          className={`h-4 w-4 shrink-0 ${fieldErrors.confirmPassword ? "text-destructive" : "text-muted-foreground"}`}
                        />
                        <input
                          id="confirm-password-input"
                          type={showConfirmPassword ? "text" : "password"}
                          name="confirmPassword"
                          autoComplete="new-password"
                          value={confirmPassword}
                          onChange={(e) => {
                            setConfirmPassword(e.target.value);
                            clearError("confirmPassword");
                          }}
                          placeholder="Repeat password"
                          className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                        />
                        <button
                          type="button"
                          onClick={() => setShowConfirmPassword((p) => !p)}
                          className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer"
                        >
                          {showConfirmPassword ? (
                            <EyeOff className="h-4 w-4" />
                          ) : (
                            <Eye className="h-4 w-4" />
                          )}
                        </button>
                      </div>
                      {fieldErrors.confirmPassword && (
                        <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" /> {fieldErrors.confirmPassword}
                        </p>
                      )}
                    </div>

                    {/* Mobile (optional) */}
                    <div>
                      <label
                        htmlFor="phone-input"
                        className="mb-1 block text-xs font-medium text-foreground"
                      >
                        Mobile Number{" "}
                        <span className="text-muted-foreground font-normal">(optional)</span>
                      </label>
                      <div
                        className={`flex items-center gap-2.5 rounded-xl border px-3.5 py-2.5 transition-all bg-background/80 focus-within:ring-2 focus-within:ring-primary/20 ${
                          fieldErrors.phone
                            ? "border-destructive focus-within:border-destructive"
                            : "border-input focus-within:border-primary focus-within:bg-background"
                        }`}
                      >
                        <Phone
                          className={`h-4 w-4 shrink-0 ${fieldErrors.phone ? "text-destructive" : "text-muted-foreground"}`}
                        />
                        <input
                          id="phone-input"
                          type="tel"
                          name="phone"
                          maxLength={10}
                          autoComplete="tel"
                          value={phone}
                          onChange={(e) => {
                            const clean = e.target.value.replace(/\D/g, "");
                            setPhone(clean);
                            clearError("phone");
                          }}
                          placeholder="10-digit number"
                          className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                        />
                      </div>
                      {fieldErrors.phone && (
                        <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" /> {fieldErrors.phone}
                        </p>
                      )}
                    </div>

                    <button
                      type="submit"
                      disabled={isLoading}
                      className="group flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-sm font-bold text-primary-foreground shadow-md hover:bg-primary-hover transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-60 cursor-pointer"
                    >
                      {isLoading ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" /> Sending verification code...
                        </>
                      ) : (
                        <>
                          Create account
                          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                        </>
                      )}
                    </button>
                  </form>

                  <div className="mt-4 text-center text-xs text-muted-foreground">
                    Already have an account?{" "}
                    <button
                      type="button"
                      onClick={() => {
                        setStep("password");
                        setApiError("");
                        setFieldErrors({});
                      }}
                      className="font-semibold text-primary hover:underline cursor-pointer"
                    >
                      Sign in
                    </button>
                  </div>
                </div>
              )}

              {/* ─────────────────────────────────────────────────────────────
                  STEP 4: VERIFY EMAIL OTP (New Registration)
                  ───────────────────────────────────────────────────────────── */}
              {step === "verify-email" && (
                <div>
                  <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
                    Verify your email
                  </h1>
                  <p className="mt-1.5 text-sm text-muted-foreground break-words">
                    We sent a 6-digit verification code to{" "}
                    <span className="font-semibold text-foreground">{maskEmail(identifier)}</span>.
                  </p>

                  <form className="mt-6 space-y-4" onSubmit={handleVerifyEmailSubmit}>
                    <div>
                      <label
                        htmlFor="otp-verify-input"
                        className="mb-1.5 block text-xs font-medium text-foreground"
                      >
                        Enter 6-Digit Code
                      </label>
                      <input
                        id="otp-verify-input"
                        ref={otpInputRef}
                        type="text"
                        inputMode="numeric"
                        maxLength={6}
                        autoFocus
                        value={otp}
                        onChange={(e) => {
                          const val = e.target.value.replace(/\D/g, "");
                          setOtp(val);
                          clearError("otp");
                        }}
                        placeholder="••••••"
                        className={`w-full rounded-xl border bg-background/80 px-3.5 py-3.5 text-center font-mono text-2xl font-bold tracking-[0.4em] text-foreground outline-none transition-all focus:ring-2 focus:ring-primary/20 ${
                          fieldErrors.otp
                            ? "border-destructive focus:border-destructive"
                            : "border-input focus:border-primary focus:bg-background"
                        }`}
                      />
                      {fieldErrors.otp && (
                        <p className="mt-1 flex items-center justify-center gap-1 text-[11px] text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" /> {fieldErrors.otp}
                        </p>
                      )}
                    </div>

                    <div className="flex items-center justify-between text-xs pt-1">
                      <button
                        type="button"
                        disabled={resendTimer > 0 || isLoading}
                        onClick={() => handleResendOtp("register")}
                        className={`font-medium transition-colors ${
                          resendTimer > 0
                            ? "text-muted-foreground cursor-not-allowed"
                            : "text-primary hover:underline cursor-pointer"
                        }`}
                      >
                        {resendTimer > 0 ? `Resend code in ${resendTimer}s` : "Resend code"}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setStep("create-account");
                          setOtp("");
                          setApiError("");
                        }}
                        className="text-muted-foreground hover:text-foreground hover:underline cursor-pointer"
                      >
                        Change details
                      </button>
                    </div>

                    <button
                      type="submit"
                      disabled={isLoading || otp.length !== 6}
                      className="group flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-sm font-bold text-primary-foreground shadow-md hover:bg-primary-hover transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-50 cursor-pointer"
                    >
                      {isLoading ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" /> Verifying email...
                        </>
                      ) : (
                        <>
                          Verify email
                          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                        </>
                      )}
                    </button>
                  </form>
                </div>
              )}

              {/* ─────────────────────────────────────────────────────────────
                  STEP 5: DIRECT OTP LOGIN (For returning user requesting OTP)
                  ───────────────────────────────────────────────────────────── */}
              {step === "otp-login" && (
                <div>
                  <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
                    Sign in with Code
                  </h1>
                  <p className="mt-1.5 text-sm text-muted-foreground break-words">
                    We sent a 6-digit sign-in code to{" "}
                    <span className="font-semibold text-foreground">{maskEmail(identifier)}</span>.
                  </p>

                  <form className="mt-6 space-y-4" onSubmit={handleOtpLoginSubmit}>
                    <div>
                      <label
                        htmlFor="otp-login-input"
                        className="mb-1.5 block text-xs font-medium text-foreground"
                      >
                        Enter 6-Digit Code
                      </label>
                      <input
                        id="otp-login-input"
                        ref={otpInputRef}
                        type="text"
                        inputMode="numeric"
                        maxLength={6}
                        autoFocus
                        value={otp}
                        onChange={(e) => {
                          const val = e.target.value.replace(/\D/g, "");
                          setOtp(val);
                          clearError("otp");
                        }}
                        placeholder="••••••"
                        className={`w-full rounded-xl border bg-background/80 px-3.5 py-3.5 text-center font-mono text-2xl font-bold tracking-[0.4em] text-foreground outline-none transition-all focus:ring-2 focus:ring-primary/20 ${
                          fieldErrors.otp
                            ? "border-destructive focus:border-destructive"
                            : "border-input focus:border-primary focus:bg-background"
                        }`}
                      />
                      {fieldErrors.otp && (
                        <p className="mt-1 flex items-center justify-center gap-1 text-[11px] text-destructive">
                          <AlertCircle className="h-3 w-3 shrink-0" /> {fieldErrors.otp}
                        </p>
                      )}
                    </div>

                    <div className="flex items-center justify-between text-xs pt-1">
                      <button
                        type="button"
                        disabled={resendTimer > 0 || isLoading}
                        onClick={() => handleResendOtp("login")}
                        className={`font-medium transition-colors ${
                          resendTimer > 0
                            ? "text-muted-foreground cursor-not-allowed"
                            : "text-primary hover:underline cursor-pointer"
                        }`}
                      >
                        {resendTimer > 0 ? `Resend code in ${resendTimer}s` : "Resend code"}
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setStep("password");
                          setOtp("");
                          setApiError("");
                        }}
                        className="text-muted-foreground hover:text-foreground hover:underline cursor-pointer"
                      >
                        Use password instead
                      </button>
                    </div>

                    <button
                      type="submit"
                      disabled={isLoading || otp.length !== 6}
                      className="group flex w-full items-center justify-center gap-2 rounded-xl bg-primary py-3.5 text-sm font-bold text-primary-foreground shadow-md hover:bg-primary-hover transition-all hover:scale-[1.01] active:scale-[0.99] disabled:opacity-50 cursor-pointer"
                    >
                      {isLoading ? (
                        <>
                          <Loader2 className="h-4 w-4 animate-spin" /> Verifying...
                        </>
                      ) : (
                        <>
                          Sign in
                          <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                        </>
                      )}
                    </button>
                  </form>
                </div>
              )}

              {/* ─────────────────────────────────────────────────────────────
                  STEP 6: FORGOT PASSWORD RECOVERY
                  ───────────────────────────────────────────────────────────── */}
              {step === "forgot-password" && (
                <div>
                  {forgotStep === "success" ? (
                    <div className="rounded-2xl border border-primary/30 bg-primary/10 p-5 text-center">
                      <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-primary/20 text-primary mb-3">
                        <CheckCircle2 className="h-6 w-6" />
                      </div>
                      <h2 className="font-display text-lg font-bold text-foreground">
                        Password updated successfully
                      </h2>
                      <p className="mt-1.5 text-xs text-muted-foreground leading-relaxed">
                        Your password has been changed. You can now sign in with your new
                        credentials.
                      </p>
                      <button
                        type="button"
                        onClick={() => {
                          setStep("password");
                          setForgotStep("email");
                          setPassword("");
                        }}
                        className="mt-5 w-full rounded-xl bg-primary py-3 text-sm font-bold text-primary-foreground shadow-md hover:bg-primary-hover transition-all cursor-pointer"
                      >
                        Return to Sign In
                      </button>
                    </div>
                  ) : forgotStep === "otp" ? (
                    <div>
                      <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
                        Set new password
                      </h1>
                      <p className="mt-1.5 text-sm text-muted-foreground">
                        Enter the recovery code sent to{" "}
                        <span className="font-semibold text-foreground">
                          {maskEmail(identifier)}
                        </span>{" "}
                        and choose a new password.
                      </p>

                      <form onSubmit={handleForgotResetPassword} className="mt-6 space-y-4">
                        <div>
                          <label
                            htmlFor="forgot-otp-input"
                            className="mb-1 block text-xs font-medium text-foreground"
                          >
                            6-Digit Recovery Code
                          </label>
                          <input
                            id="forgot-otp-input"
                            type="text"
                            inputMode="numeric"
                            maxLength={6}
                            autoFocus
                            value={forgotOtp}
                            onChange={(e) => setForgotOtp(e.target.value.replace(/\D/g, ""))}
                            placeholder="123456"
                            className="w-full rounded-xl border border-input bg-background/80 px-3.5 py-3 text-center font-mono text-xl font-bold tracking-widest text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/20"
                          />
                        </div>

                        <div>
                          <label
                            htmlFor="forgot-new-pw-input"
                            className="mb-1 block text-xs font-medium text-foreground"
                          >
                            New Password (min 6 characters)
                          </label>
                          <div className="flex items-center gap-2.5 rounded-xl border border-input bg-background/80 px-3.5 py-3 focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
                            <Lock className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <input
                              id="forgot-new-pw-input"
                              type={showPassword ? "text" : "password"}
                              value={forgotNewPassword}
                              onChange={(e) => setForgotNewPassword(e.target.value)}
                              placeholder="Enter new password"
                              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                            />
                            <button
                              type="button"
                              onClick={() => setShowPassword((p) => !p)}
                              className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer"
                            >
                              {showPassword ? (
                                <EyeOff className="h-4 w-4" />
                              ) : (
                                <Eye className="h-4 w-4" />
                              )}
                            </button>
                          </div>
                        </div>

                        <div>
                          <label
                            htmlFor="forgot-confirm-pw-input"
                            className="mb-1 block text-xs font-medium text-foreground"
                          >
                            Confirm New Password
                          </label>
                          <div className="flex items-center gap-2.5 rounded-xl border border-input bg-background/80 px-3.5 py-3 focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
                            <Lock className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <input
                              id="forgot-confirm-pw-input"
                              type={showConfirmPassword ? "text" : "password"}
                              value={forgotConfirmPassword}
                              onChange={(e) => setForgotConfirmPassword(e.target.value)}
                              placeholder="Repeat new password"
                              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                            />
                            <button
                              type="button"
                              onClick={() => setShowConfirmPassword((p) => !p)}
                              className="shrink-0 text-muted-foreground hover:text-foreground cursor-pointer"
                            >
                              {showConfirmPassword ? (
                                <EyeOff className="h-4 w-4" />
                              ) : (
                                <Eye className="h-4 w-4" />
                              )}
                            </button>
                          </div>
                        </div>

                        <button
                          type="submit"
                          disabled={isLoading}
                          className="w-full rounded-xl bg-primary py-3.5 text-sm font-bold text-primary-foreground shadow-md hover:bg-primary-hover transition-all cursor-pointer disabled:opacity-60"
                        >
                          {isLoading ? "Updating password..." : "Update Password"}
                        </button>
                      </form>
                    </div>
                  ) : (
                    <div>
                      <h1 className="font-display text-2xl font-bold tracking-tight text-foreground">
                        Reset password
                      </h1>
                      <p className="mt-1.5 text-sm text-muted-foreground">
                        Enter your account email to receive a 6-digit recovery code.
                      </p>

                      <form onSubmit={handleForgotRequestOtp} className="mt-6 space-y-4">
                        <div>
                          <label
                            htmlFor="recovery-email-input"
                            className="mb-1.5 block text-xs font-medium text-foreground"
                          >
                            Account Email Address
                          </label>
                          <div className="flex items-center gap-2.5 rounded-xl border border-input bg-background/80 px-3.5 py-3 focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
                            <Mail className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <input
                              id="recovery-email-input"
                              type="email"
                              autoFocus
                              value={identifier}
                              onChange={(e) => setIdentifier(e.target.value)}
                              placeholder="you@example.com"
                              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
                            />
                          </div>
                        </div>

                        <div className="flex gap-3 pt-2">
                          <button
                            type="button"
                            onClick={() => setStep("password")}
                            className="flex-1 rounded-xl border border-border py-3 text-sm font-medium hover:bg-surface-2 transition-colors cursor-pointer"
                          >
                            Cancel
                          </button>
                          <button
                            type="submit"
                            disabled={isLoading}
                            className="flex-1 rounded-xl bg-primary py-3 text-sm font-bold text-primary-foreground hover:bg-primary-hover shadow-md transition-all cursor-pointer disabled:opacity-60"
                          >
                            {isLoading ? "Sending..." : "Send Reset Code"}
                          </button>
                        </div>
                      </form>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Right: Visual Brand Hero Column (Preserved & Enhanced) */}
      <div className="relative hidden overflow-hidden border-l border-border lg:block bg-muted">
        <img
          src="/auth-farm.png"
          alt="Precision agriculture fields with intelligence overlay"
          loading="lazy"
          className="absolute inset-0 h-full w-full object-cover opacity-90"
        />
        <div className="absolute inset-0 bg-gradient-to-t from-background via-background/50 to-transparent" />

        <div className="absolute top-12 right-12 hidden xl:block">
          <div className="glass-strong float-slow w-fit rounded-2xl px-5 py-4 shadow-xl border border-border/80">
            <div className="flex items-center gap-3">
              <div className="h-10 w-10 rounded-full bg-primary/20 flex items-center justify-center">
                <BarChart3 className="h-5 w-5 text-primary" />
              </div>
              <div>
                <div className="text-[10px] uppercase tracking-widest text-muted-foreground font-semibold">
                  Projected Yield
                </div>
                <div className="mt-0.5 text-lg font-bold text-foreground">
                  14,250 <span className="text-sm font-normal text-muted-foreground">kg/ha</span>
                </div>
              </div>
            </div>
          </div>
        </div>

        <div className="absolute bottom-12 left-12 right-12 flex flex-col items-start gap-10">
          <div className="glass-strong float-slow-delayed w-fit rounded-2xl px-5 py-4 shadow-xl border border-border/80">
            <div className="flex items-center gap-2.5 mb-1.5">
              <ShieldCheck className="h-4 w-4 text-primary" />
              <div className="text-[10px] uppercase tracking-widest text-primary font-bold">
                Smart Advisory Active
              </div>
            </div>
            <div className="text-sm font-semibold text-foreground">Optimal irrigation window</div>
            <div className="text-xs text-muted-foreground mt-0.5">6:00 AM - 9:00 AM Tomorrow</div>
          </div>

          <div>
            <h2 className="max-w-xl font-display text-4xl font-bold leading-tight tracking-tight text-foreground">
              Your farm's data, <br /> working{" "}
              <span className="text-primary italic pr-2">for you.</span>
            </h2>
            <p className="mt-3 max-w-md text-base text-muted-foreground leading-relaxed">
              Soil, weather, crop planning, and market intelligence — beautifully unified into one
              proactive platform.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
