import Link from "next/link";
import { AiExplanation } from "../../components/ai-explanation";
import { MetricChart, type ChartPoint } from "../../components/metric-chart";
import {
  metricPrimaryPeriodType,
  metricSourceCurrency,
  metricSourceLinks,
} from "../../../lib/metric-provenance";
import { requireWorkspace } from "../../../lib/require-workspace";
import { formatDate, formatMetric, label } from "../../../lib/workspace";

const TABS = [
  "profitability",
  "liquidity",
  "leverage",
  "efficiency",
  "working capital",
  "cash flow",
] as const;
const SERIES: Record<string, { names: string[]; unit: string }> = {
  profitability: {
    names: ["gross_margin", "operating_margin", "net_margin"],
    unit: "%",
  },
  liquidity: { names: ["current_ratio", "quick_ratio"], unit: "×" },
  leverage: { names: ["debt_to_equity", "interest_coverage"], unit: "×" },
  efficiency: {
    names: ["asset_turnover", "receivables_turnover", "inventory_turnover"],
    unit: "×",
  },
  "working capital": {
    names: ["dso", "dio", "dpo", "cash_conversion_cycle"],
    unit: "days",
  },
  "cash flow": {
    names: ["operating_cash_flow", "net_income", "free_cash_flow"],
    unit: "amount",
  },
};
const COLORS = ["#126045", "#d07a35", "#356ba0", "#8a5aa3"];

