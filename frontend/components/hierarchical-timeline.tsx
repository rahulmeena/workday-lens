"use client";

import { initialDayValue } from "../lib/config";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";

import { SetupPanel } from "./setup-panel";
import {
  ActivityLLMDebugResponse,
  ActivityRollupItem,
  ActivitySegment,
  RuntimeSettingsResponse,
  fetchActivityDashboard,
  fetchActivityLLMDebug,
  fetchActivityRollupsRange,
  fetchSetupStatus,
  reprocessActivityRange,
} from "../lib/api";

type RollupLevel = "5m" | "15m" | "1h" | "4h" | "1d" | "1w";
type TimelineLevel = "1m" | RollupLevel;
type ActivityStatus = "queued" | "processing" | "processed" | "violation" | "pending_llm";

interface TimelineDetail {
  time: string;
  text: string;
}

interface TimelineCardItem {
  id: string;
  level: TimelineLevel;
  start: string;
  end: string;
  durationMinutes: number;
  title: string;
  summary: string;
  project: string;
  activityLabel: string;
  focusLabel: string;
  details: TimelineDetail[];
  sourceCount: number;
  confidence: number;
  status: ActivityStatus;
  modelName?: string | null;
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  latencyMs: number;
}

interface TimelineColumn {
  level: TimelineLevel;
  title: string;
  subtitle: string;
  iconSrc: string;
  items: TimelineCardItem[];
  loading: boolean;
  error: boolean;
  disabled?: boolean;
  emptyText: string;
  queuedCount: number;
  processingCount: number;
  pendingCount: number;
}

interface LLMDebugTarget {
  id: string;
  level: TimelineLevel;
  title: string;
  range: string;
}

const ICON_BASE = "/workday-lens-icons";
const WORKDAY_LENS_LOGO_SRC = `${ICON_BASE}/workday-lens-logo-main.png`;
const REFRESH_ICON_SRC = `${ICON_BASE}/refresh-icon.svg`;
const TIMELINE_HERO_ART_SRC = "/workday-lens-art/timeline-dunes.png";
const TIMELINE_POLL_INTERVAL = 60_000;
const INITIAL_TIMELINE_CARD_LIMIT = 25;
const TIMELINE_CARD_BATCH_SIZE = 25;
const RAW_EVENT_TEXT_LIMIT = 220;
const TIMELINE_DEBUG_STORAGE_KEY = "workday-lens:timeline-debug";
const TIMELINE_DEBUG_QUERY_PARAM = "debug";
const TIMELINE_DEBUG_ENV_ENABLED = ["1", "true", "yes", "on"].includes(
  (process.env.NEXT_PUBLIC_TIMELINE_DEBUG ?? "").trim().toLowerCase(),
);

const TIMELINE_SIDEBAR_ITEMS = [
  { label: "Today", href: "/", iconSrc: `${ICON_BASE}/sidebar-today.svg` },
  { label: "Timeline", href: "/timeline", iconSrc: `${ICON_BASE}/sidebar-timeline.svg` },
  { label: "Capture Log", href: "/capture-log", iconSrc: `${ICON_BASE}/settings.svg` },
  { label: "Resources", href: "/resources", iconSrc: `${ICON_BASE}/focus-time-badge.svg` },
  { label: "Projects", iconSrc: `${ICON_BASE}/sidebar-projects.svg` },
  { label: "Insights", iconSrc: `${ICON_BASE}/sidebar-insights.svg` },
  { label: "Learnings", iconSrc: `${ICON_BASE}/sidebar-learnings.svg` },
];

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

const TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
});

const SECOND_FORMATTER = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

const WEEK_RANGE_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
});

const TOKEN_FORMATTER = new Intl.NumberFormat("en-US");

const TIMELINE_LEVELS: Array<{
  level: TimelineLevel;
  title: string;
  subtitle: string;
  iconSrc: string;
}> = [
  { level: "1m", title: "1 min", subtitle: "Raw activity", iconSrc: `${ICON_BASE}/sunrise-badge.svg` },
  { level: "5m", title: "5 min", subtitle: "Small rollups", iconSrc: `${ICON_BASE}/sidebar-timeline.svg` },
  { level: "15m", title: "15 min", subtitle: "Intent clusters", iconSrc: `${ICON_BASE}/meetings-time-badge.svg` },
  { level: "1h", title: "1 hour", subtitle: "Activity topics", iconSrc: `${ICON_BASE}/focus-time-badge.svg` },
  { level: "4h", title: "4 hours", subtitle: "Focus windows", iconSrc: `${ICON_BASE}/deep-work.svg` },
  { level: "1d", title: "1 day", subtitle: "Daily themes", iconSrc: `${ICON_BASE}/insight-bulb.svg` },
  { level: "1w", title: "1 week", subtitle: "Weekly patterns", iconSrc: `${ICON_BASE}/sidebar-insights.svg` },
];

function IconImage({ className, src, size }: { className: string; src: string; size: number }) {
  return <Image className={className} src={src} alt="" width={size} height={size} aria-hidden="true" unoptimized />;
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
  start.setHours(0, 0, 0, 0);
  const end = addDays(start, 1);
  return { start, end };
}

function weekRange(day: string) {
  const start = dateFromDayValue(day);
  start.setDate(start.getDate() - ((start.getDay() + 6) % 7));
  start.setHours(0, 0, 0, 0);
  const end = addDays(start, 7);
  return { start, end };
}

function formatDatePickerLabel(day: string) {
  return CONTROL_DATE_FORMATTER.format(dateFromDayValue(day));
}

function formatTime(value: string) {
  return TIME_FORMATTER.format(new Date(value));
}

function formatTimeWithSeconds(value: string) {
  return SECOND_FORMATTER.format(new Date(value));
}

