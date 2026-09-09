import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, getHistory, getSummary } from "../api/client";
import type { HistoryRecord, SummaryResponse, Verdict } from "../types/api";
import { DOC_TYPE_LABEL, VERDICT_COPY } from "../lib/copy";
import { VerdictPill, BindingPill } from "./Pills";
import { ErrorPanel } from "./ErrorPanel";
import { Disclaimer } from "./Disclaimer";
import "../styles/dashboard.css";

interface DashboardViewProps {
  reasons: Record<string, string> | null;
}

interface DayBucket {
  day: string;
  total: number;
  segments: { verdict: string; count: number }[];
}

function buildTrend(trend: SummaryResponse["trend"]): DayBucket[] {
  const map = new Map<string, DayBucket>();
  for (const point of trend) {
    let bucket = map.get(point.day);
    if (!bucket) {
      bucket = { day: point.day, total: 0, segments: [] };
      map.set(point.day, bucket);
    }
    bucket.total += point.count;
    bucket.segments.push({ verdict: point.verdict, count: point.count });
  }
  return Array.from(map.values()).sort((a, b) => a.day.localeCompare(b.day));
}

export function DashboardView({ reasons }: DashboardViewProps) {
  const [history, setHistory] = useState<HistoryRecord[] | null>(null);
  const [summary, setSummary] = useState<SummaryResponse | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(false);
  const [query, setQuery] = useState("");
  const [docType, setDocType] = useState("");
  const [verdictFilter, setVerdictFilter] = useState("");
  const requestId = useRef(0);

  const load = useCallback(async () => {
    const currentRequest = ++requestId.current;
    setLoading(true);
    setError(null);
    try {
      const [historyResponse, summaryResponse] = await Promise.all([getHistory(50), getSummary()]);
      if (currentRequest !== requestId.current) return;
      setHistory(historyResponse.records);
      setSummary(summaryResponse);
    } catch (err) {
      if (currentRequest !== requestId.current) return;
      setError(err instanceof ApiError ? err : new ApiError(0, "Could not load dashboard data."));
    } finally {
      if (currentRequest === requestId.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    return () => { requestId.current += 1; };
  }, [load]);

  const translate = (code: string) => reasons?.[code] ?? code;
  const totalChecks = summary ? Object.values(summary.by_verdict).reduce((a, b) => a + b, 0) : 0;
  const trendDays = summary ? buildTrend(summary.trend) : [];
  const maxDayTotal = Math.max(1, ...trendDays.map((d) => d.total));
  const search = query.trim().toLowerCase();
  const filteredHistory = (history ?? []).filter(record => {
    if (docType && record.doc_type !== docType) return false;
    if (verdictFilter && record.verdict !== verdictFilter) return false;
    return !search || [record.id, DOC_TYPE_LABEL[record.doc_type] ?? record.doc_type,
      VERDICT_COPY[record.verdict].title, ...record.reason_codes.map(translate), ...record.reason_codes,
    ].join(" ").toLowerCase().includes(search);
  });
  const docTypes = [...new Set((history ?? []).map(record => record.doc_type))];
  const hasFilters = Boolean(query || docType || verdictFilter);

  return (
    <div className="dashboard-view">
      <div className="dashboard-view__header">
        <div>
          <h2>Dashboard</h2>
          <p className="dashboard-view__subtitle">
            Review past findings, trace the evidence, and see which checks need a closer look.
          </p>
        </div>
        <button type="button" className="button button--secondary" onClick={load} disabled={loading}>
          {loading ? "Refreshing…" : "Refresh"}
        </button>
      </div>

      {error && <ErrorPanel error={error} />}
      {loading && !summary && <p className="dashboard-loading" role="status">Loading your verification history…</p>}

      {summary && (
        <>
          <div className="dashboard-grid">
            <div className="dashboard-card" data-anim="dashboard-card">
              <h3 className="dashboard-card__title">Total checks</h3>
              <div className="dashboard-stat">
                <span className="dashboard-stat__value">{totalChecks}</span>
                <span className="dashboard-stat__label">records</span>
              </div>
            </div>

            <div className="dashboard-card" data-anim="dashboard-card">
              <h3 className="dashboard-card__title">By verdict</h3>
              <ul className="breakdown-list">
                {Object.entries(summary.by_verdict).map(([verdict, count]) => {
                  const tone = VERDICT_COPY[verdict as Verdict]?.tone ?? "unverifiable";
                  return (
                    <li key={verdict} className="breakdown-row">
                      <span className="breakdown-row__label">{verdict.replace(/_/g, " ")}</span>
                      <span
                        className="breakdown-row__bar"
                        style={{
                          width: `${barWidth(count, summary.by_verdict)}%`,
                          background: `var(--verdict-${tone}-accent)`,
                        }}
                      />
                      <span className="breakdown-row__value">{count}</span>
                    </li>
                  );
                })}
              </ul>
            </div>

            <div className="dashboard-card" data-anim="dashboard-card">
              <h3 className="dashboard-card__title">By document type</h3>
              <ul className="breakdown-list">
                {Object.entries(summary.by_doc_type).map(([docType, count]) => (
                  <li key={docType} className="breakdown-row">
                    <span className="breakdown-row__label">{DOC_TYPE_LABEL[docType] ?? docType}</span>
                    <span
                      className="breakdown-row__bar"
                      style={{
                        width: `${barWidth(count, summary.by_doc_type)}%`,
                        background: "var(--tier-cryptographic-accent)",
                      }}
                    />
                    <span className="breakdown-row__value">{count}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="dashboard-card dashboard-card--wide" data-anim="dashboard-card">
              <h3 className="dashboard-card__title">Top reasons observed</h3>
              {summary.top_reasons.length === 0 ? (
                <p className="reason-empty">No checks recorded yet.</p>
              ) : (
                <ul className="top-reasons-list">
                  {summary.top_reasons.map((item) => (
                    <li key={item.code} className="top-reasons-item">
                      <span className="top-reasons-item__message">{translate(item.code)}</span>
                      <span className="top-reasons-item__count">{item.count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            <div className="dashboard-card dashboard-card--wide" data-anim="dashboard-card">
              <h3 className="dashboard-card__title">Trend by day · UTC</h3>
              {trendDays.length === 0 ? (
                <p className="reason-empty">No checks recorded yet.</p>
              ) : (
                <>
                  <div className="dashboard-trend">
                    {trendDays.map((bucket) => (
                      <div
                        key={bucket.day}
                        className="dashboard-trend__bar"
                        data-anim="trend-bar"
                        style={{ height: `${Math.max(6, (bucket.total / maxDayTotal) * 100)}%` }}
                        title={`${bucket.day}: ${bucket.total} check${bucket.total === 1 ? "" : "s"}`}
                      >
                        {bucket.segments.map((segment, index) => {
                          const tone = VERDICT_COPY[segment.verdict as Verdict]?.tone ?? "unverifiable";
                          return (
                            <span
                              key={`${segment.verdict}-${index}`}
                              className="dashboard-trend__segment"
                              style={{
                                flexGrow: segment.count,
                                background: `var(--verdict-${tone}-accent)`,
                              }}
                            />
                          );
                        })}
                      </div>
                    ))}
                  </div>
                  <div className="dashboard-trend__axis">
                    {trendDays.map((bucket) => (
                      <span key={bucket.day}>{formatDay(bucket.day)}</span>
                    ))}
                  </div>
                </>
              )}
            </div>
          </div>

          <section className="dashboard-history">
            <h3>Recent checks</h3>
            {history && history.length > 0 && (
              <>
                <div className="dashboard-filters">
                  <label>Search checks
                    <input type="search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Record ID, reason, or finding…" />
                  </label>
                  <label>Document type
                    <select value={docType} onChange={event => setDocType(event.target.value)}>
                      <option value="">All types</option>
                      {docTypes.map(type => <option key={type} value={type}>{DOC_TYPE_LABEL[type] ?? type}</option>)}
                    </select>
                  </label>
                  <label>Finding
                    <select value={verdictFilter} onChange={event => setVerdictFilter(event.target.value)}>
                      <option value="">All findings</option>
                      {Object.entries(VERDICT_COPY).map(([value, copy]) => <option key={value} value={value}>{copy.title}</option>)}
                    </select>
                  </label>
                </div>
                <div className="dashboard-filter-summary">
                  <p role="status">{filteredHistory.length} of the latest {history.length} checks</p>
                  {hasFilters && <button type="button" className="button button--secondary" onClick={() => { setQuery(""); setDocType(""); setVerdictFilter(""); }}>Clear filters</button>}
                </div>
              </>
            )}
            {!history || history.length === 0 ? (
              <p className="reason-empty">{loading ? "Loading…" : "No checks recorded yet."}</p>
            ) : filteredHistory.length === 0 ? (
              <p className="reason-empty">No checks match these filters. Try another search or clear the filters.</p>
            ) : (
              <div className="dashboard-table-wrap">
                <table className="dashboard-table">
                  <thead>
                    <tr>
                      <th>When</th>
                      <th>Type</th>
                      <th>Verdict</th>
                      <th>Identity binding</th>
                      <th>Reasons</th>
                    </tr>
                  </thead>
                  <tbody>
                    {filteredHistory.map((record) => (
                      <tr key={record.id}>
                        <td>{formatTimestamp(record.created_at)}</td>
                        <td>{DOC_TYPE_LABEL[record.doc_type] ?? record.doc_type}</td>
                        <td>
                          <VerdictPill verdict={record.verdict} />
                        </td>
                        <td>
                          <BindingPill binding={record.binding} />
                        </td>
                        <td className="dashboard-table__reasons">
                          {record.reason_codes.length === 0 ? "—" : record.reason_codes.map(translate).join("; ")}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          <Disclaimer text={summary.disclaimer} />
        </>
      )}
    </div>
  );
}

function barWidth(count: number, all: Record<string, number>): number {
  const max = Math.max(...Object.values(all), 1);
  return Math.max(4, Math.round((count / max) * 100));
}

function formatTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString();
}

function formatDay(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(5);
  return date.toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
}