export default async function AnalysisPage({
  searchParams,
}: {
  searchParams: Promise<{ company?: string; tab?: string }>;
}) {
  const { supabase, user } = await requireWorkspace();
  const query = await searchParams;
  const tab = TABS.find((item) => item === query.tab) || "profitability";
  const companies = await supabase
    .from("companies")
    .select("id,name")
    .eq("user_id", user.id)
    .order("name");
  const selected =
    companies.data?.find((item) => item.id === query.company) ||
    companies.data?.[0];
  const [metrics, statements] = await Promise.all([
    supabase
      .from("financial_metrics")
      .select(
        "id,company_id,statement_id,period_end,metric_name,metric_value,formula_version,metadata",
      )
      .eq("user_id", user.id)
      .eq("company_id", selected?.id || "00000000-0000-0000-0000-000000000000")
      .eq("is_stale", false)
      .order("period_end", { ascending: true })
      .limit(1000),
    supabase
      .from("financial_statements")
      .select("id,document_id,currency,period_type")
      .eq("user_id", user.id)
      .eq("company_id", selected?.id || "00000000-0000-0000-0000-000000000000")
      .limit(1000),
  ]);
  const selectedNames = SERIES[tab].names;
  const visible = (metrics.data || []).filter((item) =>
    selectedNames.includes(item.metric_name),
  );
  const statementById = new Map(
    (statements.data || []).map((item) => [item.id, item]),
  );
  const chartPeriodType = visible.some(
    (item) =>
      metricPrimaryPeriodType(
        item.statement_id,
        item.metadata,
        statementById,
      ) === "annual",
  )
    ? "annual"
    : metricPrimaryPeriodType(
        visible[0]?.statement_id || null,
        visible[0]?.metadata,
        statementById,
      );
  const chartCurrency = visible
    .map((item) => metricSourceCurrency(item.metadata, statementById))
    .find(Boolean);
  const points = new Map<string, ChartPoint>();
  const sourceLinks: Record<string, Record<string, string>> = {};
  const keys = new Set<string>();
  let duplicate = false;
  for (const item of visible) {
    const sources = metricSourceLinks(item.metadata, statementById);
    if (
      !sources.length ||
      metricSourceCurrency(item.metadata, statementById) !== chartCurrency ||
      metricPrimaryPeriodType(
        item.statement_id,
        item.metadata,
        statementById,
      ) !== chartPeriodType
    )
      continue;
    const point = points.get(item.period_end) || { period: item.period_end };
    const key = `${item.period_end}:${item.metric_name}`;
    if (keys.has(key)) {
      point[item.metric_name] = null;
      delete sourceLinks[item.period_end]?.[item.metric_name];
      duplicate = true;
    } else {
      point[item.metric_name] = item.metric_value;
      sourceLinks[item.period_end] ||= {};
      sourceLinks[item.period_end][item.metric_name] = sources[0].href;
      keys.add(key);
    }
    points.set(item.period_end, point);
  }
  const series = selectedNames
    .filter((name) =>
      [...points.values()].some((point) => typeof point[name] === "number"),
    )
    .map((name, index) => ({
      key: name,
      label: label(name),
      color: COLORS[index % COLORS.length],
    }));
  const loadError = companies.error || metrics.error || statements.error;
  return (
    <main className="workspace__main">
      <p className="eyebrow">Financial analysis</p>
      <h1>Analysis</h1>
      <p className="description">
        Charts use stored, current metrics for one company at a time. Values
        remain linked to their calculation and statement where that link is
        stored.
      </p>
      {loadError && (
        <p role="alert" className="form-message form-message--error">
          Analysis data could not be loaded.
        </p>
      )}
      {!selected ? (
        <section className="workspace-card">
          <p>No companies or calculated metrics are available yet.</p>
        </section>
      ) : (
        <>
          <form className="analysis-filters" method="get">
            <label htmlFor="analysis-company">Company</label>
            <select
              id="analysis-company"
              name="company"
              defaultValue={selected.id}
            >
              {companies.data?.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </select>
            <label htmlFor="analysis-tab">Area</label>
            <select id="analysis-tab" name="tab" defaultValue={tab}>
              {TABS.map((item) => (
                <option key={item} value={item}>
                  {label(item)}
                </option>
              ))}
            </select>
            <button className="button button--secondary" type="submit">
              Show
            </button>
          </form>
          <nav className="analysis-tabs" aria-label="Analysis areas">
            {TABS.map((item) => (
              <Link
                aria-current={item === tab ? "page" : undefined}
                key={item}
                href={`/dashboard/analysis?company=${selected.id}&tab=${encodeURIComponent(item)}`}
              >
                {label(item)}
              </Link>
            ))}
          </nav>
          {duplicate && (
            <p role="alert">
              Several current records share the same metric and period. Those
              chart points are omitted until a statement version is chosen.
            </p>
          )}
          <section className="workspace-card">
            <h2>{label(tab)} trends</h2>
            <MetricChart
              title={`${selected.name}: ${label(tab)}`}
              data={[...points.values()].sort((a, b) =>
                a.period.localeCompare(b.period),
              )}
              series={series}
              sourceLinks={sourceLinks}
              unit={
                SERIES[tab].unit === "amount"
                  ? chartCurrency || "units"
                  : SERIES[tab].unit
              }
            />
          </section>
          <AiExplanation
            companyId={selected.id}
            focus={tab}
            hasMetrics={visible.length > 0}
          />
          <section className="workspace-card">
            <h2>Calculated values</h2>
            {!visible.length ? (
              <p>
                No {label(tab)} metrics have been calculated for this company
                yet.
              </p>
            ) : (
              <div className="table-scroll">
                <table className="data-table">
                  <thead>
                    <tr>
                      <th scope="col">Metric</th>
                      <th scope="col">Period</th>
                      <th scope="col">Value</th>
                      <th scope="col">Formula</th>
                      <th scope="col">Source</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visible
                      .slice()
                      .reverse()
                      .map((item) => (
                        <tr key={item.id}>
                          <th scope="row">{label(item.metric_name)}</th>
                          <td>{formatDate(item.period_end)}</td>
                          <td>
                            {metricSourceLinks(item.metadata, statementById)
                              .length &&
                            metricSourceCurrency(item.metadata, statementById)
                              ? formatMetric(
                                  item.metric_name,
                                  item.metric_value,
                                  metricSourceCurrency(
                                    item.metadata,
                                    statementById,
                                  ),
                                )
                              : "Provenance unavailable"}
                          </td>
                          <td>{item.formula_version}</td>
                          <td>
                            {metricSourceLinks(item.metadata, statementById)
                              .length
                              ? metricSourceLinks(
                                  item.metadata,
                                  statementById,
                                ).map((source) => (
                                  <Link key={source.href} href={source.href}>
                                    {source.label}{" "}
                                  </Link>
                                ))
                              : "Not linked"}
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        </>
      )}
    </main>
  );
}
