import { currentSeason } from "@/lib/season";
import { API_URL } from "@/lib/api";
import { createFileRoute } from "@tanstack/react-router";
import { useState, useEffect, useCallback, useMemo } from "react";
import { Plus, TrendingUp, Wallet, AlertCircle, Trash2 } from "lucide-react";
import { useAppData } from "@/lib/AppDataContext";
import { PageHeader } from "@/components/app/AppShell";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";
import { toast } from "sonner";
import { apiErrorMessage } from "@/lib/validation";

function formatRs(value) {
  const n = Number(value) || 0;
  const paise = !Number.isInteger(Math.round(n * 100) / 100);
  return n.toLocaleString("en-IN", { minimumFractionDigits: paise ? 2 : 0, maximumFractionDigits: 2 });
}

export const Route = createFileRoute("/_app/expenses")({
  head: () => ({
    meta: [
      { title: "Expense Tracker — KrishiMitra" },
      {
        name: "description",
        content: "Track farm expenses by category with cost summaries and break-even insights.",
      },
    ],
  }),
  component: ExpensesPage,
});

const COLORS = [
  "var(--color-chart-1)",
  "var(--color-chart-2)",
  "var(--color-chart-3)",
  "var(--color-chart-4)",
  "var(--color-chart-5)",
];

