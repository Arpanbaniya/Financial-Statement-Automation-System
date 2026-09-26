"use client";

import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { formatNumber } from "../../lib/workspace";

export type ChartPoint = { period: string } & Record<
  string,
  string | number | null
>;
export type ChartSeries = { key: string; label: string; color: string };

export function MetricChart({
  title,
  data,
  series,
  unit,
  sourceLinks = {},
}: {
  title: string;
  data: ChartPoint[];
  series: ChartSeries[];
  unit: string;
  sourceLinks?: Record<string, Record<string, string>>;
}) {
  if (!data.length || !series.length)
    return <p>No comparable values to chart yet.</p>;
  return (
    <figure className="metric-chart">
      <figcaption>{title}</figcaption>
      <div
        className="metric-chart__canvas"
        role="img"
        aria-label={`${title}; values are in the table below`}
      >
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data}
            margin={{ top: 12, right: 18, bottom: 8, left: 8 }}
          >
            <CartesianGrid stroke="#e4eee8" />
            <XAxis dataKey="period" />
            <YAxis
              domain={[
                (min: number) => Math.min(0, min),
                (max: number) => Math.max(0, max),
              ]}
              width={66}
            />
            <Tooltip
              formatter={(value) => `${formatNumber(Number(value), 2)} ${unit}`}
            />
            <Legend />
            {series.map((item) => (
              <Line
                key={item.key}
                type="linear"
                dataKey={item.key}
                name={item.label}
                stroke={item.color}
                strokeWidth={2}
                dot
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <div className="table-scroll">
        <table className="data-table">
          <caption>{title} data</caption>
          <thead>
            <tr>
              <th scope="col">Period</th>
              {series.map((item) => (
                <th scope="col" key={item.key}>
                  {item.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((point) => (
              <tr key={point.period}>
                <th scope="row">{point.period}</th>
                {series.map((item) => (
                  <td key={item.key}>
                    {typeof point[item.key] === "number" ? (
                      sourceLinks[point.period]?.[item.key] ? (
                        <a href={sourceLinks[point.period][item.key]}>
                          {formatNumber(point[item.key] as number, 2)} {unit}
                        </a>
                      ) : (
                        `${formatNumber(point[item.key] as number, 2)} ${unit}`
                      )
                    ) : (
                      "Unavailable"
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </figure>
  );
}
