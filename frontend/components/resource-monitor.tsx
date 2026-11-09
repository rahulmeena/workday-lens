"use client";

import { initialDayValue } from "../lib/config";

import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { SetupPanel } from "./setup-panel";
import { ResourceMonitorResponse, fetchResourceMonitor, fetchSetupStatus } from "../lib/api";

const ICON_BASE = "/workday-lens-icons";
const WORKDAY_LENS_LOGO_SRC = `${ICON_BASE}/workday-lens-logo-main.png`;
const RESOURCE_POLL_INTERVAL_MS = 5_000;
const RESOURCE_RETENTION_MS = 7 * 24 * 60 * 60 * 1000;
const MAX_RESOURCE_SAMPLES = Math.ceil(RESOURCE_RETENTION_MS / RESOURCE_POLL_INTERVAL_MS);
const MAX_CHART_POINTS = 520;
const RESOURCE_X_TICK_COUNT = 5;

type ResourceRangeValue = "week" | "day" | "4h" | "1h";

const RESOURCE_RANGE_OPTIONS: Array<{ value: ResourceRangeValue; label: string }> = [
  { value: "week", label: "Week" },
  { value: "day", label: "Day" },
  { value: "4h", label: "4h" },
  { value: "1h", label: "1h" },
];

const RESOURCE_SIDEBAR_ITEMS = [
  { label: "Today", href: "/", iconSrc: `${ICON_BASE}/sidebar-today.svg` },
  { label: "Timeline", href: "/timeline", iconSrc: `${ICON_BASE}/sidebar-timeline.svg` },
  { label: "Capture Log", href: "/capture-log", iconSrc: `${ICON_BASE}/settings.svg` },
  { label: "Resources", href: "/resources", iconSrc: `${ICON_BASE}/focus-time-badge.svg` },
  { label: "Projects", iconSrc: `${ICON_BASE}/sidebar-projects.svg` },
  { label: "Insights", iconSrc: `${ICON_BASE}/sidebar-insights.svg` },
  { label: "Learnings", iconSrc: `${ICON_BASE}/sidebar-learnings.svg` },
];

const TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

const CONTROL_TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
});

const AXIS_TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
});

const CONTROL_DATE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "long",
  day: "numeric",
  year: "numeric",
});

const SHORT_DATE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
});

const NUMBER_FORMATTER = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 1,
});

const INTEGER_FORMATTER = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0,
});

interface ResourceSample {
  capturedAt: string;
  promptTps: number;
  completionTps: number;
  totalTps: number;
  cpuPercent: number;
  memoryGb: number;
  activeWindows: number;
  activeTokens: number;
  keepUpRatio: number;
  capacityPerMinute: number;
  arrivalPerMinute: number;
  latencySeconds: number;
  thermalRank: number;
  thermalState: string;
}

interface ChartSeries {
  label: string;
  color: string;
  value: (sample: ResourceSample) => number;
}

function IconImage({ className, src, size }: { className: string; src: string; size: number }) {
  return <Image className={className} src={src} alt="" width={size} height={size} aria-hidden="true" unoptimized />;
}

function profileInitial(displayName: string) {
  return displayName.trim().charAt(0).toUpperCase() || "?";
}

function isSidebarItemActive(href: string, pathname: string | null) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || Boolean(pathname?.startsWith(`${href}/`));
}

function formatTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return TIME_FORMATTER.format(date);
}

