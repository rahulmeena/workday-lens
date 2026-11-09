"use client";

import { useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { DayStoryChart } from "./day-story-chart";
import { SetupPanel } from "./setup-panel";
import { ActivitySegment, fetchActivityDashboard, fetchSetupStatus } from "../lib/api";
import { DEFAULT_POLL_INTERVAL } from "../lib/config";

const LONG_DATE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  weekday: "long",
  month: "long",
  day: "numeric",
});

const SHORT_DATE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  year: "numeric",
});

const TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
});

function formatMinutes(minutes: number) {
  if (!minutes) {
    return "0m";
  }
  const hours = Math.floor(minutes / 60);
  const remaining = minutes % 60;
  if (!hours) {
    return `${remaining}m`;
  }
  if (!remaining) {
    return `${hours}h`;
  }
  return `${hours}h ${remaining}m`;
}

function formatDateLabel(value?: string | null) {
  if (!value) {
    return "Today";
  }
  const match = value.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  const date = match
    ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]))
    : new Date(value);
  return LONG_DATE_FORMATTER.format(date);
}

function formatDatePickerLabel(value: string) {
  const [year, month, day] = value.split("-").map(Number);
  const date = new Date(year, (month || 1) - 1, day || 1);
  return SHORT_DATE_FORMATTER.format(date);
}