function isEnabledDebugValue(value: string | null) {
  return value ? ["1", "true", "yes", "on"].includes(value.trim().toLowerCase()) : false;
}

function initialTimelineDebugEnabled() {
  if (TIMELINE_DEBUG_ENV_ENABLED) {
    return true;
  }
  if (typeof window === "undefined") {
    return false;
  }
  try {
    const params = new URLSearchParams(window.location.search);
    const debugParam = params.get(TIMELINE_DEBUG_QUERY_PARAM);
    if (debugParam !== null) {
      const enabled = isEnabledDebugValue(debugParam);
      if (enabled) {
        window.localStorage.setItem(TIMELINE_DEBUG_STORAGE_KEY, "1");
      } else {
        window.localStorage.removeItem(TIMELINE_DEBUG_STORAGE_KEY);
      }
      return enabled;
    }
    return window.localStorage.getItem(TIMELINE_DEBUG_STORAGE_KEY) === "1";
  } catch {
    return false;
  }
}

function formatTokenCount(value: number) {
  return TOKEN_FORMATTER.format(Math.max(0, Math.round(value)));
}

function formatLatency(value: number) {
  const ms = Math.max(0, Math.round(value));
  if (ms < 1000) {
    return `${ms} ms`;
  }
  const seconds = ms / 1000;
  return `${seconds.toFixed(seconds < 10 ? 1 : 0)} s`;
}

function formatCardRange(item: TimelineCardItem, selectedDay: string) {
  const start = new Date(item.start);
  const end = new Date(item.end);
  if (item.level === "1w") {
    const selectedDate = dateFromDayValue(selectedDay);
    const visibleEnd = selectedDate.getTime() < end.getTime() ? selectedDate : addDays(end, -1);
    if (toDateInputValue(start) === toDateInputValue(visibleEnd)) {
      return WEEK_RANGE_FORMATTER.format(start);
    }
    return `${WEEK_RANGE_FORMATTER.format(start)} - ${WEEK_RANGE_FORMATTER.format(visibleEnd)}`;
  }
  if (item.level === "1d") {
    return SHORT_DATE_FORMATTER.format(start);
  }
  return `${formatTime(item.start)} - ${formatTime(item.end)}`;
}

function soFarLabel(item: TimelineCardItem, selectedDay: string) {
  if (selectedDay !== todayDateValue() || (item.level !== "1d" && item.level !== "1w")) {
    return "";
  }
  const start = new Date(item.start);
  if (Number.isNaN(start.getTime())) {
    return "";
  }
  if (item.level === "1d" && toDateInputValue(start) === selectedDay) {
    return "Day so far";
  }
  if (item.level === "1w" && toDateInputValue(start) === toDateInputValue(weekRange(selectedDay).start)) {
    return "Week so far";
  }
  return "";
}

function formatRawTimestamp(value: string, fallback: string) {
  const parsed = new Date(value);
  if (!Number.isNaN(parsed.getTime())) {
    return SECOND_FORMATTER.format(parsed);
  }
  const clock = value.match(/\d{1,2}:\d{2}(?::\d{2})?\s?(?:AM|PM)?/i);
  if (clock) {
    return clock[0];
  }
  return formatTimeWithSeconds(fallback);
}

function cleanEventText(value: string) {
  const cleaned = value
    .replace(/\s+/g, " ")
    .replace(/^\[mouse action\]\s*/i, "Mouse action ")
    .replace(/^\[mouse hover summary:/i, "Mouse hover summary:")
    .trim();
  const eventText = cleaned || "Activity event";
  if (eventText.length <= RAW_EVENT_TEXT_LIMIT) {
    return eventText;
  }
  return `${eventText.slice(0, RAW_EVENT_TEXT_LIMIT).trimEnd()}... [truncated for display]`;
}

function parseRawEventLine(line: string, fallbackTime: string): TimelineDetail | null {
  const trimmed = line.trim();
  if (!trimmed) {
    return null;
  }
  const timestamped = trimmed.match(/^\[([^\]]+)\]\s*(.*)$/);
  if (timestamped) {
    return {
      time: formatRawTimestamp(timestamped[1], fallbackTime),
      text: cleanEventText(timestamped[2]),
    };
  }
  return {
    time: formatTimeWithSeconds(fallbackTime),
    text: cleanEventText(trimmed),
  };
}

function splitSentences(value: string) {
  return value
    .split(/(?<=[.!?])\s+/)
    .map((sentence) => sentence.trim())
    .filter(Boolean);
}

function segmentDetails(segment: ActivitySegment): TimelineDetail[] {
  const rawDetails = segment.raw_excerpt
    .split(/\r?\n/)
    .map((line) => parseRawEventLine(line, segment.captured_from))
    .filter((detail): detail is TimelineDetail => Boolean(detail))
    .slice(0, 8);

  if (rawDetails.length) {
    return rawDetails;
  }

  return [
    {
      time: `${formatTimeWithSeconds(segment.captured_from)} - ${formatTimeWithSeconds(segment.captured_to)}`,
      text: segment.summary || segment.headline || "Activity captured",
    },
  ];
}

function rollupDetails(rollup: ActivityRollupItem): TimelineDetail[] {
  const intervalDetails = rollup.important_intervals
    .filter(Boolean)
    .slice(0, 5)
    .map((interval) => ({ time: "", text: interval }));

  if (intervalDetails.length) {
    return intervalDetails;
  }

  const sentenceDetails = splitSentences(rollup.summary)
    .slice(0, 3)
    .map((sentence) => ({ time: "", text: sentence }));

  if (sentenceDetails.length) {
    return sentenceDetails;
  }

  return [
    {
      time: "",
      text: rollup.headline || "Rollup is waiting for a finished LLM summary.",
    },
  ];
}