function ExpensesPage() {
  const { activeFarmId, activeFarm, token, fetchScoped, postScoped } = useAppData();
  const [expenses, setExpenses] = useState([]);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [expenseErrors, setExpenseErrors] = useState({});
  const [formData, setFormData] = useState({
    label: "",
    category: "seeds",
    amountRs: "",
  });

  const fetchExpenses = useCallback(async () => {
    if (!token) return;
    try {
      const url = activeFarmId ? `/expenses?farm=${activeFarmId}` : `/expenses`;
      const res = await fetch(`${API_URL}${url}`, {
        headers: { Authorization: `Bearer ${token}` }
      });
      if (res.ok) {
        const data = await res.json();
        setExpenses(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error(err);
    }
  }, [activeFarmId, token]);

  useEffect(() => {
    fetchExpenses();
  }, [fetchExpenses]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    // Inline validation
    const newErrors = {};
    if (!formData.label.trim()) newErrors.label = "Description is required";
    if (!formData.amountRs) newErrors.amountRs = "Amount is required";
    else if (!Number.isFinite(Number(formData.amountRs)) || Number(formData.amountRs) <= 0) newErrors.amountRs = "Amount must be greater than 0";
    else if (Number(formData.amountRs) > 100000000) newErrors.amountRs = "Amount cannot exceed ₹10,00,00,000";
    if (!activeFarmId) {
      toast.error("Add a farm first, then record expenses for it.");
      return;
    }
    if (Object.keys(newErrors).length > 0) { setExpenseErrors(newErrors); return; }
    setExpenseErrors({});
    setIsSubmitting(true);
    try {
      
      const res = await fetch(`${API_URL}/expenses`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`
        },
        body: JSON.stringify({
          label: formData.label,
          category: formData.category,
          amountRs: Number(formData.amountRs),
          ...(activeFarmId ? { farm: activeFarmId } : {})
        })
      });
      
      if (res.ok) {
        const data = await res.json();
        if (data && (data._id || data.id)) {
          setFormData({ label: "", category: "seeds", amountRs: "" });
          fetchExpenses();
          toast.success("Expense recorded");
        } else {
          toast.error("Failed to add expense");
        }
      } else {
        const errData = await res.json().catch(() => ({}));
        toast.error(`Could not add expense. ${apiErrorMessage(errData)}`);
      }
    } catch (err) {
      toast.error("Error adding expense");
    } finally {
      setIsSubmitting(false);
    }
  };

  const [deletingId, setDeletingId] = useState(null);
  const handleDelete = async (x) => {
    const id = x._id || x.id;
    if (typeof window !== "undefined" && !window.confirm(`Delete "${x.label}" (₹${formatRs(x.amountRs || 0)})?`)) return;
    setDeletingId(id);
    try {
      const res = await fetch(`${API_URL}/expenses/${id}`, {
        method: "DELETE",
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok || res.status === 404) {
        setExpenses((prev) => prev.filter((e) => (e._id || e.id) !== id));
        toast.success("Expense deleted");
      } else {
        toast.error("Could not delete the expense. Please try again.");
      }
    } catch {
      toast.error("Could not reach the server. Please try again.");
    } finally {
      setDeletingId(null);
    }
  };

  const expenseByCategory = useMemo(() => {
    const cats = {};
    expenses.forEach((x) => {
      const cat = x.category || "other";
      cats[cat] = (cats[cat] || 0) + (x.amountRs || x.amount || 0);
    });
    return Object.entries(cats).map(([name, value]) => ({
      name: name.charAt(0).toUpperCase() + name.slice(1),
      value,
    }));
  }, [expenses]);

  const total = expenseByCategory.reduce((s, c) => s + c.value, 0);
  const topCategory = [...expenseByCategory].sort((a, b) => b.value - a.value)[0];

  return (
    <div>
      <PageHeader
        title="Expense Tracker"
        subtitle={`${currentSeason().label} · ${activeFarmId ? (activeFarm?.name || "This farm") : "All Farms"} · ₹${formatRs(total)} spent so far`}
      />

      {/* Insight cards */}
      <section className="mb-5 grid gap-4 sm:grid-cols-3">
        <div className="glass hover-lift rounded-2xl p-5">
          <div className="flex items-center gap-2 text-[11px] uppercase tracking-widest text-muted-foreground">
            <Wallet className="h-3.5 w-3.5 text-primary" /> Season spend
          </div>
          <div className="mt-2 font-display text-2xl font-bold">
            ₹{formatRs(total)}
          </div>
          <div className="mt-1 text-[11px] text-muted-foreground">
            {expenses.length === 0
              ? "No expenses recorded yet"
              : `${expenses.length} ${expenses.length === 1 ? "entry" : "entries"} · most on ${topCategory?.name ?? "—"}`}
          </div>
        </div>
        <div className="glass hover-lift flex flex-col justify-center rounded-2xl p-5 lg:col-span-2">
          <form onSubmit={handleSubmit}>
            <div className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-muted-foreground">
              Quick add expense
            </div>
            <div className="grid gap-3 sm:grid-cols-[minmax(0,1fr)_140px_120px_auto]">
              <div>
                <input
                  value={formData.label}
                  onChange={(e) => { setFormData({ ...formData, label: e.target.value }); if (expenseErrors.label) setExpenseErrors(p => ({...p, label: ""})); }}
                  placeholder="What did you spend on?"
                  className={`w-full rounded-lg border bg-secondary/40 px-3 py-2 text-xs outline-none focus:border-primary/50 ${expenseErrors.label ? "border-destructive" : "border-input"}`}
                />
                {expenseErrors.label && <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive leading-tight"><AlertCircle className="h-3 w-3 shrink-0" /><span>{expenseErrors.label}</span></p>}
              </div>
              <select
                value={formData.category}
                onChange={(e) => setFormData({ ...formData, category: e.target.value })}
                className="w-full rounded-lg border border-input bg-secondary/40 px-3 py-2 text-xs outline-none focus:border-primary/50"
              >
                <option value="seeds">Seeds</option>
                <option value="fertilizer">Fertilizer</option>
                <option value="pesticide">Pesticide</option>
                <option value="labor">Labor</option>
                <option value="irrigation">Irrigation</option>
                <option value="equipment">Equipment</option>
                <option value="transport">Transport</option>
                <option value="other">Other</option>
              </select>
              <div>
                <input
                  type="number"
                  min="1"
                  step="any"
                  value={formData.amountRs}
                  onChange={(e) => { setFormData({ ...formData, amountRs: e.target.value }); if (expenseErrors.amountRs) setExpenseErrors(p => ({...p, amountRs: ""})); }}
                  placeholder="₹ Amount"
                  className={`w-full rounded-lg border bg-secondary/40 px-3 py-2 text-xs outline-none focus:border-primary/50 ${expenseErrors.amountRs ? "border-destructive" : "border-input"}`}
                />
                {expenseErrors.amountRs && <p className="mt-1 flex items-center gap-1 text-[11px] text-destructive leading-tight"><AlertCircle className="h-3 w-3 shrink-0" /><span>{expenseErrors.amountRs}</span></p>}
              </div>
              <button
                disabled={isSubmitting}
                type="submit"
                className="flex items-center justify-center gap-1 rounded-lg bg-primary px-4 py-2 text-xs font-semibold text-primary-foreground transition-transform hover:scale-[1.03] w-full sm:w-auto cursor-pointer"
              >
                <Plus className="h-4 w-4" /> {isSubmitting ? "Adding..." : "Add"}
              </button>
            </div>
          </form>
        </div>
      </section>

      <div className="grid gap-5 lg:grid-cols-3">
        {/* Category breakdown */}
        <section className="glass rounded-2xl p-5">
          <h2 className="font-display text-sm font-semibold">Category breakdown</h2>
          {expenseByCategory.length === 0 ? (
            <div className="flex h-48 items-center justify-center text-xs text-muted-foreground">No data yet</div>
          ) : (
            <div className="mx-auto h-48 w-full">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={expenseByCategory}
                    dataKey="value"
                    nameKey="name"
                    innerRadius={52}
                    outerRadius={75}
                    paddingAngle={3}
                    strokeWidth={0}
                  >
                    {expenseByCategory.map((_, i) => (
                      <Cell key={i} fill={COLORS[i % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip
                    formatter={(v) => `₹${formatRs(v)}`}
                    contentStyle={{
                      background: "var(--color-popover)",
                      border: "1px solid var(--color-border)",
                      borderRadius: 12,
                      fontSize: 12,
                      color: "var(--color-popover-foreground)",
                    }}
                    itemStyle={{ color: "var(--color-popover-foreground)" }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          )}
          <div className="space-y-2">
            {expenseByCategory.map((c, i) => (
              <div key={c.name} className="flex items-center gap-2.5 text-xs">
                <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: COLORS[i % COLORS.length] }} />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{c.name}</span>
                <span className="font-semibold">₹{formatRs(c.value)}</span>
                <span className="w-10 text-right text-[10px] text-muted-foreground">
                  {total > 0 ? Math.round((c.value / total) * 100) : 0}%
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* Expense log + quick add */}
        <section className="glass rounded-2xl p-5 lg:col-span-2">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="font-display text-sm font-semibold">Recent expenses</h2>
            <span className="text-[11px] text-muted-foreground">{expenses.length} {expenses.length === 1 ? "record" : "records"}</span>
          </div>
          <div className="space-y-2">
            {expenses.length === 0 ? (
              <div className="grid place-items-center rounded-xl border border-dashed border-border py-8 text-xs text-muted-foreground">
                No expenses recorded yet. Use Quick add expense to record one.
              </div>
            ) : (
              expenses.map((x) => {
                const d = new Date(x.date || x.createdAt || Date.now());
                return (
                  <div
                    key={x._id || x.id}
                    className="ring-glow grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-xl border border-border bg-secondary/30 px-4 py-3 sm:flex"
                  >
                    <div className="flex min-w-0 items-center gap-3 sm:flex-1">
                      <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-secondary text-center text-[10px] font-bold text-muted-foreground">
                        {d.getDate()}<br />{d.toLocaleString("default", { month: "short" })}
                      </span>
                      <div className="min-w-0">
                        <div className="truncate text-xs font-medium">{x.label}</div>
                        <div className="text-[10px] text-muted-foreground">
                          {d.toLocaleDateString()} · {x.category}
                        </div>
                      </div>
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5 text-right">
                      <span className="font-display text-sm font-bold">
                        ₹{formatRs(x.amountRs || x.amount || 0)}
                      </span>
                      <button
                        type="button"
                        onClick={() => handleDelete(x)}
                        disabled={deletingId === (x._id || x.id)}
                        aria-label={`Delete expense ${x.label}`}
                        title="Delete expense"
                        className="grid h-8 w-8 place-items-center rounded-lg text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:opacity-50"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                );
              })
            )}
          </div>


        </section>
      </div>
    </div>
  );
}
