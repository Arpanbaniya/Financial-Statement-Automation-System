import Link from "next/link";
import { notFound } from "next/navigation";
import { MetricChart, type ChartPoint } from "../../../components/metric-chart";
import {
  metricPrimaryPeriodType,
  metricSourceCurrency,
  metricSourceLinks,
} from "../../../../lib/metric-provenance";
import { requireWorkspace } from "../../../../lib/require-workspace";
import { formatDate, formatMetric, label } from "../../../../lib/workspace";

export default async function CompanyPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const { supabase, user } = await requireWorkspace();
  const { data: company, error: companyError } = await supabase
    .from("companies")
    .select("id,name,ticker,country,industry")
    .eq("id", id)
    .eq("user_id", user.id)
    .maybeSingle();
  if (!company && !companyError) notFound();
  const [statements, metrics, documents] = await Promise.all([
    supabase
      .from("financial_statements")
      .select(
        "id,document_id,statement_type,period_type,period_end,currency,status",
      )
      .eq("user_id", user.id)
      .eq("company_id", id)
      .order("period_end", { ascending: false })
      .limit(100),
    supabase
      .from("financial_metrics")
      .select(
        "id,metric_name,metric_value,period_end,statement_id,formula_version,is_stale,metadata",
      )
      .eq("user_id", user.id)
      .eq("company_id", id)
      .eq("is_stale", false)
      .order("period_end", { ascending: true })
      .limit(500),
    supabase
      .from("documents")
      .select("id,original_filename,status")
      .eq("user_id", user.id)
      .eq("company_id", id)
      .limit(100),
  ]);
  const loadError =
    companyError || statements.error || metrics.error || documents.error;
  const statementById = new Map(
    (statements.data || []).map((item) => [item.id, item]),
  );
  const statementIds = (statements.data || []).map((item) => item.id);
  const sourceLines = statementIds.length
    ? await supabase
        .from("financial_line_items")
        .select(
          "id,statement_id,canonical_name,normalized_value,original_value,source_page,source_cell",
        )
        .eq("user_id", user.id)
        .eq("review_status", "accepted")
        .in("statement_id", statementIds)
        .in("canonical_name", [
          "revenue",
          "net_income",
          "total_assets",
          "total_liabilities",
          "shareholders_equity",
        ])
        .limit(1000)
    : null;
  function sourceChart(kind: string, names: string[]) {
    const candidates = (statements.data || []).filter(
      (item) => item.statement_type === kind && item.status === "accepted",
    );
    const periodType = candidates.some((item) => item.period_type === "annual")
      ? "annual"
      : candidates[0]?.period_type;
    const sourceCurrency = candidates.find((item) => item.currency)?.currency;
    const data = new Map<string, ChartPoint>();
    const sourceLinks: Record<string, Record<string, string>> = {};
    const seen = new Set<string>();
    let duplicates = false;
    for (const line of sourceLines?.data || []) {
      const statement = statementById.get(line.statement_id);
      if (
        !statement ||
        statement.status !== "accepted" ||
        statement.statement_type !== kind ||
        statement.period_type !== periodType ||
        statement.currency !== sourceCurrency ||
        !line.canonical_name ||
        !names.includes(line.canonical_name) ||
        line.normalized_value === null ||
        line.original_value === null ||
        (!line.source_page && !line.source_cell)
      )
        continue;
      const point = data.get(statement.period_end) || {
        period: statement.period_end,
      };
      const key = `${statement.period_end}:${line.canonical_name}`;
      if (seen.has(key)) {
        point[line.canonical_name] = null;
        delete sourceLinks[statement.period_end]?.[line.canonical_name];
        duplicates = true;
      } else {
        point[line.canonical_name] = line.normalized_value;
        sourceLinks[statement.period_end] ||= {};
        sourceLinks[statement.period_end][line.canonical_name] =
          `/dashboard/documents/${statement.document_id}#line-${line.id}`;
        seen.add(key);
      }
      data.set(statement.period_end, point);
    }
    return {
      data: [...data.values()].sort((a, b) => a.period.localeCompare(b.period)),
      series: names
        .filter((name) =>
          [...data.values()].some((point) => typeof point[name] === "number"),
        )
        .map((name, index) => ({
          key: name,
          label: label(name),
          color: ["#126045", "#d07a35", "#356ba0"][index],
        })),
      sourceLinks,
      duplicates,
      currency: sourceCurrency,
    };
  }
  const incomeChart = sourceChart("income_statement", [
    "revenue",
    "net_income",
  ]);
  const balanceChart = sourceChart("balance_sheet", [
    "total_assets",
    "total_liabilities",
    "shareholders_equity",
  ]);
  const chartNames = [
    "revenue",
    "net_income",
    "operating_cash_flow",
    "free_cash_flow",
  ];
  const chartCandidates = (metrics.data || []).filter((item) =>
    chartNames.includes(item.metric_name),
  );
  const chartPeriodType = chartCandidates.some(
    (item) =>
      metricPrimaryPeriodType(
        item.statement_id,
        item.metadata,
        statementById,
      ) === "annual",
  )
    ? "annual"
    : metricPrimaryPeriodType(
        chartCandidates[0]?.statement_id || null,
        chartCandidates[0]?.metadata,
        statementById,
      );
  const chartCurrency = chartCandidates
    .map((item) => metricSourceCurrency(item.metadata, statementById))
    .find(Boolean);
  const points = new Map<string, ChartPoint>();
  const metricLinks: Record<string, Record<string, string>> = {};
  const chartKeys = new Set<string>();
  let duplicate = false;
  for (const metric of metrics.data || []) {
    const sources = metricSourceLinks(metric.metadata, statementById);
    if (
      !chartNames.includes(metric.metric_name) ||
      metric.metric_value === null ||
      !sources.length ||
      metricSourceCurrency(metric.metadata, statementById) !== chartCurrency ||
      metricPrimaryPeriodType(
        metric.statement_id,
        metric.metadata,
        statementById,
      ) !== chartPeriodType
    )
      continue;
    const point = points.get(metric.period_end) || {
      period: metric.period_end,
    };
    const key = `${metric.period_end}:${metric.metric_name}`;
    if (chartKeys.has(key)) {
      point[metric.metric_name] = null;
      delete metricLinks[metric.period_end]?.[metric.metric_name];
      duplicate = true;
    } else {
      point[metric.metric_name] = metric.metric_value;
      metricLinks[metric.period_end] ||= {};
      metricLinks[metric.period_end][metric.metric_name] = sources[0].href;
      chartKeys.add(key);
    }
    points.set(metric.period_end, point);
  }
  const chartSeries = chartNames
    .filter((name) =>
      [...points.values()].some((point) => typeof point[name] === "number"),
    )
    .map((name, index) => ({
      key: name,
      label: label(name),
      color: ["#126045", "#d07a35", "#356ba0", "#8a5aa3"][index],
    }));
  return (
    <main className="workspace__main">
      <p className="eyebrow">Company overview</p>
      <h1>{company?.name || "Company"}</h1>
      <p className="description">
        {[company?.ticker, company?.country, company?.industry]
          .filter(Boolean)
          .join(" · ") || "No profile details yet"}
      </p>
      {loadError && (
        <p role="alert" className="form-message form-message--error">
          Company data could not be loaded.
        </p>
      )}
      {sourceLines?.error && (
        <p role="alert" className="form-message form-message--error">
          Statement trend data could not be loaded.
        </p>
      )}
      {(incomeChart.duplicates || balanceChart.duplicates) && (
        <p role="alert">
          Duplicate source periods are omitted from statement charts until a
          version is chosen.
        </p>
      )}
      <section className="workspace-card">
        <h2>Income trends</h2>
        <MetricChart
          title="Revenue and net income"
          data={incomeChart.data}
          series={incomeChart.series}
          sourceLinks={incomeChart.sourceLinks}
          unit={incomeChart.currency || "units"}
        />
      </section>
      <section className="workspace-card">
        <h2>Balance sheet trends</h2>
        <MetricChart
          title="Assets, liabilities, and equity"
          data={balanceChart.data}
          series={balanceChart.series}
          sourceLinks={balanceChart.sourceLinks}
          unit={balanceChart.currency || "units"}
        />
      </section>
      <section className="workspace-card">
        <h2>Trends</h2>
        {duplicate && (
          <p role="alert">
            Duplicate metric periods are omitted from the chart until a
            statement version is chosen.
          </p>
        )}
        <MetricChart
          title="Reported amounts over time"
          data={[...points.values()].sort((a, b) =>
            a.period.localeCompare(b.period),
          )}
          series={chartSeries}
          unit={chartCurrency || "units"}
          sourceLinks={metricLinks}
        />
      </section>
      <section className="workspace-card">
        <h2>Financial statements</h2>
        {!statements.data?.length ? (
          <p>
            No accepted or draft statements are stored for this company yet.
          </p>
        ) : (
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Type</th>
                  <th scope="col">Period end</th>
                  <th scope="col">Currency</th>
                  <th scope="col">Status</th>
                  <th scope="col">Source</th>
                </tr>
              </thead>
              <tbody>
                {statements.data.map((item) => (
                  <tr id={`statement-${item.id}`} key={item.id}>
                    <th scope="row">{label(item.statement_type)}</th>
                    <td>{formatDate(item.period_end)}</td>
                    <td>{item.currency || "Unresolved"}</td>
                    <td>{label(item.status)}</td>
                    <td>
                      <Link
                        href={`/dashboard/documents/${item.document_id}#statement-${item.id}`}
                      >
                        View document
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="workspace-card">
        <h2>Calculated metrics</h2>
        {!metrics.data?.length ? (
          <p>No calculated metrics are stored yet.</p>
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
                {metrics.data
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
                        {metricSourceLinks(item.metadata, statementById).length
                          ? metricSourceLinks(item.metadata, statementById).map(
                              (source) => (
                                <Link key={source.href} href={source.href}>
                                  {source.label}{" "}
                                </Link>
                              ),
                            )
                          : "Not linked"}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      <section className="workspace-card">
        <h2>Documents</h2>
        {!documents.data?.length ? (
          <p>No documents assigned to this company.</p>
        ) : (
          <ul className="plain-list">
            {documents.data.map((item) => (
              <li key={item.id}>
                <Link href={`/dashboard/documents/${item.id}`}>
                  {item.original_filename}
                </Link>
                <span>{label(item.status)}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}