function segmentToTimelineItem(segment: ActivitySegment): TimelineCardItem {
  return {
    id: segment.window_id,
    level: "1m",
    start: segment.captured_from,
    end: segment.captured_to,
    durationMinutes: segment.duration_minutes,
    title: segment.headline || segment.activity_label || "Activity window",
    summary: segment.summary,
    project: segment.project || "General work",
    activityLabel: segment.activity_label || "Activity",
    focusLabel: segment.focus_label || "Steady",
    details: segmentDetails(segment),
    sourceCount: 1,
    confidence: segment.confidence,
    status: segment.status,
    modelName: segment.model_name,
    promptTokens: segment.prompt_tokens,
    completionTokens: segment.completion_tokens,
    totalTokens: segment.total_tokens,
    latencyMs: segment.latency_ms,
  };
}

function rollupToTimelineItem(rollup: ActivityRollupItem): TimelineCardItem {
  return {
    id: rollup.id,
    level: rollup.level as TimelineLevel,
    start: rollup.captured_from,
    end: rollup.captured_to,
    durationMinutes: rollup.duration_minutes,
    title: rollup.headline || rollup.activity_label || `${rollup.level} rollup`,
    summary: rollup.summary,
    project: rollup.project || "General work",
    activityLabel: rollup.activity_label || "Activity",
    focusLabel: rollup.focus_label || "Steady",
    details: rollupDetails(rollup),
    sourceCount: rollup.source_count,
    confidence: rollup.confidence,
    status: rollup.status,
    modelName: rollup.model_name,
    promptTokens: rollup.prompt_tokens,
    completionTokens: rollup.completion_tokens,
    totalTokens: rollup.total_tokens,
    latencyMs: rollup.latency_ms,
  };
}

function newestFirst<T extends { start: string }>(items: T[]) {
  return [...items].sort((left, right) => new Date(right.start).getTime() - new Date(left.start).getTime());
}

function countStatus(items: TimelineCardItem[], status: ActivityStatus) {
  return items.filter((item) => item.status === status).length;
}

function ongoingCount(column: TimelineColumn) {
  return column.queuedCount + column.processingCount + column.pendingCount;
}

function waitingCount(column: TimelineColumn) {
  return column.queuedCount + column.pendingCount;
}

