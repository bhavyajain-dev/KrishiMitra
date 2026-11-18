import { Link, createFileRoute } from "@tanstack/react-router";
import { BrandMark, ThemeToggle } from "@/components/app/AppShell";
import {
  Sprout, ChevronRight, CloudRain, Camera, Leaf, TrendingUp, FlaskConical,
  MessagesSquare, IndianRupee, CalendarRange, Wallet, MapPinned, Sparkles,
} from "lucide-react";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "KrishiMitra — Intelligence that grows with you." },
    ],
  }),
  component: Landing,
});

function Landing() {
  return (
    <div className="min-h-screen bg-background text-foreground font-sans selection:bg-primary/30">
      
      {/* Navbar */}
      <header className="fixed top-4 sm:top-6 left-1/2 -translate-x-1/2 z-50 w-[95%] sm:w-[90%] max-w-5xl rounded-full glass border border-foreground/10 px-3.5 sm:px-6 py-2 sm:py-3 flex items-center justify-between shadow-2xl">
        <BrandMark />
        <div className="flex items-center gap-1.5 xs:gap-2.5 sm:gap-4 shrink-0">
          <ThemeToggle />
          <Link
            to="/auth"
            search={{ mode: "login" }}
            className="text-xs sm:text-sm font-medium text-foreground hover:text-primary transition-colors whitespace-nowrap px-1.5 py-1"
          >
            Log in
          </Link>
          <Link
            to="/auth"
            search={{ mode: "signup" }}
            className="rounded-full bg-primary/20 text-primary border border-primary/50 px-3 py-1.5 sm:px-5 sm:py-2 text-xs sm:text-sm font-bold transition-all hover:bg-primary hover:text-background hover:glow-emerald whitespace-nowrap inline-flex items-center shrink-0"
          >
            <span>Get Started</span>
            <ChevronRight className="inline h-3.5 w-3.5 sm:h-4 sm:w-4 ml-0.5 sm:ml-1 shrink-0" />
          </Link>
        </div>
      </header>

      {/* Hero Section */}
      <section className="relative flex flex-col items-center pt-32 pb-16 sm:pt-48 sm:pb-32 overflow-hidden px-6">
        {/* Background */}
        <div className="absolute inset-0 z-0">
           <img 
             src="https://images.unsplash.com/photo-1591857177580-dc82b9ac4e1e?auto=format&fit=crop&w=2000&q=80" 
             alt="Lush moss background" 
             className="w-full h-full object-cover opacity-30 mix-blend-luminosity"
           />
           <div className="absolute inset-0 bg-gradient-to-b from-background/50 via-background/80 to-background" />
        </div>

        <div className="relative z-10 w-full max-w-5xl flex flex-col items-center text-center">
          
          <div className="inline-flex max-w-full items-center gap-2 whitespace-nowrap rounded-full border border-primary/30 bg-primary/10 px-4 py-1.5 text-xs font-semibold text-primary mb-8 glow-emerald">
             <div className="h-2 w-2 shrink-0 rounded-full bg-primary animate-pulse" />
             <span className="sm:hidden">Your Smart Farming Assistant</span>
             <span className="hidden sm:inline">Welcome to KrishiMitra: Your Smart Farming Assistant</span>
             <ChevronRight className="h-3 w-3 shrink-0" />
          </div>

          <h1 className="font-display text-[2.35rem] sm:text-7xl font-bold tracking-tight text-foreground mb-6 leading-[1.1] text-balance">
            Intelligence that <br />
            <span className="text-primary italic pr-2">grows</span> with you.
          </h1>

          <p className="text-muted-foreground text-base sm:text-xl max-w-2xl mb-10">
            Crop recommendations from your soil test, weather alerts, leaf disease detection and mandi prices, in one place for Indian farmers.
          </p>

          <Link to="/auth" search={{ mode: "signup" }} className="rounded-full bg-primary text-background px-8 py-4 text-base font-bold transition-all hover:scale-105 glow-emerald flex items-center gap-2 mb-6">
            Get Started Free <ChevronRight className="h-5 w-5" />
          </Link>

          {/* Removed trial badges per user request */}
        </div>

        {/* Core features (real KrishiMitra capabilities) */}
        <div className="relative z-10 w-full max-w-6xl mt-12 sm:mt-24 grid grid-cols-1 md:grid-cols-3 gap-6">

          {/* ML crop recommendations */}
          <div className="glass-strong rounded-3xl p-6 sm:p-8 hover:-translate-y-2 transition-transform duration-500">
             <div className="h-12 w-12 rounded-xl border border-foreground/20 flex items-center justify-center mb-6">
                <Sprout className="text-primary h-6 w-6" />
             </div>
             <h3 className="text-xl font-bold text-foreground mb-3">ML crop recommendations</h3>
             <p className="text-muted-foreground text-sm leading-relaxed mb-8">
               A trained model ranks 25 crops for your farm from your soil test, local climate, season and state.
             </p>
             <div className="h-32 rounded-xl border border-foreground/10 bg-background/40 flex items-center justify-center overflow-hidden relative">
                 <div className="absolute left-3 top-1/2 -translate-y-1/2 flex flex-col gap-2">
                    {["Soil test", "Climate", "Season"].map((label) => (
                      <div key={label} className="rounded-md bg-foreground/10 px-2 py-1 text-[10px] font-medium text-muted-foreground">{label}</div>
                    ))}
                 </div>
                 <svg className="absolute left-20 right-14 h-full w-[calc(100%-8.5rem)] opacity-30" preserveAspectRatio="none">
                    <path d="M0 20 C 50 20, 50 60, 100 60 M0 50 C 50 50, 50 60, 100 60 M0 80 C 50 80, 50 60, 100 60" stroke="var(--color-primary)" fill="none" strokeWidth="2" strokeDasharray="4 4"/>
                 </svg>
                 <div className="absolute right-4 h-12 w-12 rounded-xl border border-primary/50 bg-primary/20 flex items-center justify-center glow-emerald">
                    <Sprout className="text-primary h-6 w-6" />
                 </div>
             </div>
          </div>

          {/* Leaf disease detection */}
          <div className="glass-strong rounded-3xl p-6 sm:p-8 hover:-translate-y-2 transition-transform duration-500">
             <div className="h-12 w-12 rounded-xl border border-foreground/20 flex items-center justify-center mb-6">
                <Camera className="text-primary h-6 w-6" />
             </div>
             <h3 className="text-xl font-bold text-foreground mb-3">Leaf disease detection</h3>
             <p className="text-muted-foreground text-sm leading-relaxed mb-8">
               Upload a photo of a leaf to identify the disease and get treatment steps.
             </p>
             <div className="h-32 rounded-xl border border-foreground/10 bg-background/40 flex items-center justify-center relative overflow-hidden">
                <div className="relative h-20 w-20">
                  <span className="absolute left-0 top-0 h-4 w-4 border-l-2 border-t-2 border-primary rounded-tl" />
                  <span className="absolute right-0 top-0 h-4 w-4 border-r-2 border-t-2 border-primary rounded-tr" />
                  <span className="absolute left-0 bottom-0 h-4 w-4 border-l-2 border-b-2 border-primary rounded-bl" />
                  <span className="absolute right-0 bottom-0 h-4 w-4 border-r-2 border-b-2 border-primary rounded-br" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <Leaf className="h-9 w-9 text-primary" />
                  </div>
                  <div className="absolute inset-x-1 top-1/2 h-0.5 bg-primary/70 glow-emerald animate-pulse" />
                </div>
             </div>
          </div>

          {/* Weather & risk alerts */}
          <div className="glass-strong rounded-3xl p-6 sm:p-8 hover:-translate-y-2 transition-transform duration-500">
             <div className="h-12 w-12 rounded-xl border border-foreground/20 flex items-center justify-center mb-6">
                <CloudRain className="text-primary h-6 w-6" />
             </div>
             <h3 className="text-xl font-bold text-foreground mb-3">Weather & risk alerts</h3>
             <p className="text-muted-foreground text-sm leading-relaxed mb-8">
               A 16-day forecast for your farm, with alerts for heavy rain, heat and disease-prone humidity.
             </p>
             <div className="h-32 rounded-xl border border-foreground/10 bg-background/40 flex items-center justify-center relative overflow-hidden">
                <div className="absolute inset-0 flex items-center justify-center">
                  <div className="h-32 w-32 rounded-full border border-primary/20" />
                  <div className="absolute h-20 w-20 rounded-full border border-primary/40" />
                  <div className="absolute h-8 w-8 rounded-full border border-primary text-primary flex items-center justify-center bg-primary/10 glow-emerald">
                     <CloudRain className="h-3 w-3" />
                  </div>
                </div>
                <div className="absolute inset-0 bg-gradient-to-tr from-transparent via-primary/5 to-transparent animate-[spin_4s_linear_infinite]" style={{ transformOrigin: 'center' }} />
             </div>
          </div>

        </div>
      </section>

      {/* More features + how it works */}
      <section className="relative py-12 sm:py-24 px-4 sm:px-6 flex justify-center overflow-hidden">
        <div className="relative z-10 w-full max-w-5xl glass-strong rounded-[2.5rem] border border-foreground/20 p-5 sm:p-12 shadow-2xl overflow-hidden">

           <div className="mb-8 sm:mb-10">
              <div className="text-muted-foreground text-sm font-semibold uppercase tracking-wider mb-2">What KrishiMitra does</div>
              <h2 className="text-3xl sm:text-5xl font-bold text-foreground tracking-tight">Everything for your farm</h2>
           </div>

           <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4 sm:gap-6">
              <div className="rounded-2xl border border-foreground/10 bg-foreground/5 p-6 backdrop-blur-md">
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-primary/30 bg-primary/10">
                  <TrendingUp className="h-5 w-5 text-primary" />
                </div>
                <h3 className="mb-2 text-base font-semibold text-foreground">Yield prediction</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">Expected yield in tonnes per hectare for each crop, from a model trained on two decades of Indian crop data.</p>
              </div>
              <div className="rounded-2xl border border-foreground/10 bg-foreground/5 p-6 backdrop-blur-md">
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-primary/30 bg-primary/10">
                  <FlaskConical className="h-5 w-5 text-primary" />
                </div>
                <h3 className="mb-2 text-base font-semibold text-foreground">Fertilizer plans</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">Doses for every growth stage of your crop, based on ICAR guidelines.</p>
              </div>
              <div className="rounded-2xl border border-foreground/10 bg-foreground/5 p-6 backdrop-blur-md">
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-primary/30 bg-primary/10">
                  <MessagesSquare className="h-5 w-5 text-primary" />
                </div>
                <h3 className="mb-2 text-base font-semibold text-foreground">AI Mitra assistant</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">Ask farming questions in plain language and get answers grounded in a verified knowledge base.</p>
              </div>
              <div className="rounded-2xl border border-foreground/10 bg-foreground/5 p-6 backdrop-blur-md">
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-primary/30 bg-primary/10">
                  <IndianRupee className="h-5 w-5 text-primary" />
                </div>
                <h3 className="mb-2 text-base font-semibold text-foreground">Mandi prices</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">Daily commodity prices from APMC markets across India, from data.gov.in.</p>
              </div>
              <div className="rounded-2xl border border-foreground/10 bg-foreground/5 p-6 backdrop-blur-md">
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-primary/30 bg-primary/10">
                  <CalendarRange className="h-5 w-5 text-primary" />
                </div>
                <h3 className="mb-2 text-base font-semibold text-foreground">Crop plan</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">A stage-by-stage timeline from land preparation to harvest, with field tips for each stage.</p>
              </div>
              <div className="rounded-2xl border border-foreground/10 bg-foreground/5 p-6 backdrop-blur-md">
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-xl border border-primary/30 bg-primary/10">
                  <Wallet className="h-5 w-5 text-primary" />
                </div>
                <h3 className="mb-2 text-base font-semibold text-foreground">Expense tracker</h3>
                <p className="text-sm leading-relaxed text-muted-foreground">Log farm costs per crop and season, and see where your money goes.</p>
              </div>
           </div>

           <div className="mt-10 sm:mt-14 border-t border-foreground/10 pt-8 sm:pt-10">
              <h3 className="mb-6 text-xl sm:text-2xl font-bold text-foreground">How it works</h3>
              <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div className="flex items-start gap-4">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-background">1</div>
                <div>
                  <h4 className="flex items-center gap-2 font-semibold text-foreground"><MapPinned className="h-4 w-4 text-primary" />Add your farm</h4>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">Location, area, water source and your Soil Health Card values.</p>
                </div>
              </div>
              <div className="flex items-start gap-4">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-background">2</div>
                <div>
                  <h4 className="flex items-center gap-2 font-semibold text-foreground"><Sparkles className="h-4 w-4 text-primary" />Get recommendations</h4>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">Crops ranked for your soil and climate, with yield, fertilizer and irrigation advice.</p>
                </div>
              </div>
              <div className="flex items-start gap-4">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-background">3</div>
                <div>
                  <h4 className="flex items-center gap-2 font-semibold text-foreground"><CalendarRange className="h-4 w-4 text-primary" />Plan, track and sell</h4>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">Follow your crop plan, log expenses and check mandi prices.</p>
                </div>
              </div>
              </div>
              <div className="mt-8 flex justify-center">
                <Link to="/auth" search={{ mode: "signup" }} className="rounded-full bg-primary text-background px-7 py-3 text-sm font-bold transition-all hover:scale-105 glow-emerald flex items-center gap-2">
                  Get Started Free <ChevronRight className="h-4 w-4" />
                </Link>
              </div>
           </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t border-foreground/10 px-6 py-8">
        <div className="mx-auto flex max-w-5xl flex-col items-center justify-between gap-3 text-center sm:flex-row sm:text-left">
          <BrandMark />
          <p className="text-xs text-muted-foreground">© 2026 KrishiMitra · Smart farming assistant for Indian farmers</p>
        </div>
      </footer>
    </div>
  );
}
