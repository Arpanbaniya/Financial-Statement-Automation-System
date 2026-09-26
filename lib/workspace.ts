export function label(value: string): string {
  return value.replaceAll("_", " ");
}

export function formatNumber(value: number | null, digits = 1): string {
  if (value === null || !Number.isFinite(value)) return "Unavailable";
  return new Intl.NumberFormat("en", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

export function formatDate(value: string): string {
  const date = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  return Number.isNaN(date.getTime())
    ? value
    : new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeZone: "UTC",
      }).format(date);
}

export function metricUnit(
  name: string,
): "percent" | "days" | "times" | "amount" {
  if (["dso", "dio", "dpo", "cash_conversion_cycle"].includes(name))
    return "days";
  if (name.includes("margin") || name.endsWith("_growth")) return "percent";
  if (name.endsWith("_ratio") || name.endsWith("_turnover")) return "times";
  return "amount";
}

export function formatMetric(
  name: string,
  value: number | null,
  currency?: string | null,
): string {
  if (value === null) return "Unavailable";
  const unit = metricUnit(name);
  if (unit === "percent") return `${formatNumber(value)}%`;
  if (unit === "days") return `${formatNumber(value)} days`;
  if (unit === "times") return `${formatNumber(value, 2)}×`;
  return `${currency ? `${currency} ` : ""}${formatNumber(value, 2)}`;
}

export function metricCategory(name: string): string {
  if (name.includes("margin") || name.includes("return_on"))
    return "profitability";
  if (name.includes("debt") || name.includes("coverage")) return "leverage";
  if (
    [
      "dso",
      "dio",
      "dpo",
      "cash_conversion_cycle",
      "net_working_capital",
    ].includes(name)
  )
    return "working capital";
  if (
    name.includes("cash_flow") ||
    name.includes("cash_conversion") ||
    name.includes("capital_expenditure")
  )
    return "cash flow";
  if (name.includes("current_ratio") || name.includes("quick_ratio"))
    return "liquidity";
  return "efficiency";
}