function countLabel(count: number, singular: string, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`;
}

function compactWorkCount(column: TimelineColumn) {
  const waiting = waitingCount(column);
  if (waiting) {
    return `${column.processingCount}/${waiting}`;
  }
  if (column.processingCount) {
    return `${column.processingCount}/0`;
  }
  if (!ongoingCount(column)) {
    return "";
  }
  return "";
}

function compactWorkTitle(column: TimelineColumn) {
  const parts = [
    column.processingCount ? `${column.processingCount} processing` : "",
    column.queuedCount ? `${column.queuedCount} queued` : "",
    column.pendingCount ? `${column.pendingCount} pending` : "",
  ].filter(Boolean);
  return parts.length ? `LLM work: ${parts.join(", ")}` : "No queued LLM work";
}

function statusSummary(column: TimelineColumn) {
  const processedCount = countStatus(column.items, "processed");
  const violationCount = countStatus(column.items, "violation");
  const waiting = waitingCount(column);
  const parts = [
    processedCount ? countLabel(processedCount, "processed", "processed") : "",
    violationCount ? countLabel(violationCount, "flagged", "flagged") : "",
    column.processingCount ? countLabel(column.processingCount, "processing", "processing") : "",
    waiting ? countLabel(waiting, "queued", "queued") : "",
  ].filter(Boolean);
  if (!parts.length && column.items.length) {
    return `${column.items.length} captured`;
  }
  return parts.join(" · ");
}

function itemStatusLabel(status: ActivityStatus) {
  if (status === "processing") {
    return "LLM processing";
  }
  if (status === "queued") {
    return "LLM queued";
  }
  if (status === "pending_llm") {
    return "Needs retry";
  }
  if (status === "violation") {
    return "Flagged";
  }
  return "";
}

function isRollupEnabled(runtime: RuntimeSettingsResponse, level: RollupLevel) {
  if (level === "5m") {
    return runtime.rollup_5m_enabled;
  }
  if (level === "15m") {
    return runtime.rollup_15m_enabled;
  }
  if (level === "1h") {
    return runtime.rollup_1h_enabled;
  }
  if (level === "4h") {
    return runtime.rollup_4h_enabled;
  }
  if (level === "1d") {
    return runtime.rollup_1d_enabled;
  }
  return runtime.rollup_1w_enabled;
}

function confidenceLabel(value: number) {
  if (value >= 0.78) {
    return "High confidence";
  }
  if (value >= 0.52) {
    return "Medium confidence";
  }
  return "Low confidence";
}

function cardMinHeight(item: TimelineCardItem) {
  if (item.level === "1m") {
    return 178;
  }
  if (item.level === "5m") {
    return Math.min(255, 176 + item.sourceCount * 12);
  }
  if (item.level === "15m") {
    return Math.min(285, 196 + item.sourceCount * 10);
  }
  if (item.level === "1h") {
    return Math.min(315, 214 + Math.round(item.durationMinutes / 8));
  }
  if (item.level === "4h") {
    return Math.min(360, 236 + Math.round(item.durationMinutes / 12));
  }
  if (item.level === "1d") {
    return 320;
  }
  return 360;
}

type LazyTimelineLevel = "1m" | "5m" | "15m";

function usesLazyRendering(level: TimelineLevel): level is LazyTimelineLevel {
  return level === "1m" || level === "5m" || level === "15m";
}

function profileInitial(displayName: string) {
  return displayName.trim().charAt(0).toUpperCase() || "?";
}

function TimelineSidebar({ onSettingsClick, displayName }: { onSettingsClick?: () => void; displayName?: string }) {
  const profileName = displayName?.trim() || "You";
  const pathname = usePathname();
  return (
    <aside className="hierarchy-sidebar" aria-label="Workday Lens collapsed navigation">
      <Link href="/" className="hierarchy-sidebar__logo" aria-label="Go to Today" title="Workday Lens">
        <IconImage className="hierarchy-sidebar__logo-image" src={WORKDAY_LENS_LOGO_SRC} size={56} />
      </Link>
      <nav className="hierarchy-sidebar__nav">
        {TIMELINE_SIDEBAR_ITEMS.map((item) =>
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
          disabled={!onSettingsClick}
          aria-label="Open local settings"
          title="Settings"
          onClick={onSettingsClick}
        >
          <IconImage className="hierarchy-sidebar__icon" src={`${ICON_BASE}/settings.svg`} size={26} />
          <span>Settings</span>
        </button>
        <div className="hierarchy-sidebar__avatar" aria-label={profileName} title={profileName}>
          {profileInitial(profileName)}
        </div>
      </div>
    </aside>
  );
}

function isSidebarItemActive(href: string, pathname: string | null) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || Boolean(pathname?.startsWith(`${href}/`));
}

function TimelineCard({
  item,
  isLastColumn,
  selectedDay,
  showTokenDebug,
  onInspectLLM,
}: {
  item: TimelineCardItem;
  isLastColumn: boolean;
  selectedDay: string;
  showTokenDebug: boolean;
  onInspectLLM: (target: LLMDebugTarget) => void;
}) {
  const statusLabel = itemStatusLabel(item.status);
  const currentPeriodLabel = soFarLabel(item, selectedDay);
  const cardRange = formatCardRange(item, selectedDay);
  return (
    <article
      className={`hierarchy-card hierarchy-card--${item.level} ${isLastColumn ? "is-terminal" : ""}`}
      style={{ minHeight: cardMinHeight(item) }}
    >
      <div className="hierarchy-card__range">
        <span className="hierarchy-card__range-text">{cardRange}</span>
        {currentPeriodLabel && (
          <span className="hierarchy-card__so-far">
            <span className="hierarchy-card__so-far-dot" aria-hidden="true" />
            {currentPeriodLabel}
          </span>
        )}
      </div>
      {statusLabel && <div className={`hierarchy-card__status hierarchy-card__status--${item.status}`}>{statusLabel}</div>}
      <h3>{item.title}</h3>
      {item.summary && <p className="hierarchy-card__summary">{item.summary}</p>}
      <ol className="hierarchy-card__events">
        {item.details.map((detail, index) => (
          <li key={`${item.id}-${index}`}>
            {detail.time && <time>{detail.time}</time>}
            <span>{detail.text}</span>
          </li>
        ))}
      </ol>
      <div className="hierarchy-card__tags">
        <span>{item.project}</span>
        <span>{item.activityLabel}</span>
        <span>{item.focusLabel}</span>
      </div>
      <div className="hierarchy-card__meta">
        <span>{item.sourceCount === 1 ? "1 source" : `${item.sourceCount} sources`}</span>
        <span>{confidenceLabel(item.confidence)}</span>
        {item.modelName && <span>{item.modelName}</span>}
        {showTokenDebug && (
          <>
            <span title={`LLM input tokens: ${formatTokenCount(item.promptTokens)}`}>
              in {formatTokenCount(item.promptTokens)} tokens
            </span>
            <span title={`LLM output tokens: ${formatTokenCount(item.completionTokens)}`}>
              out {formatTokenCount(item.completionTokens)} tokens
            </span>
            <span title="LLM call duration">
              {formatLatency(item.latencyMs)}
            </span>
            <button
              type="button"
              className="hierarchy-card__debug-button"
              aria-label="Inspect LLM prompt and response"
              title="Inspect LLM prompt and response"
              onClick={() => onInspectLLM({ id: item.id, level: item.level, title: item.title, range: cardRange })}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
                <path d="M4.2 5.4h11.6M4.2 10h11.6M4.2 14.6h7.4" />
                <circle cx="15.2" cy="14.6" r="1.4" />
              </svg>
            </button>
          </>
        )}
      </div>
    </article>
  );
}

function LLMDebugModal({
  target,
  trace,
  loading,
  error,
  onClose,
}: {
  target: LLMDebugTarget;
  trace?: ActivityLLMDebugResponse;
  loading: boolean;
  error: Error | null;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState<"prompt" | "response" | null>(null);

  useEffect(() => {
    setCopied(null);
  }, [target.id, target.level]);

  async function copyText(kind: "prompt" | "response", text: string) {
    if (!text) {
      return;
    }
    await navigator.clipboard.writeText(text);
    setCopied(kind);
    window.setTimeout(() => setCopied(null), 1200);
  }

  const promptText = trace?.prompt_text ?? "";
  const responseText = trace?.response_text ?? "";

  return (
    <div className="hierarchy-debug-modal" role="dialog" aria-modal="true" aria-label="LLM prompt inspector">
      <button type="button" className="hierarchy-debug-modal__backdrop" aria-label="Close LLM inspector" onClick={onClose} />
      <div className="hierarchy-debug-modal__panel">
        <header className="hierarchy-debug-modal__header">
          <div>
            <span className="hierarchy-debug-modal__eyebrow">{target.level} LLM trace</span>
            <h2>{target.title}</h2>
            <p>{target.range}</p>
          </div>
          <button type="button" className="hierarchy-debug-modal__close" aria-label="Close LLM inspector" onClick={onClose}>
            <svg viewBox="0 0 20 20" aria-hidden="true" focusable="false">
              <path d="M5.8 5.8l8.4 8.4M14.2 5.8l-8.4 8.4" />
            </svg>
          </button>
        </header>
        {trace && (
          <div className="hierarchy-debug-modal__meta">
            <span>{trace.model_name || "model unavailable"}</span>
            <span>in {formatTokenCount(trace.prompt_tokens)} tokens</span>
            <span>out {formatTokenCount(trace.completion_tokens)} tokens</span>
            <span>{formatLatency(trace.latency_ms)}</span>
          </div>
        )}
        {trace?.notes.length ? (
          <div className="hierarchy-debug-modal__notes">
            {trace.notes.map((note) => (
              <span key={note}>{note}</span>
            ))}
          </div>
        ) : null}
        {error && <div className="hierarchy-debug-modal__error">{error.message}</div>}
        <div className="hierarchy-debug-modal__grid">
          <section className="hierarchy-debug-modal__section">
            <header>
              <h3>Prompt</h3>
              <button type="button" disabled={!promptText} onClick={() => copyText("prompt", promptText)}>
                {copied === "prompt" ? "Copied" : "Copy"}
              </button>
            </header>
            <pre>{loading ? "Loading reconstructed prompt..." : promptText || "No prompt text available."}</pre>
          </section>
          <section className="hierarchy-debug-modal__section">
            <header>
              <h3>Response</h3>
              <button type="button" disabled={!responseText} onClick={() => copyText("response", responseText)}>
                {copied === "response" ? "Copied" : "Copy"}
              </button>
            </header>
            <pre>{loading ? "Loading stored response..." : responseText || "No stored response available."}</pre>
          </section>
        </div>
      </div>
    </div>
  );
}

function TimelineColumnView({
  column,
  isLastColumn,
  selectedDay,
  onReprocess,
  reprocessing,
  notice,
  visibleLimit,
  onLoadMore,
  showTokenDebug,
  onInspectLLM,
}: {
  column: TimelineColumn;
  isLastColumn: boolean;
  selectedDay: string;
  onReprocess: (level: TimelineLevel) => void;
  reprocessing: boolean;
  notice?: string;
  visibleLimit?: number;
  onLoadMore?: () => void;
  showTokenDebug: boolean;
  onInspectLLM: (target: LLMDebugTarget) => void;
}) {
  const workCount = compactWorkCount(column);
  const workTitle = compactWorkTitle(column);
  const visibleItems =
    typeof visibleLimit === "number" ? column.items.slice(0, Math.max(0, visibleLimit)) : column.items;
  const hiddenItemCount = Math.max(0, column.items.length - visibleItems.length);
  const summaryText = showTokenDebug ? statusSummary(column) : "";
  const isProcessing = column.processingCount > 0;
  const hasWaitingWork = waitingCount(column) > 0;
  const loadMoreRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!onLoadMore || hiddenItemCount <= 0) {
      return;
    }
    const node = loadMoreRef.current;
    if (!node) {
      return;
    }
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          onLoadMore();
        }
      },
      { rootMargin: "360px 0px" },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [hiddenItemCount, onLoadMore]);

  return (
    <section className={`hierarchy-column hierarchy-column--${column.level}`} aria-label={column.title}>
      <header className="hierarchy-column__header">
        <IconImage className="hierarchy-column__icon" src={column.iconSrc} size={28} />
        <div className="hierarchy-column__title">
          <div className="hierarchy-column__copy">
            <h2>{column.title}</h2>
            <span className="hierarchy-column__subtitle">{column.subtitle}</span>
          </div>
          <div className="hierarchy-column__controls">
            {workCount && (
              <span
                className={`hierarchy-column__work-count ${isProcessing ? "is-processing" : hasWaitingWork ? "is-waiting" : ""}`}
                title={workTitle}
                aria-label={workTitle}
              >
                {(isProcessing || hasWaitingWork) && <span className="hierarchy-column__live-dot" aria-hidden="true" />}
                {workCount}
              </span>
            )}
            <button
              type="button"
              className={`hierarchy-column__action ${reprocessing ? "is-reprocessing" : ""}`}
              aria-label={`Reprocess ${column.title} with the LLM`}
              title="Reprocess this column with the LLM"
              disabled={Boolean(column.disabled) || reprocessing}
              onClick={() => onReprocess(column.level)}
            >
              <IconImage className="hierarchy-column__action-icon" src={REFRESH_ICON_SRC} size={19} />
            </button>
          </div>
        </div>
        {(summaryText || notice || reprocessing) && (
          <div className={`hierarchy-column__work ${ongoingCount(column) > 0 || reprocessing ? "is-active" : ""}`}>
            {reprocessing ? "Queueing LLM work..." : notice || summaryText}
          </div>
        )}
      </header>

      <div className="hierarchy-column__body">
        {column.disabled ? (
          <div className="hierarchy-empty-card">
            <strong>{column.title} rollups are disabled</strong>
            <span>Enable this level in local settings when you want these LLM calls.</span>
          </div>
        ) : column.error ? (
          <div className="hierarchy-empty-card">
            <strong>Could not load {column.title}</strong>
            <span>The local activity API did not return this timeline level.</span>
          </div>
        ) : column.loading && column.items.length === 0 ? (
          <>
            <div className="hierarchy-skeleton-card" />
            <div className="hierarchy-skeleton-card" />
            <div className="hierarchy-skeleton-card" />
          </>
        ) : column.items.length === 0 ? (
          <div className="hierarchy-empty-card">
            <strong>No {column.title} activity yet</strong>
            <span>{column.emptyText}</span>
          </div>
        ) : (
          <>
            {visibleItems.map((item) => (
              <TimelineCard
                key={item.id}
                item={item}
                isLastColumn={isLastColumn}
                selectedDay={selectedDay}
                showTokenDebug={showTokenDebug}
                onInspectLLM={onInspectLLM}
              />
            ))}
            {hiddenItemCount > 0 && (
              <div ref={loadMoreRef} className="hierarchy-load-more" aria-live="polite">
                <span>Loading more activity</span>
                <strong>
                  Showing {visibleItems.length} of {column.items.length}
                </strong>
              </div>
            )}
          </>
        )}
      </div>
    </section>
  );
}

export function HierarchicalTimeline() {
  const [selectedDay, setSelectedDay] = useState(initialDayValue);
  const [showSettings, setShowSettings] = useState(false);
  const [reprocessingLevel, setReprocessingLevel] = useState<TimelineLevel | null>(null);
  const [columnNotices, setColumnNotices] = useState<Partial<Record<TimelineLevel, string>>>({});
  const [visibleTimelineCounts, setVisibleTimelineCounts] = useState<Record<LazyTimelineLevel, number>>({
    "1m": INITIAL_TIMELINE_CARD_LIMIT,
    "5m": INITIAL_TIMELINE_CARD_LIMIT,
    "15m": INITIAL_TIMELINE_CARD_LIMIT,
  });
  const [showTimelineDebug] = useState(() => initialTimelineDebugEnabled());
  const [llmDebugTarget, setLlmDebugTarget] = useState<LLMDebugTarget | null>(null);
  const dateInputRef = useRef<HTMLInputElement | null>(null);
  const today = todayDateValue();
  const canMoveForward = selectedDay < today;
  const selectedDayRange = useMemo(() => dayRange(selectedDay), [selectedDay]);
  const selectedWeekRange = useMemo(() => weekRange(selectedDay), [selectedDay]);
  const dayStartIso = selectedDayRange.start.toISOString();
  const dayEndIso = selectedDayRange.end.toISOString();
  const weekStartIso = selectedWeekRange.start.toISOString();
  const weekEndIso = selectedWeekRange.end.toISOString();
  const shouldPoll = selectedDay === today;

  function openDatePicker() {
    const input = dateInputRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    if (!input) {
      return;
    }
    if (typeof input.showPicker === "function") {
      input.showPicker();
    } else {
      input.focus();
      input.click();
    }
  }

  const setupQuery = useQuery({
    queryKey: ["setup-status"],
    queryFn: fetchSetupStatus,
    staleTime: 30_000,
  });

  const setup = setupQuery.data;
  const ready = Boolean(setup && !setup.needs_setup);
  const runtime = setup?.runtime_settings;

  const dashboardQuery = useQuery({
    queryKey: ["activity-dashboard", selectedDay],
    queryFn: () => fetchActivityDashboard(selectedDay),
    enabled: ready,
    refetchInterval: shouldPoll ? TIMELINE_POLL_INTERVAL : false,
    staleTime: 20_000,
  });

  const fiveMinuteQuery = useQuery({
    queryKey: ["activity-rollups", "5m", dayStartIso, dayEndIso],
    queryFn: () => fetchActivityRollupsRange("5m", dayStartIso, dayEndIso),
    enabled: Boolean(ready && runtime && isRollupEnabled(runtime, "5m")),
    refetchInterval: shouldPoll ? TIMELINE_POLL_INTERVAL : false,
    staleTime: 20_000,
  });

  const fifteenMinuteQuery = useQuery({
    queryKey: ["activity-rollups", "15m", dayStartIso, dayEndIso],
    queryFn: () => fetchActivityRollupsRange("15m", dayStartIso, dayEndIso),
    enabled: Boolean(ready && runtime && isRollupEnabled(runtime, "15m")),
    refetchInterval: shouldPoll ? TIMELINE_POLL_INTERVAL : false,
    staleTime: 20_000,
  });

  const hourQuery = useQuery({
    queryKey: ["activity-rollups", "1h", dayStartIso, dayEndIso],
    queryFn: () => fetchActivityRollupsRange("1h", dayStartIso, dayEndIso),
    enabled: Boolean(ready && runtime && isRollupEnabled(runtime, "1h")),
    refetchInterval: shouldPoll ? TIMELINE_POLL_INTERVAL : false,
    staleTime: 20_000,
  });

  const fourHourQuery = useQuery({
    queryKey: ["activity-rollups", "4h", dayStartIso, dayEndIso],
    queryFn: () => fetchActivityRollupsRange("4h", dayStartIso, dayEndIso),
    enabled: Boolean(ready && runtime && isRollupEnabled(runtime, "4h")),
    refetchInterval: shouldPoll ? TIMELINE_POLL_INTERVAL : false,
    staleTime: 20_000,
  });

  const dayQuery = useQuery({
    queryKey: ["activity-rollups", "1d", dayStartIso, dayEndIso],
    queryFn: () => fetchActivityRollupsRange("1d", dayStartIso, dayEndIso),
    enabled: Boolean(ready && runtime && isRollupEnabled(runtime, "1d")),
    refetchInterval: shouldPoll ? TIMELINE_POLL_INTERVAL : false,
    staleTime: 60_000,
  });

  const weekQuery = useQuery({
    queryKey: ["activity-rollups", "1w", weekStartIso, weekEndIso],
    queryFn: () => fetchActivityRollupsRange("1w", weekStartIso, weekEndIso),
    enabled: Boolean(ready && runtime && isRollupEnabled(runtime, "1w")),
    refetchInterval: shouldPoll ? TIMELINE_POLL_INTERVAL : false,
    staleTime: 60_000,
  });

  const llmDebugQuery = useQuery({
    queryKey: ["activity-llm-debug", llmDebugTarget?.level, llmDebugTarget?.id],
    queryFn: () => {
      if (!llmDebugTarget) {
        throw new Error("No LLM debug target selected.");
      }
      return fetchActivityLLMDebug(llmDebugTarget.level, llmDebugTarget.id);
    },
    enabled: Boolean(showTimelineDebug && llmDebugTarget),
    staleTime: 0,
    gcTime: 30_000,
  });

  const columns = useMemo<TimelineColumn[]>(() => {
    const segments = dashboardQuery.data?.segments ?? [];
    const rollupItems = {
      "5m": fiveMinuteQuery.data?.data ?? [],
      "15m": fifteenMinuteQuery.data?.data ?? [],
      "1h": hourQuery.data?.data ?? [],
      "4h": fourHourQuery.data?.data ?? [],
      "1d": dayQuery.data?.data ?? [],
      "1w": weekQuery.data?.data ?? [],
    } satisfies Record<RollupLevel, ActivityRollupItem[]>;

    const queryState = {
      "5m": fiveMinuteQuery,
      "15m": fifteenMinuteQuery,
      "1h": hourQuery,
      "4h": fourHourQuery,
      "1d": dayQuery,
      "1w": weekQuery,
    };

    return TIMELINE_LEVELS.map((definition) => {
      if (definition.level === "1m") {
        const items = newestFirst(segments.map(segmentToTimelineItem));
        return {
          ...definition,
          items,
          loading: dashboardQuery.isLoading,
          error: dashboardQuery.isError,
          emptyText: "Raw one-minute windows will appear here once macOS activity is captured and analyzed.",
          queuedCount: countStatus(items, "queued"),
          processingCount: countStatus(items, "processing"),
          pendingCount: countStatus(items, "pending_llm"),
        };
      }

      const level = definition.level;
      const enabled = Boolean(runtime && isRollupEnabled(runtime, level));
      const query = queryState[level];
      const items = newestFirst(rollupItems[level].map(rollupToTimelineItem));
      return {
        ...definition,
        items,
        loading: query.isLoading,
        error: query.isError,
        disabled: Boolean(runtime && !enabled),
        emptyText: `${definition.title} summaries will appear here after that hierarchy level has completed.`,
        queuedCount: countStatus(items, "queued"),
        processingCount: countStatus(items, "processing"),
        pendingCount: countStatus(items, "pending_llm"),
      };
    });
  }, [
    dashboardQuery.data?.segments,
    dashboardQuery.isError,
    dashboardQuery.isLoading,
    dayQuery,
    fifteenMinuteQuery,
    fiveMinuteQuery,
    fourHourQuery,
    hourQuery,
    runtime,
    weekQuery,
  ]);
  const oneMinuteItemCount = columns.find((column) => column.level === "1m")?.items.length ?? 0;
  const fiveMinuteItemCount = columns.find((column) => column.level === "5m")?.items.length ?? 0;
  const fifteenMinuteItemCount = columns.find((column) => column.level === "15m")?.items.length ?? 0;
  const lazyTimelineItemCounts = useMemo<Record<LazyTimelineLevel, number>>(
    () => ({
      "1m": oneMinuteItemCount,
      "5m": fiveMinuteItemCount,
      "15m": fifteenMinuteItemCount,
    }),
    [fifteenMinuteItemCount, fiveMinuteItemCount, oneMinuteItemCount],
  );

  useEffect(() => {
    setVisibleTimelineCounts({
      "1m": INITIAL_TIMELINE_CARD_LIMIT,
      "5m": INITIAL_TIMELINE_CARD_LIMIT,
      "15m": INITIAL_TIMELINE_CARD_LIMIT,
    });
  }, [selectedDay]);

  const loadMoreTimelineCards = useCallback((level: LazyTimelineLevel) => {
    setVisibleTimelineCounts((current) => ({
      ...current,
      [level]: Math.min(
        current[level] + TIMELINE_CARD_BATCH_SIZE,
        Math.max(lazyTimelineItemCounts[level], INITIAL_TIMELINE_CARD_LIMIT),
      ),
    }));
  }, [lazyTimelineItemCounts]);

  const handleLoadMoreTimelineCards = useCallback((level: TimelineLevel) => {
    if (usesLazyRendering(level)) {
      loadMoreTimelineCards(level);
    }
  }, [loadMoreTimelineCards]);

  async function refreshSetupAndTimeline() {
    await setupQuery.refetch();
    await dashboardQuery.refetch();
    await Promise.all([
      fiveMinuteQuery.refetch(),
      fifteenMinuteQuery.refetch(),
      hourQuery.refetch(),
      fourHourQuery.refetch(),
      dayQuery.refetch(),
      weekQuery.refetch(),
    ]);
  }

  async function refetchColumn(level: TimelineLevel) {
    if (level === "1m") {
      await dashboardQuery.refetch();
    } else if (level === "5m") {
      await fiveMinuteQuery.refetch();
    } else if (level === "15m") {
      await fifteenMinuteQuery.refetch();
    } else if (level === "1h") {
      await hourQuery.refetch();
    } else if (level === "4h") {
      await fourHourQuery.refetch();
    } else if (level === "1d") {
      await dayQuery.refetch();
    } else {
      await weekQuery.refetch();
    }
  }

  function reprocessRange(level: TimelineLevel) {
    if (level === "1w") {
      return selectedWeekRange;
    }
    return selectedDayRange;
  }

  function reprocessRangeLabel(level: TimelineLevel) {
    if (level === "1w") {
      const end = dateFromDayValue(selectedDay);
      return `${WEEK_RANGE_FORMATTER.format(selectedWeekRange.start)} - ${WEEK_RANGE_FORMATTER.format(end)}`;
    }
    return formatDatePickerLabel(selectedDay);
  }

  async function handleColumnReprocess(level: TimelineLevel) {
    const column = columns.find((item) => item.level === level);
    if (!column || column.disabled || reprocessingLevel) {
      return;
    }
    const range = reprocessRange(level);
    const visibleCount = column.items.length;
    const targetLabel = level === "1m" ? "raw activity windows" : `${column.title} rollups`;
    const itemEstimate = visibleCount
      ? `${visibleCount} visible ${visibleCount === 1 ? "item" : "items"}`
      : "ready items in this column";
    const confirmed = window.confirm(
      `Reprocess ${targetLabel} for ${reprocessRangeLabel(level)}?\n\n` +
        `This can queue paid LLM calls for ${itemEstimate}. Continue?`,
    );
    if (!confirmed) {
      return;
    }
    setReprocessingLevel(level);
    setColumnNotices((current) => ({ ...current, [level]: "Queueing LLM work..." }));
    try {
      const result = await reprocessActivityRange(level, range.start.toISOString(), range.end.toISOString(), "all");
      const queued = result.queued_windows + result.queued_rollups;
      const invalidated = result.invalidated_rollups;
      setColumnNotices((current) => ({
        ...current,
        [level]: queued
          ? `${queued} LLM ${queued === 1 ? "call" : "calls"} queued${invalidated ? `; ${invalidated} parent summaries reset` : ""}.`
          : "No ready items were queued.",
      }));
      await refetchColumn(level);
    } catch (error) {
      setColumnNotices((current) => ({
        ...current,
        [level]: error instanceof Error ? error.message : "Could not queue LLM work.",
      }));
    } finally {
      setReprocessingLevel(null);
    }
  }

  if (setupQuery.isLoading) {
    return (
      <div className="hierarchy-timeline">
        <TimelineSidebar />
        <main className="hierarchy-main">
          <div className="hierarchy-page-message">Checking local setup for Timeline.</div>
        </main>
      </div>
    );
  }

  if (setupQuery.isError || !setup) {
    return (
      <div className="hierarchy-timeline">
        <TimelineSidebar />
        <main className="hierarchy-main">
          <div className="hierarchy-page-message is-error">The app could not read local setup status from the local API.</div>
        </main>
      </div>
    );
  }

  if (setup.needs_setup) {
    return <SetupPanel setup={setup} onSaved={refreshSetupAndTimeline} mode="setup" />;
  }

  return (
    <div className="hierarchy-timeline">
      {showSettings && (
        <div className="lens-settings-layer">
          <SetupPanel
            setup={setup}
            onSaved={refreshSetupAndTimeline}
            mode="manage"
            onClose={() => setShowSettings(false)}
          />
        </div>
      )}

      <TimelineSidebar onSettingsClick={() => setShowSettings(true)} displayName={setup.runtime_settings.display_name} />

      <main className="hierarchy-main">
        <header className="hierarchy-hero">
          <Image
            className="hierarchy-hero__art"
            src={TIMELINE_HERO_ART_SRC}
            alt=""
            width={1180}
            height={394}
            aria-hidden="true"
            unoptimized
          />
          <div className="hierarchy-hero__copy">
            <h1>Timeline</h1>
            <p>Hierarchical rollups from raw activity</p>
          </div>
          <div className="hierarchy-toolbar">
            <div className="hierarchy-date-control">
              <button type="button" aria-label="Previous day" onClick={() => setSelectedDay((current) => shiftDayValue(current, -1))}>
                <span aria-hidden="true">{"<"}</span>
              </button>
              <button
                type="button"
                className="hierarchy-date-control__picker"
                aria-label={`Choose timeline day. Current selection is ${formatDatePickerLabel(selectedDay)}`}
                onClick={openDatePicker}
              >
                <span className="hierarchy-calendar-icon" aria-hidden="true" />
                {formatDatePickerLabel(selectedDay)}
              </button>
              <button
                type="button"
                aria-label="Next day"
                onClick={() => setSelectedDay((current) => shiftDayValue(current, 1))}
                disabled={!canMoveForward}
              >
                <span aria-hidden="true">{">"}</span>
              </button>
              <input
                ref={dateInputRef}
                className="hierarchy-date-control__native"
                type="date"
                value={selectedDay}
                max={today}
                onChange={(event) => setSelectedDay(event.target.value)}
                aria-label="Timeline date"
              />
            </div>
            <button type="button" className="hierarchy-filter-button">
              Filters
            </button>
          </div>
        </header>

        <section className="hierarchy-board" aria-label="Hierarchical activity timeline">
          {columns.map((column, index) => (
            <TimelineColumnView
              key={column.level}
              column={column}
              isLastColumn={index === columns.length - 1}
              selectedDay={selectedDay}
              onReprocess={handleColumnReprocess}
              reprocessing={reprocessingLevel === column.level}
              notice={columnNotices[column.level]}
              visibleLimit={usesLazyRendering(column.level) ? visibleTimelineCounts[column.level] : undefined}
              onLoadMore={usesLazyRendering(column.level) ? () => handleLoadMoreTimelineCards(column.level) : undefined}
              showTokenDebug={showTimelineDebug}
              onInspectLLM={setLlmDebugTarget}
            />
          ))}
        </section>
        {showTimelineDebug && llmDebugTarget && (
          <LLMDebugModal
            target={llmDebugTarget}
            trace={llmDebugQuery.data}
            loading={llmDebugQuery.isFetching}
            error={llmDebugQuery.error instanceof Error ? llmDebugQuery.error : null}
            onClose={() => setLlmDebugTarget(null)}
          />
        )}
      </main>
    </div>
  );
}