function formatAxisTime(value: number) {
  return AXIS_TIME_FORMATTER.format(new Date(value));
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

function dateFromDayValue(day: string) {
  const [year, month, value] = day.split("-").map(Number);
  return new Date(year, (month || 1) - 1, value || 1);
}

function addDays(value: Date, days: number) {
  const next = new Date(value);
  next.setDate(next.getDate() + days);
  return next;
}

function shiftDayValue(day: string, offset: number) {
  return toDateInputValue(addDays(dateFromDayValue(day), offset));
}

function dayRange(day: string) {
  const start = dateFromDayValue(day);
  return {
    start,
    end: addDays(start, 1),
  };
}

function weekRange(day: string) {
  const selected = dateFromDayValue(day);
  const daysSinceMonday = (selected.getDay() + 6) % 7;
  const start = addDays(selected, -daysSinceMonday);
  return {
    start,
    end: addDays(start, 7),
  };
}

function hourRange(day: string, hour: number) {
  const start = dateFromDayValue(day);
  start.setHours(hour, 0, 0, 0);
  return {
    start,
    end: new Date(start.getTime() + 60 * 60 * 1000),
  };
}

function fourHourRange(day: string, hour: number) {
  const start = dateFromDayValue(day);
  start.setHours(hour, 0, 0, 0);
  return {
    start,
    end: new Date(start.getTime() + 4 * 60 * 60 * 1000),
  };
}

function rangeForResourceView(day: string, mode: ResourceRangeValue, hour: number, fourHour: number) {
  if (mode === "week") {
    return weekRange(day);
  }
  if (mode === "4h") {
    return fourHourRange(day, fourHour);
  }
  if (mode === "1h") {
    return hourRange(day, hour);
  }
  return dayRange(day);
}

function formatDatePickerLabel(day: string) {
  return CONTROL_DATE_FORMATTER.format(dateFromDayValue(day));
}

function formatResourceViewLabel(start: Date, end: Date, mode: ResourceRangeValue) {
  if (mode === "week") {
    return `${SHORT_DATE_FORMATTER.format(start)} - ${SHORT_DATE_FORMATTER.format(addDays(end, -1))}`;
  }
  if (mode === "4h" || mode === "1h") {
    return `${SHORT_DATE_FORMATTER.format(start)}, ${CONTROL_TIME_FORMATTER.format(start)} - ${CONTROL_TIME_FORMATTER.format(end)}`;
  }
  return CONTROL_DATE_FORMATTER.format(start);
}

function formatNumber(value: number, suffix = "") {
  return `${NUMBER_FORMATTER.format(value)}${suffix}`;
}

function formatInteger(value: number) {
  return INTEGER_FORMATTER.format(value);
}

function formatMemory(memoryMb: number) {
  if (memoryMb >= 1024) {
    return `${NUMBER_FORMATTER.format(memoryMb / 1024)} GB`;
  }
  return `${INTEGER_FORMATTER.format(memoryMb)} MB`;
}

function formatDurationMs(value: number) {
  if (!value) {
    return "0s";
  }
  if (value < 1000) {
    return `${INTEGER_FORMATTER.format(value)}ms`;
  }
  return `${NUMBER_FORMATTER.format(value / 1000)}s`;
}

function formatStaleSeconds(value?: number | null) {
  if (value == null) {
    return "Waiting for helper heartbeat";
  }
  if (value < 60) {
    return `Updated ${INTEGER_FORMATTER.format(value)}s ago`;
  }
  return `Updated ${NUMBER_FORMATTER.format(value / 60)} min ago`;
}

function formatThermalState(state: string) {
  const cleaned = state.trim().toLowerCase();
  if (!cleaned || cleaned === "unknown") {
    return "Unknown";
  }
  return cleaned.charAt(0).toUpperCase() + cleaned.slice(1);
}

function sampleTime(sample: ResourceSample) {
  const parsed = Date.parse(sample.capturedAt);
  return Number.isFinite(parsed) ? parsed : 0;
}

function downsampleSamples(samples: ResourceSample[], maxPoints: number) {
  if (samples.length <= maxPoints) {
    return samples;
  }
  const stride = Math.ceil(samples.length / maxPoints);
  const result = samples.filter((_, index) => index % stride === 0);
  const last = samples[samples.length - 1];
  if (result[result.length - 1] !== last) {
    result.push(last);
  }
  return result;
}

function sampleFromResponse(data: ResourceMonitorResponse): ResourceSample {
  const thermal = data.thermal ?? { state: "unknown", rank: -1 };
  const thermalRank = thermal.rank >= 0 ? thermal.rank : 0;
  return {
    capturedAt: data.captured_at,
    promptTps: data.throughput.avg_prompt_tokens_per_second,
    completionTps: data.throughput.avg_completion_tokens_per_second,
    totalTps: data.throughput.avg_total_tokens_per_second,
    cpuPercent: data.qwen.cpu_percent,
    memoryGb: data.qwen.memory_mb / 1024,
    activeWindows: data.backlog.active_windows,
    activeTokens: data.backlog.active_window_tokens,
    keepUpRatio: data.throughput.keep_up_ratio,
    capacityPerMinute: data.throughput.windows_per_minute_capacity,
    arrivalPerMinute: data.throughput.capture_windows_per_minute,
    latencySeconds: data.throughput.avg_window_latency_ms / 1000,
    thermalRank,
    thermalState: thermal.state,
  };
}

function ResourceSidebar({
  displayName,
  onSettingsClick,
}: {
  displayName: string;
  onSettingsClick: () => void;
}) {
  const pathname = usePathname();
  return (
    <aside className="hierarchy-sidebar" aria-label="Workday Lens collapsed navigation">
      <Link href="/" className="hierarchy-sidebar__logo" aria-label="Go to Today" title="Workday Lens">
        <IconImage className="hierarchy-sidebar__logo-image" src={WORKDAY_LENS_LOGO_SRC} size={56} />
      </Link>
      <nav className="hierarchy-sidebar__nav">
        {RESOURCE_SIDEBAR_ITEMS.map((item) =>
          item.href ? (
            <Link
              key={item.label}
              href={item.href}
              className={`hierarchy-sidebar__item ${isSidebarItemActive(item.href, pathname) ? "is-active" : ""}`}
              aria-current={isSidebarItemActive(item.href, pathname) ? "page" : undefined}
              aria-label={item.label}
              title={item.label}
            >
              <IconImage className="hierarchy-sidebar__icon" src={item.iconSrc} size={28} />
              <span>{item.label}</span>
            </Link>
          ) : (
            <button key={item.label} type="button" className="hierarchy-sidebar__item" disabled aria-label={item.label} title={item.label}>
              <IconImage className="hierarchy-sidebar__icon" src={item.iconSrc} size={28} />
              <span>{item.label}</span>
            </button>
          ),
        )}
      </nav>
      <div className="hierarchy-sidebar__bottom">
        <button
          type="button"
          className="hierarchy-sidebar__item hierarchy-sidebar__item--settings"
          aria-label="Open local settings"
          title="Settings"
          onClick={onSettingsClick}
        >
          <IconImage className="hierarchy-sidebar__icon" src={`${ICON_BASE}/settings.svg`} size={26} />
          <span>Settings</span>
        </button>
        <div className="hierarchy-sidebar__avatar" aria-label={displayName} title={displayName}>
          {profileInitial(displayName)}
        </div>
      </div>
    </aside>
  );
}

function MiniLineChart({
  samples,
  series,
  emptyLabel,
  rangeStart,
  rangeEnd,
}: {
  samples: ResourceSample[];
  series: ChartSeries[];
  emptyLabel: string;
  rangeStart: Date;
  rangeEnd: Date;
}) {
  const width = 620;
  const height = 210;
  const plotLeft = 32;
  const plotRight = width - 24;
  const plotTop = 28;
  const plotBottom = height - 42;
  const domainStart = rangeStart.getTime();
  const domainEnd = rangeEnd.getTime();
  const domainSpan = Math.max(domainEnd - domainStart, 1);
  const visibleSamples = samples.filter((sample) => {
    const time = sampleTime(sample);
    return time >= domainStart && time <= domainEnd;
  });
  const chartSamples = downsampleSamples(visibleSamples, MAX_CHART_POINTS);
  const xTicks = Array.from({ length: RESOURCE_X_TICK_COUNT }, (_, index) => domainStart + (domainSpan * index) / (RESOURCE_X_TICK_COUNT - 1));
  const values = series.flatMap((item) => visibleSamples.map((sample) => item.value(sample)).filter((value) => Number.isFinite(value)));
  const maxValue = Math.max(1, ...values);
  const minValue = Math.min(0, ...values);
  const span = Math.max(maxValue - minValue, 1);

  if (visibleSamples.length < 2) {
    return (
      <div className="resource-chart__empty">
        <span>{emptyLabel}</span>
      </div>
    );
  }

  function pointFor(sample: ResourceSample, getter: (sample: ResourceSample) => number) {
    const xRatio = Math.min(Math.max((sampleTime(sample) - domainStart) / domainSpan, 0), 1);
    const x = plotLeft + xRatio * (plotRight - plotLeft);
    const normalized = (getter(sample) - minValue) / span;
    const y = plotBottom - normalized * (plotBottom - plotTop);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }

  return (
    <svg className="resource-chart__svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Resource time series">
      {xTicks.map((tick, index) => {
        const x = plotLeft + ((tick - domainStart) / domainSpan) * (plotRight - plotLeft);
        const anchor = index === 0 ? "start" : index === xTicks.length - 1 ? "end" : "middle";
        return (
          <g key={tick}>
            <line x1={x} x2={x} y1={plotTop} y2={plotBottom} className="resource-chart__grid" />
            <text x={x} y={height - 12} textAnchor={anchor} className="resource-chart__time">
              {formatAxisTime(tick)}
            </text>
          </g>
        );
      })}
      <line x1={plotLeft} x2={plotRight} y1={plotBottom} y2={plotBottom} className="resource-chart__axis" />
      <line x1={plotLeft} x2={plotLeft} y1={plotTop} y2={plotBottom} className="resource-chart__axis" />
      <text x={plotLeft} y={18} className="resource-chart__tick">
        {formatNumber(maxValue)}
      </text>
      <text x={plotLeft + 2} y={plotBottom - 6} className="resource-chart__tick">
        {formatNumber(minValue)}
      </text>
      {series.map((item) => (
        <polyline
          key={item.label}
          points={chartSamples.map((sample) => pointFor(sample, item.value)).join(" ")}
          fill="none"
          stroke={item.color}
          strokeWidth="3"
          strokeLinecap="round"
          strokeLinejoin="round"
          vectorEffect="non-scaling-stroke"
        />
      ))}
    </svg>
  );
}

function ChartPanel({
  title,
  subtitle,
  samples,
  series,
  rangeStart,
  rangeEnd,
}: {
  title: string;
  subtitle: string;
  samples: ResourceSample[];
  series: ChartSeries[];
  rangeStart: Date;
  rangeEnd: Date;
}) {
  return (
    <section className="resource-panel resource-chart">
      <div className="resource-panel__header">
        <div>
          <h2>{title}</h2>
          <p>{subtitle}</p>
        </div>
        <div className="resource-chart__legend">
          {series.map((item) => (
            <span key={item.label}>
              <i style={{ backgroundColor: item.color }} />
              {item.label}
            </span>
          ))}
        </div>
      </div>
      <MiniLineChart
        samples={samples}
        series={series}
        emptyLabel="Waiting for a second resource sample in this range."
        rangeStart={rangeStart}
        rangeEnd={rangeEnd}
      />
    </section>
  );
}

function KpiCard({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: string;
  detail: string;
  tone?: "neutral" | "good" | "warn" | "hot";
}) {
  return (
    <section className={`resource-kpi resource-kpi--${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{detail}</small>
    </section>
  );
}

function keepUpTone(ratio: number, hasRuns: boolean): "neutral" | "good" | "warn" | "hot" {
  if (!hasRuns) {
    return "neutral";
  }
  if (ratio >= 1.25) {
    return "good";
  }
  if (ratio >= 1) {
    return "warn";
  }
  return "hot";
}

function thermalTone(rank: number): "neutral" | "good" | "warn" | "hot" {
  if (rank < 0) {
    return "neutral";
  }
  if (rank === 0) {
    return "good";
  }
  if (rank === 1) {
    return "warn";
  }
  return "hot";
}

function cacheLabel(cacheRamMb: number) {
  return cacheRamMb > 0 ? `cache ${formatInteger(cacheRamMb)} MB` : "cache off";
}

function backlogTrendLabel(data: ResourceMonitorResponse) {
  const throughput = data.throughput;
  if (throughput.recent_window_runs === 0) {
    return "Waiting for inference sample";
  }
  if (throughput.estimated_backlog_change_per_hour > 0) {
    return `Growing by ${formatNumber(throughput.estimated_backlog_change_per_hour)} windows/hour`;
  }
  if (throughput.estimated_backlog_drain_minutes != null) {
    return `Drains in about ${formatNumber(throughput.estimated_backlog_drain_minutes)} min`;
  }
  return "Stable or draining";
}

export function ResourceMonitor() {
  const [samples, setSamples] = useState<ResourceSample[]>([]);
  const [showSettings, setShowSettings] = useState(false);
  const [selectedDay, setSelectedDay] = useState(initialDayValue);
  const [selectedRange, setSelectedRange] = useState<ResourceRangeValue>("day");
  const [selectedHour, setSelectedHour] = useState(() => new Date().getHours());
  const [selectedFourHour, setSelectedFourHour] = useState(() => Math.floor(new Date().getHours() / 4) * 4);
  const dateInputRef = useRef<HTMLInputElement | null>(null);
  const resourceQuery = useQuery({
    queryKey: ["resource-monitor"],
    queryFn: fetchResourceMonitor,
    refetchInterval: RESOURCE_POLL_INTERVAL_MS,
  });
  const setupQuery = useQuery({
    queryKey: ["setup-status", "resources"],
    queryFn: fetchSetupStatus,
    refetchInterval: 30_000,
  });

  useEffect(() => {
    if (!resourceQuery.data) {
      return;
    }
    const nextSample = sampleFromResponse(resourceQuery.data);
    setSamples((current) => {
      if (current.some((sample) => sample.capturedAt === nextSample.capturedAt)) {
        return current;
      }
      const cutoff = Date.now() - RESOURCE_RETENTION_MS;
      return [...current.filter((sample) => sampleTime(sample) >= cutoff), nextSample].slice(-MAX_RESOURCE_SAMPLES);
    });
  }, [resourceQuery.data]);

  const data = resourceQuery.data;
  const profileName = setupQuery.data?.runtime_settings.display_name.trim() || "You";
  const today = todayDateValue();
  const currentHour = new Date().getHours();
  const maxHourForSelectedDay = selectedDay === today ? currentHour : 23;
  const maxFourHourForSelectedDay = selectedDay === today ? Math.floor(currentHour / 4) * 4 : 20;
  const nextSelectedDay = shiftDayValue(selectedDay, selectedRange === "week" ? 7 : 1);
  const canMoveForward = nextSelectedDay <= today;
  const canMovePeriodBack = selectedRange === "1h" ? selectedHour > 0 : selectedRange === "4h" ? selectedFourHour > 0 : false;
  const canMovePeriodForward =
    selectedRange === "1h"
      ? selectedHour < maxHourForSelectedDay
      : selectedRange === "4h"
        ? selectedFourHour < maxFourHourForSelectedDay
        : false;
  const viewRange = useMemo(
    () => rangeForResourceView(selectedDay, selectedRange, selectedHour, selectedFourHour),
    [selectedDay, selectedFourHour, selectedHour, selectedRange],
  );
  const hasRuns = Boolean(data && data.throughput.recent_window_runs > 0);
  const latestRun = data?.recent_completions[data.recent_completions.length - 1];
  const thermalSnapshot = data?.thermal ?? { state: "unknown", rank: -1, source: "unavailable", stale_seconds: null };

  useEffect(() => {
    setSelectedHour((current) => Math.min(current, maxHourForSelectedDay));
    setSelectedFourHour((current) => Math.min(current, maxFourHourForSelectedDay));
  }, [maxFourHourForSelectedDay, maxHourForSelectedDay]);

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

  function shiftPeriod(offset: number) {
    if (selectedRange === "1h") {
      setSelectedHour((current) => Math.max(0, Math.min(maxHourForSelectedDay, current + offset)));
      return;
    }
    if (selectedRange === "4h") {
      setSelectedFourHour((current) => Math.max(0, Math.min(maxFourHourForSelectedDay, current + offset * 4)));
    }
  }

  function handleRangeChange(value: ResourceRangeValue) {
    setSelectedRange(value);
    if (value === "1h") {
      setSelectedHour((current) => Math.min(current, maxHourForSelectedDay));
    }
    if (value === "4h") {
      setSelectedFourHour((current) => Math.min(current, maxFourHourForSelectedDay));
    }
  }

  const speedSeries = useMemo<ChartSeries[]>(
    () => [
      { label: "pg/s", color: "#3f7f8f", value: (sample) => sample.promptTps },
      { label: "tg/s", color: "#e36f2c", value: (sample) => sample.completionTps },
      { label: "total tok/s", color: "#6d8f48", value: (sample) => sample.totalTps },
    ],
    [],
  );
  const loadSeries = useMemo<ChartSeries[]>(
    () => [
      { label: "Qwen CPU %", color: "#c45a2a", value: (sample) => sample.cpuPercent },
      { label: "Qwen memory GB", color: "#547f71", value: (sample) => sample.memoryGb },
    ],
    [],
  );
  const backlogSeries = useMemo<ChartSeries[]>(
    () => [
      { label: "active windows", color: "#9b5b2d", value: (sample) => sample.activeWindows },
      { label: "backlog tokens / 1k", color: "#4f7a9f", value: (sample) => sample.activeTokens / 1000 },
      { label: "keep-up ratio", color: "#5f934f", value: (sample) => sample.keepUpRatio },
    ],
    [],
  );
  const thermalSeries = useMemo<ChartSeries[]>(
    () => [{ label: "thermal rank", color: "#b64631", value: (sample) => sample.thermalRank }],
    [],
  );

  return (
    <div className="resource-monitor">
      {showSettings && setupQuery.data && (
        <div className="lens-settings-layer">
          <SetupPanel
            setup={setupQuery.data}
            onSaved={() => {
              void setupQuery.refetch();
              void resourceQuery.refetch();
            }}
            mode="manage"
            onClose={() => setShowSettings(false)}
          />
        </div>
      )}

      <ResourceSidebar displayName={profileName} onSettingsClick={() => setShowSettings(true)} />

      <main className="resource-main">
        <header className="resource-hero">
          <div className="resource-hero__copy">
            <span>Local model health</span>
            <h1>Resources</h1>
            <p>Qwen throughput, memory, CPU, and backlog pressure while Workday Lens is running.</p>
          </div>
          <div className={`resource-health resource-health--${data?.qwen.running ? "running" : "idle"}`} aria-live="polite">
            <i />
            <div>
              <strong>{data?.qwen.running ? "Local Qwen running" : "Local Qwen idle"}</strong>
              <span>{data ? `${data.qwen.state} at ${formatTime(data.captured_at)}` : "Loading resource monitor"}</span>
            </div>
          </div>
        </header>

        {resourceQuery.error && (
          <section className="resource-panel resource-panel--error">
            <h2>Resource monitor unavailable</h2>
            <p>{resourceQuery.error instanceof Error ? resourceQuery.error.message : "Could not load resource data."}</p>
          </section>
        )}

        {data ? (
          <>
            <section className="resource-timebar" aria-label="Resource chart time range">
              <div className="resource-date-control">
                <button
                  type="button"
                  aria-label={selectedRange === "week" ? "Previous week" : "Previous day"}
                  onClick={() => setSelectedDay((current) => shiftDayValue(current, selectedRange === "week" ? -7 : -1))}
                >
                  <span aria-hidden="true">{"<"}</span>
                </button>
                <button
                  type="button"
                  className="resource-date-control__picker"
                  aria-label={`Choose resource chart date. Current selection is ${formatResourceViewLabel(viewRange.start, viewRange.end, selectedRange)}`}
                  onClick={openDatePicker}
                >
                  <span className="resource-calendar-icon" aria-hidden="true" />
                  {formatResourceViewLabel(viewRange.start, viewRange.end, selectedRange)}
                </button>
                <button
                  type="button"
                  aria-label={selectedRange === "week" ? "Next week" : "Next day"}
                  onClick={() => setSelectedDay((current) => shiftDayValue(current, selectedRange === "week" ? 7 : 1))}
                  disabled={!canMoveForward}
                >
                  <span aria-hidden="true">{">"}</span>
                </button>
                <input
                  ref={dateInputRef}
                  className="resource-date-control__native"
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
              </div>

              <div className="resource-range-control" role="tablist" aria-label="Resource chart range">
                {RESOURCE_RANGE_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    className={selectedRange === option.value ? "is-active" : ""}
                    onClick={() => handleRangeChange(option.value)}
                    aria-selected={selectedRange === option.value}
                    role="tab"
                  >
                    {option.label}
                  </button>
                ))}
              </div>

              {(selectedRange === "1h" || selectedRange === "4h") && (
                <div className="resource-period-control" aria-label={`${selectedRange} period navigation`}>
                  <button type="button" onClick={() => shiftPeriod(-1)} disabled={!canMovePeriodBack}>
                    <span aria-hidden="true">{"<"}</span>
                  </button>
                  <strong>
                    {CONTROL_TIME_FORMATTER.format(viewRange.start)} - {CONTROL_TIME_FORMATTER.format(viewRange.end)}
                  </strong>
                  <button type="button" onClick={() => shiftPeriod(1)} disabled={!canMovePeriodForward}>
                    <span aria-hidden="true">{">"}</span>
                  </button>
                </div>
              )}
            </section>

            <section className="resource-kpis" aria-label="Resource summary">
              <KpiCard
                label="Keep-up ratio"
                value={`${formatNumber(data.throughput.keep_up_ratio)}x`}
                detail={backlogTrendLabel(data)}
                tone={keepUpTone(data.throughput.keep_up_ratio, hasRuns)}
              />
              <KpiCard
                label="Generation speed"
                value={`${formatNumber(data.throughput.avg_completion_tokens_per_second)} tg/s`}
                detail={`${formatNumber(data.throughput.avg_prompt_tokens_per_second)} pg/s prompt eval`}
                tone={hasRuns ? "good" : "neutral"}
              />
              <KpiCard
                label="Qwen CPU"
                value={`${formatNumber(data.qwen.cpu_percent)}%`}
                detail={`Memory ${formatMemory(data.qwen.memory_mb)}`}
                tone={data.qwen.cpu_percent > 250 ? "hot" : data.qwen.cpu_percent > 125 ? "warn" : "neutral"}
              />
              <KpiCard
                label="Thermal state"
                value={formatThermalState(thermalSnapshot.state)}
                detail={`${formatStaleSeconds(thermalSnapshot.stale_seconds)} - ${thermalSnapshot.source}`}
                tone={thermalTone(thermalSnapshot.rank)}
              />
              <KpiCard
                label="Backlog"
                value={`${formatInteger(data.backlog.active_windows)} windows`}
                detail={`${formatInteger(data.backlog.active_window_tokens)} tokens queued`}
                tone={data.backlog.active_windows > 20 ? "hot" : data.backlog.active_windows > 5 ? "warn" : "good"}
              />
              <KpiCard
                label="Window latency"
                value={formatDurationMs(data.throughput.avg_window_latency_ms)}
                detail={`${formatNumber(data.throughput.windows_per_minute_capacity)} windows/min capacity`}
                tone={hasRuns && data.throughput.keep_up_ratio < 1 ? "hot" : "neutral"}
              />
              <KpiCard
                label="Context"
                value={`${formatInteger(data.qwen.ctx_size / 1024)}k`}
                detail={`Max ${formatInteger(data.qwen.max_ctx_size / 1024)}k, predict ${formatInteger(data.qwen.predict_tokens)}, threads ${formatInteger(data.qwen.threads)}/${formatInteger(data.qwen.threads_batch)}, ${cacheLabel(data.qwen.cache_ram_mb)}`}
                tone={data.qwen.ctx_size > 32768 ? "warn" : "neutral"}
              />
            </section>

            <section className="resource-grid">
              <ChartPanel
                title="Inference Speed"
                subtitle="Prompt eval speed and generation speed from recent llama.cpp completions."
                samples={samples}
                series={speedSeries}
                rangeStart={viewRange.start}
                rangeEnd={viewRange.end}
              />
              <ChartPanel
                title="Mac Load"
                subtitle="Local Qwen process CPU and resident memory."
                samples={samples}
                series={loadSeries}
                rangeStart={viewRange.start}
                rangeEnd={viewRange.end}
              />
              <ChartPanel
                title="Thermal Pressure"
                subtitle="macOS helper heartbeat: 0 nominal, 1 fair, 2 serious, 3 critical."
                samples={samples}
                series={thermalSeries}
                rangeStart={viewRange.start}
                rangeEnd={viewRange.end}
              />
              <ChartPanel
                title="Backlog Pressure"
                subtitle="Pending analysis work against model capacity."
                samples={samples}
                series={backlogSeries}
                rangeStart={viewRange.start}
                rangeEnd={viewRange.end}
              />

              <section className="resource-panel resource-panel--wide">
                <div className="resource-panel__header">
                  <div>
                    <h2>Processes</h2>
                    <p>CPU and memory are sampled from macOS process stats.</p>
                  </div>
                </div>
                <div className="resource-table resource-process-table">
                  <div className="resource-table__head">
                    <span>Process</span>
                    <span>Status</span>
                    <span>PID</span>
                    <span>CPU</span>
                    <span>Memory</span>
                  </div>
                  {data.processes.map((process) => (
                    <div className="resource-table__row" key={process.role} title={process.command ?? undefined}>
                      <strong>{process.name}</strong>
                      <span>{process.running ? "Running" : "Idle"}</span>
                      <span>{process.pid ?? "-"}</span>
                      <span>{formatNumber(process.cpu_percent)}%</span>
                      <span>{formatMemory(process.memory_mb)}</span>
                    </div>
                  ))}
                </div>
              </section>

              <section className="resource-panel resource-panel--wide">
                <div className="resource-panel__header">
                  <div>
                    <h2>Recent Qwen Runs</h2>
                    <p>Latest completions seen by this backend process.</p>
                  </div>
                  {latestRun && <span className="resource-panel__pill">last {formatTime(latestRun.finished_at)}</span>}
                </div>
                <div className="resource-table resource-run-table">
                  <div className="resource-table__head">
                    <span>Time</span>
                    <span>Ctx</span>
                    <span>Prompt</span>
                    <span>Output</span>
                    <span>pg/s</span>
                    <span>tg/s</span>
                    <span>Latency</span>
                  </div>
                  {data.recent_completions.length === 0 ? (
                    <div className="resource-table__empty">No local Qwen completions sampled since this backend started.</div>
                  ) : (
                    [...data.recent_completions].reverse().slice(0, 12).map((run) => (
                      <div className="resource-table__row" key={`${run.started_at}-${run.latency_ms}`}>
                        <strong>{formatTime(run.finished_at)}</strong>
                        <span>{formatInteger(run.ctx_size / 1024)}k</span>
                        <span>{formatInteger(run.prompt_tokens)}</span>
                        <span>{formatInteger(run.completion_tokens)}</span>
                        <span>{formatNumber(run.prompt_tokens_per_second)}</span>
                        <span>{formatNumber(run.completion_tokens_per_second)}</span>
                        <span>{formatDurationMs(run.latency_ms)}</span>
                      </div>
                    ))
                  )}
                </div>
              </section>
            </section>
          </>
        ) : (
          <section className="resource-panel resource-panel--loading">
            <h2>Loading resource monitor</h2>
            <p>Collecting the first local snapshot.</p>
          </section>
        )}
      </main>
    </div>
  );
}