function toDateInputValue(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function todayDateValue() {
  return toDateInputValue(new Date());
}

function shiftDayValue(day: string, offset: number) {
  const value = new Date(`${day}T12:00:00`);
  value.setDate(value.getDate() + offset);
  return toDateInputValue(value);
}

function formatTime(value: string) {
  return TIME_FORMATTER.format(new Date(value));
}

const activityClassMap: Record<string, string> = {
  deep_work: "activity-pill activity-pill--deep",
  planning: "activity-pill activity-pill--plan",
  research: "activity-pill activity-pill--research",
  review: "activity-pill activity-pill--review",
  communication: "activity-pill activity-pill--comms",
  admin: "activity-pill activity-pill--admin",
  break: "activity-pill activity-pill--break",
  other: "activity-pill activity-pill--other",
  offline: "activity-pill activity-pill--offline",
};

const focusClassMap: Record<string, string> = {
  focused: "state-pill state-pill--focused",
  steady: "state-pill state-pill--steady",
  switching: "state-pill state-pill--switching",
  blocked: "state-pill state-pill--blocked",
  idle: "state-pill state-pill--idle",
};

const EMPTY_SEGMENTS: ActivitySegment[] = [];

export function PersonalDashboard() {
  const [selectedDay, setSelectedDay] = useState(() => todayDateValue());
  const [showSettings, setShowSettings] = useState(false);
  const dateInputRef = useRef<HTMLInputElement | null>(null);
  const today = todayDateValue();
  const canMoveForward = selectedDay < today;

  function openDatePicker() {
    const input = dateInputRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    if (!input) {
      return;
    }
    try {
      if (typeof input.showPicker === "function") {
        input.showPicker();
        return;
      }
    } catch {
      // Fall back to focus/click for browsers without a usable showPicker implementation.
    }
    input.focus();
    input.click();
  }

  const setupQuery = useQuery({
    queryKey: ["setup-status"],
    queryFn: fetchSetupStatus,
  });

  const dashboardQuery = useQuery({
    queryKey: ["activity-dashboard", selectedDay],
    queryFn: () => fetchActivityDashboard(selectedDay),
    enabled: Boolean(setupQuery.data && !setupQuery.data.needs_setup),
    refetchInterval: selectedDay === today ? DEFAULT_POLL_INTERVAL : false,
  });

  const setup = setupQuery.data;
  const dashboard = dashboardQuery.data;
  const segments = dashboard?.segments ?? EMPTY_SEGMENTS;
  const topProject = dashboard?.project_breakdown[0]?.label ?? "No project detected yet";
  const chronologicalSegments = useMemo(
    () =>
      [...segments].sort(
        (left, right) => new Date(left.captured_from).getTime() - new Date(right.captured_from).getTime(),
      ),
    [segments],
  );
  const detailedTimelineSegments = useMemo(
    () => [...chronologicalSegments].reverse(),
    [chronologicalSegments],
  );

  const statCards = useMemo(
    () => [
      {
        label: "Tracked in view",
        value: formatMinutes(dashboard?.summary.total_tracked_minutes ?? 0),
        note: `${dashboard?.summary.captured_windows ?? 0} captured segments`,
      },
      {
        label: "Focused time",
        value: formatMinutes(dashboard?.summary.focused_minutes ?? 0),
        note: `${formatMinutes(dashboard?.summary.longest_focus_block_minutes ?? 0)} longest block`,
      },
      {
        label: "Context switches",
        value: String(dashboard?.summary.activity_switches ?? 0),
        note: `${dashboard?.summary.active_projects ?? 0} active workstreams`,
      },
      {
        label: "Pipeline",
        value: `${dashboard?.summary.pending_windows ?? 0} pending`,
        note: dashboard?.current_intent ? `Latest: ${dashboard.current_intent.activity_label}` : "Waiting for captured activity",
      },
    ],
    [dashboard],
  );

  async function refreshSetupAndDashboard() {
    const setupResult = await setupQuery.refetch();
    if (setupResult.data && !setupResult.data.needs_setup) {
      await dashboardQuery.refetch();
    }
  }

  if (setupQuery.isLoading) {
    return (
      <section className="panel-card">
        <p className="muted">Checking local setup for this machine.</p>
      </section>
    );
  }

  if (setupQuery.isError || !setup) {
    return (
      <section className="panel-card">
        <p className="error">The app could not read local setup status from the local API.</p>
      </section>
    );
  }

  if (setup.needs_setup) {
    return <SetupPanel setup={setup} onSaved={refreshSetupAndDashboard} mode="setup" />;
  }

  return (
    <div className="dashboard-page">
      {showSettings && (
        <SetupPanel
          setup={setup}
          onSaved={refreshSetupAndDashboard}
          mode="manage"
          onClose={() => setShowSettings(false)}
        />
      )}

      <section className="hero-card">
        <div className="hero-card__copy">
          <p className="eyebrow">Personal Activity Replay</p>
          <h2>See what your day turned into while you were heads-down.</h2>
          <p className="hero-card__body">
            Workday Lens helps you make sense of your day by showing what you were doing,
            what you were likely trying to complete, and how your time moved across the day.
          </p>
        </div>
        <div className="hero-card__meta">
          <div className="date-chip">{formatDateLabel(dashboard?.date)}</div>
          <div className="hero-card__project">
            <span className="hero-card__project-label">Dominant workstream</span>
            <strong>{topProject}</strong>
          </div>
          <div className="hero-card__controls">
            <div className="hero-card__daynav">
              <button
                type="button"
                className="button button--secondary hero-card__nav-button hero-card__nav-button--prev"
                onClick={() => setSelectedDay((current) => shiftDayValue(current, -1))}
              >
                Previous day
              </button>

              <label className="date-field">
                <span className="hero-card__project-label">Viewing day</span>
                <button
                  type="button"
                  className="date-field__trigger"
                  aria-haspopup="dialog"
                  aria-label={`Choose viewing day. Current selection is ${formatDatePickerLabel(selectedDay)}`}
                  onClick={openDatePicker}
                >
                  <span className="date-field__value">{formatDatePickerLabel(selectedDay)}</span>
                  <span className="date-field__icon" aria-hidden="true">
                    <svg viewBox="0 0 24 24" focusable="false">
                      <path
                        d="M7 2a1 1 0 0 1 1 1v1h8V3a1 1 0 1 1 2 0v1h1a2 2 0 0 1 2 2v12a3 3 0 0 1-3 3H6a3 3 0 0 1-3-3V6a2 2 0 0 1 2-2h1V3a1 1 0 0 1 1-1Zm12 8H5v8a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-8ZM6 6a1 1 0 0 0-1 1v1h14V7a1 1 0 0 0-1-1H6Z"
                        fill="currentColor"
                      />
                    </svg>
                  </span>
                </button>
                <input
                  ref={dateInputRef}
                  className="date-field__native"
                  type="date"
                  value={selectedDay}
                  max={today}
                  tabIndex={-1}
                  aria-hidden="true"
                  onChange={(event) => {
                    if (event.target.value) {
                      setSelectedDay(event.target.value);
                    }
                  }}
                />
              </label>

              <button
                type="button"
                className="button button--secondary hero-card__nav-button hero-card__nav-button--next"
                onClick={() => setSelectedDay((current) => shiftDayValue(current, 1))}
                disabled={!canMoveForward}
              >
                Next day
              </button>
            </div>

            <div className="hero-card__actions">
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setShowSettings((current) => !current)}
              >
                {showSettings ? "Hide settings" : "Local settings"}
              </button>
              <button
                type="button"
                className="button button--secondary"
                onClick={() => setSelectedDay(today)}
                disabled={selectedDay === today}
              >
                Today
              </button>
              <button type="button" className="button" onClick={() => dashboardQuery.refetch()} disabled={dashboardQuery.isFetching}>
                {dashboardQuery.isFetching ? "Refreshing..." : "Refresh snapshot"}
              </button>
            </div>
          </div>
          <p className="hero-card__hint">
            Activity is separated by local calendar day. Use the date picker to reopen earlier days as your archive grows.
          </p>
        </div>
      </section>

      {dashboardQuery.isLoading && (
        <section className="panel-card">
          <p className="muted">Reading activity and building the selected day view.</p>
        </section>
      )}

      {dashboardQuery.isError && (
        <section className="panel-card">
          <p className="error">The dashboard could not load activity from the local API.</p>
        </section>
      )}

      {dashboard && (
        <>
          <DayStoryChart
            day={selectedDay}
            segments={chronologicalSegments}
            storyHeadline={dashboard.story_headline}
            storySummary={dashboard.story_summary}
          />

          <section className="stats-grid" aria-live="polite">
            {statCards.map((card) => (
              <article key={card.label} className="stat-card">
                <span className="stat-card__label">{card.label}</span>
                <strong className="stat-card__value">{card.value}</strong>
                <p className="stat-card__note">{card.note}</p>
              </article>
            ))}
          </section>

          <section className="insight-grid">
            <article className="panel-card current-card">
              <div className="panel-card__header">
                <div>
                  <p className="section-kicker">Current Intent</p>
                  <h3>What the latest block looks like</h3>
                </div>
              </div>

              {dashboard.current_intent ? (
                <div className="intent-card">
                  <div className="intent-card__tags">
                    <span className={activityClassMap[dashboard.current_intent.activity_type] ?? activityClassMap.other}>
                      {dashboard.current_intent.activity_label}
                    </span>
                    <span className={focusClassMap[dashboard.current_intent.focus_state] ?? focusClassMap.steady}>
                      {dashboard.current_intent.focus_label}
                    </span>
                  </div>
                  <h4>{dashboard.current_intent.headline}</h4>
                  <p>{dashboard.current_intent.summary}</p>
                  <dl className="intent-card__facts">
                    <div>
                      <dt>Likely goal</dt>
                      <dd>{dashboard.current_intent.goal}</dd>
                    </div>
                    <div>
                      <dt>Project</dt>
                      <dd>{dashboard.current_intent.project}</dd>
                    </div>
                    <div>
                      <dt>Next step</dt>
                      <dd>{dashboard.current_intent.next_step}</dd>
                    </div>
                  </dl>
                </div>
              ) : (
                <div className="empty-state">
                  <h4>No activity yet</h4>
                  <p>As windows are captured and processed, your latest intent will appear here.</p>
                </div>
              )}
            </article>

            <article className="panel-card day-shape-card">
              <div className="panel-card__header">
                <div>
                  <p className="section-kicker">Day Shape</p>
                  <h3>Quick read on how time was spent</h3>
                </div>
              </div>

              <div className="day-shape-scroll">
                <div className="breakdown-block">
                  <h4>By activity type</h4>
                  {dashboard.breakdown.length > 0 ? (
                    <div className="breakdown-list">
                      {dashboard.breakdown.map((item) => (
                        <div key={item.label} className="breakdown-row">
                          <span>{item.label}</span>
                          <strong>{formatMinutes(item.minutes)}</strong>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">No completed segments to summarize yet.</p>
                  )}
                </div>

                <div className="breakdown-block">
                  <h4>By workstream</h4>
                  {dashboard.project_breakdown.length > 0 ? (
                    <div className="breakdown-list">
                      {dashboard.project_breakdown.map((item) => (
                        <div key={item.label} className="breakdown-row">
                          <span>{item.label}</span>
                          <strong>{formatMinutes(item.minutes)}</strong>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="muted">Projects will appear once the model can separate workstreams.</p>
                  )}
                </div>
              </div>
            </article>
          </section>

          <section className="panel-card timeline-card">
            <div className="panel-card__header">
              <div>
                <p className="section-kicker">Detailed Timeline</p>
                <h3>Chronological segments with intent and next-step hints</h3>
              </div>
            </div>

            {segments.length > 0 ? (
              <div className="timeline-scroll">
                <div className="timeline-list">
                  {detailedTimelineSegments.map((segment) => (
                    <article key={segment.window_id} className="timeline-item">
                      <div className="timeline-item__time">
                        <strong>{formatTime(segment.captured_from)}</strong>
                        <span>{formatTime(segment.captured_to)}</span>
                        <em>{formatMinutes(segment.duration_minutes)}</em>
                      </div>

                      <div className="timeline-item__body">
                        <div className="timeline-item__badges">
                          <span className={activityClassMap[segment.activity_type] ?? activityClassMap.other}>
                            {segment.activity_label}
                          </span>
                          <span className={focusClassMap[segment.focus_state] ?? focusClassMap.steady}>
                            {segment.focus_label}
                          </span>
                          <span className="project-pill">{segment.project}</span>
                        </div>

                        <h4>{segment.headline}</h4>
                        <p className="timeline-item__summary">{segment.summary}</p>

                        <div className="timeline-item__details">
                          <div>
                            <span className="detail-label">Goal</span>
                            <p>{segment.goal}</p>
                          </div>
                          <div>
                            <span className="detail-label">Next</span>
                            <p>{segment.next_step}</p>
                          </div>
                        </div>

                        <details className="timeline-item__raw">
                          <summary>Captured excerpt</summary>
                          <pre>{segment.raw_excerpt || "No excerpt available."}</pre>
                        </details>
                      </div>
                    </article>
                  ))}
                </div>
              </div>
            ) : (
              <div className="empty-state">
                <h4>Waiting for windows</h4>
                <p>{`Once activity is captured for ${formatDateLabel(selectedDay)}, this timeline will start filling in.`}</p>
              </div>
            )}
          </section>
        </>
      )}
    </div>
  );
}
