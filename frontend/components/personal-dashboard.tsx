"use client";

import { DEMO_MODE, initialDayValue } from "../lib/config";

import Image from "next/image";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { useQueries, useQuery } from "@tanstack/react-query";

import { SetupPanel } from "./setup-panel";
import {
  ActivityGanttBlock,
  RuntimeSettingsResponse,
  fetchActivityDashboard,
  fetchActivityGantt,
  fetchActivityRollupsRange,
  fetchSetupStatus,
} from "../lib/api";
import { DEFAULT_POLL_INTERVAL } from "../lib/config";

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

const WEEK_TICK_FORMATTER = new Intl.DateTimeFormat("en-US", {
  weekday: "short",
  month: "short",
  day: "numeric",
});

type GranularityValue = "week" | "day" | "4h" | "1h";
type TimelineLaneId = "deep" | "meetings" | "comms" | "breaks";

interface TimelineSource {
  id: string;
  captured_from: string;
  captured_to: string;
  duration_minutes: number;
  headline: string;
  summary: string;
  project: string;
  activity_type: string;
  activity_label: string;
  focus_state: string;
  focus_label: string;
  dominant_goal: string;
  ignored_noise?: string | null;
  confidence: number;
  lane?: TimelineLaneId;
  source_level?: string;
  is_marker?: boolean;
  is_gap?: boolean;
  evidence?: string;
}

interface GanttLoadingCopy {
  title: string;
  detail: string;
}

interface RollupStatusSummary {
  checking: boolean;
  queued: number;
  processing: number;
  pending: number;
  completed: number;
  total: number;
}

const GRANULARITY_STORAGE_KEY = "workday-lens-summary-granularity";
const ICON_BASE = "/workday-lens-icons";
const WORKDAY_LENS_LOGO_SRC = `${ICON_BASE}/workday-lens-logo-main.png`;
const EMPTY_GANTT_BLOCKS: ActivityGanttBlock[] = [];

const GRANULARITY_OPTIONS: Array<{ value: GranularityValue; label: string }> = [
  { value: "week", label: "Week" },
  { value: "day", label: "Day" },
  { value: "4h", label: "4h" },
  { value: "1h", label: "1h" },
];

const GANTT_REQUIRED_LEVELS: Record<GranularityValue, string[]> = {
  week: ["1d", "4h", "1h", "15m"],
  day: ["4h", "1h", "15m", "5m"],
  "4h": ["1h", "15m", "5m"],
  "1h": ["15m", "5m"],
};

const TIMELINE_LANES: Array<{ id: TimelineLaneId; label: string; iconSrc: string }> = [
  { id: "deep", label: "Deep Work", iconSrc: `${ICON_BASE}/deep-work.svg` },
  { id: "meetings", label: "Meetings", iconSrc: `${ICON_BASE}/meetings.svg` },
  { id: "comms", label: "Comms", iconSrc: `${ICON_BASE}/comms.svg` },
  { id: "breaks", label: "Breaks", iconSrc: `${ICON_BASE}/breaks.svg` },
];

const GANTT_VISUAL_TONES = ["base", "warm", "peach", "amber", "soft"] as const;

const SIDEBAR_ITEMS = [
  { label: "Timeline", href: "/timeline", iconSrc: `${ICON_BASE}/sidebar-timeline.svg` },
  { label: "Resources", href: "/resources", iconSrc: `${ICON_BASE}/focus-time-badge.svg` },
  { label: "Projects", iconSrc: `${ICON_BASE}/sidebar-projects.svg` },
  { label: "Insights", iconSrc: `${ICON_BASE}/sidebar-insights.svg` },
  { label: "Learnings", iconSrc: `${ICON_BASE}/sidebar-learnings.svg` },
];

const MEETING_KEYWORDS = [
  "standup meeting",
  "standup call",
  "video call",
  "voice call",
  "zoom",
  "teams meeting",
  "microsoft teams meeting",
  "teams call",
  "google meet",
  "meet.google",
  "slack huddle",
  "discord voice",
  "calendar invite",
  "attendee",
  "1:1",
  "one-on-one",
];

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

function profileInitial(displayName: string) {
  return displayName.trim().charAt(0).toUpperCase() || "?";
}

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

function formatDatePickerLabel(day: string) {
  return CONTROL_DATE_FORMATTER.format(dateFromDayValue(day));
}

function formatViewRange(start: Date, end: Date, mode: GranularityValue) {
  if (mode === "week") {
    return `${SHORT_DATE_FORMATTER.format(start)} - ${SHORT_DATE_FORMATTER.format(addDays(end, -1))}`;
  }
  return CONTROL_DATE_FORMATTER.format(start);
}

function formatTime(value: string) {
  return TIME_FORMATTER.format(new Date(value));
}

function clampPercent(value: number) {
  return Math.max(0, Math.min(100, value));
}

function isGranularityValue(value: string | null): value is GranularityValue {
  return GRANULARITY_OPTIONS.some((option) => option.value === value);
}

function savedGranularityValue(): GranularityValue {
  if (typeof window === "undefined") {
    return "day";
  }
  try {
    const saved = window.localStorage.getItem(GRANULARITY_STORAGE_KEY);
    return isGranularityValue(saved) ? saved : "day";
  } catch {
    return "day";
  }
}

function isRollupEnabled(runtime: RuntimeSettingsResponse, level: string) {
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
  if (level === "1w") {
    return runtime.rollup_1w_enabled;
  }
  return false;
}

function isGanttEnabled(runtime: RuntimeSettingsResponse, mode: GranularityValue) {
  return GANTT_REQUIRED_LEVELS[mode].every((level) => isRollupEnabled(runtime, level));
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

function rangeForGranularity(day: string, mode: GranularityValue, hour: number, fourHour: number) {
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

function durationMinutes(from: string, to: string) {
  return Math.max(1, Math.round((new Date(to).getTime() - new Date(from).getTime()) / 60000));
}

function ganttBlockToSource(block: ActivityGanttBlock): TimelineSource {
  const lane = TIMELINE_LANES.some((item) => item.id === block.lane) ? (block.lane as TimelineLaneId) : "deep";
  return {
    id: block.id,
    captured_from: block.captured_from,
    captured_to: block.captured_to,
    duration_minutes: block.is_gap ? 0 : durationMinutes(block.captured_from, block.captured_to),
    headline: block.label,
    summary: block.summary,
    project: block.project,
    activity_type: block.activity_type,
    activity_label: block.source_level,
    focus_state: block.focus_state,
    focus_label: block.source_level,
    dominant_goal: block.reason,
    ignored_noise: block.is_marker ? block.reason : null,
    confidence: Math.min(1, Math.max(0, block.priority_score / 100)),
    lane,
    source_level: block.source_level,
    is_marker: block.is_marker,
    is_gap: block.is_gap,
    evidence: block.evidence,
  };
}

function isMeetingLike(item: TimelineSource) {
  if (!["communication", "admin", "review"].includes(item.activity_type)) {
    return false;
  }
  const haystack = `${item.headline} ${item.summary} ${item.project} ${item.dominant_goal}`.toLowerCase();
  return MEETING_KEYWORDS.some((keyword) => haystack.includes(keyword));
}

function laneForSource(item: TimelineSource): TimelineLaneId {
  if (item.lane) {
    return item.lane;
  }
  if (item.activity_type === "break" || item.activity_type === "offline" || item.activity_type === "other") {
    return "breaks";
  }
  if (isMeetingLike(item)) {
    return "meetings";
  }
  if (item.activity_type === "communication" || item.activity_type === "admin") {
    return "comms";
  }
  return "deep";
}

function buildMetrics(items: TimelineSource[]) {
  return items.reduce(
    (totals, item) => {
      const lane = laneForSource(item);
      totals[lane] += item.duration_minutes;
      return totals;
    },
    {
      deep: 0,
      meetings: 0,
      comms: 0,
      breaks: 0,
    },
  );
}

function dominantProject(items: TimelineSource[]) {
  const projectMinutes = new Map<string, number>();
  for (const item of items) {
    const project = item.project || "General work";
    projectMinutes.set(project, (projectMinutes.get(project) ?? 0) + item.duration_minutes);
  }
  return [...projectMinutes.entries()].sort((left, right) => right[1] - left[1])[0]?.[0] ?? "No project detected yet";
}

function strongestItem(items: TimelineSource[], lane?: TimelineLaneId) {
  const candidates = lane ? items.filter((item) => laneForSource(item) === lane) : items;
  return [...candidates].sort((left, right) => right.duration_minutes - left.duration_minutes)[0] ?? null;
}

function ticksForBounds(start: Date, end: Date, mode: GranularityValue) {
  const ticks: Date[] = [];
  if (mode === "week") {
    for (let index = 0; index <= 7; index += 1) {
      ticks.push(addDays(start, index));
    }
    return ticks;
  }

  const stepMinutes = mode === "1h" ? 15 : mode === "day" ? 240 : 60;
  const cursor = new Date(start);
  cursor.setSeconds(0, 0);
  while (cursor.getTime() <= end.getTime()) {
    ticks.push(new Date(cursor));
    cursor.setMinutes(cursor.getMinutes() + stepMinutes);
  }
  return ticks;
}

function formatTick(tick: Date, mode: GranularityValue) {
  if (mode === "week") {
    return WEEK_TICK_FORMATTER.format(tick);
  }
  if (mode === "1h") {
    return TIME_FORMATTER.format(tick);
  }
  return TIME_FORMATTER.format(tick).replace(":00", "");
}

function sourceRangeLabel(item: TimelineSource) {
  return `${formatTime(item.captured_from)} - ${formatTime(item.captured_to)}`;
}

function blockRangeLabel(block: ActivityGanttBlock) {
  return `${formatTime(block.captured_from)} - ${formatTime(block.captured_to)}`;
}

function storyTextToPoints(text: string) {
  const normalized = text.replace(/\s+/g, " ").trim();
  if (!normalized) {
    return [];
  }

  const chunks = normalized
    .split(/(?<=[.!?])\s+/)
    .flatMap((sentence) => sentence.split(/\s*;\s*/))
    .flatMap((chunk) => {
      if (chunk.length < 150) {
        return [chunk];
      }
      return chunk.split(/\s+and then\s+|,\s+(?=with\b|while\b|then\b|later\b|by the\b|after\b|before\b)/i);
    })
    .map((chunk) => chunk.trim().replace(/[.;,\s]+$/, ""))
    .filter(Boolean);

  if (chunks.length <= 5) {
    return chunks;
  }

  return [...chunks.slice(0, 4), chunks.slice(4).join("; ")];
}

function ganttVisualTone(block: ActivityGanttBlock) {
  if (block.is_gap) {
    return "neutral";
  }
  return GANTT_VISUAL_TONES.includes(block.visual_tone as (typeof GANTT_VISUAL_TONES)[number])
    ? block.visual_tone
    : "base";
}

function clampSourceToNow(item: TimelineSource, nowMs: number) {
  const fromMs = Date.parse(item.captured_from);
  const toMs = Date.parse(item.captured_to);
  if (!Number.isFinite(fromMs) || !Number.isFinite(toMs)) {
    return item;
  }
  if (fromMs >= nowMs) {
    return null;
  }
  if (toMs <= nowMs) {
    return item;
  }
  const durationMinutes = Math.max(1, Math.ceil((nowMs - fromMs) / 60000));
  return {
    ...item,
    captured_to: new Date(nowMs).toISOString(),
    duration_minutes: Math.min(item.duration_minutes, durationMinutes),
  };
}

function storyForView(
  selectedDay: string,
  selectedGranularity: GranularityValue,
  rangeStart: Date,
  rangeEnd: Date,
  items: TimelineSource[],
  dashboardStory?: { headline?: string | null; summary?: string | null },
) {
  const focus = strongestItem(items, "deep");
  const interruption = items.find((item) => item.ignored_noise)?.ignored_noise ?? null;
  const strongest = focus ?? strongestItem(items);
  const period = selectedGranularity === "week" ? "week" : "day";
  const title = selectedGranularity === "week" ? "This Week's Story" : "Today's Story";

  if (!items.length) {
    return {
      title,
      subtitle: `${formatDatePickerLabel(selectedDay)} - ${DEMO_MODE ? "fictional sample day" : "auto-captured by Workday Lens"}`,
      lines: [
        "Workday Lens is waiting for the required hierarchy summaries in this view.",
        "As activity is processed, the story will describe intent, focus, interruptions, and recovery.",
      ],
      interruption: "No dominant interruption detected yet.",
    };
  }

  if (selectedGranularity === "day" && dashboardStory?.summary) {
    return {
      title,
      subtitle: `${formatDatePickerLabel(selectedDay)} - ${DEMO_MODE ? "fictional sample day" : "auto-captured by Workday Lens"}`,
      lines: storyTextToPoints(dashboardStory.summary),
      interruption: interruption ?? "No dominant interruption detected yet.",
    };
  }

  return {
    title,
    subtitle: `${formatViewRange(rangeStart, rangeEnd, selectedGranularity)} - hierarchy summary`,
    lines: [
      strongest
        ? `Most of this ${period} centered on ${strongest.project || "the main workstream"}.`
        : `This ${period} is still forming.`,
      focus
        ? `The strongest focus stretch was ${sourceRangeLabel(focus)}: ${focus.headline}.`
        : "No sustained deep work block has become dominant in this view yet.",
      interruption ? `The main low-signal activity was ${interruption}.` : "Small context switches are being folded into the dominant workstream.",
    ],
    interruption: interruption ?? "No dominant interruption detected yet.",
  };
}

function summarizeRollupStatus(queries: Array<{ isLoading: boolean; data?: { data: Array<{ status: string }> } }>): RollupStatusSummary {
  const items = queries.flatMap((query) => query.data?.data ?? []);
  return {
    checking: queries.some((query) => query.isLoading && !query.data),
    queued: items.filter((item) => item.status === "queued").length,
    processing: items.filter((item) => item.status === "processing").length,
    pending: items.filter((item) => item.status === "pending_llm").length,
    completed: items.filter((item) => item.status === "processed" || item.status === "violation").length,
    total: items.length,
  };
}

function ganttLoadingCopy(summary: RollupStatusSummary, mode: GranularityValue): GanttLoadingCopy {
  if (summary.processing > 0) {
    return {
      title: "Summaries processing",
      detail: `${summary.processing} required summary ${summary.processing === 1 ? "bucket is" : "buckets are"} currently processing.`,
    };
  }
  if (summary.pending > 0) {
    return {
      title: "Waiting for LLM summaries",
      detail: `${summary.pending} summary ${summary.pending === 1 ? "bucket needs" : "buckets need"} an LLM pass before this Gantt can be composed.`,
    };
  }
  if (summary.queued > 0) {
    return {
      title: "Summaries queued",
      detail: `${summary.queued} summary ${summary.queued === 1 ? "bucket is" : "buckets are"} queued for this ${mode} view.`,
    };
  }
  if (summary.checking) {
    return {
      title: "Checking summary status",
      detail: "Looking up the required hierarchy summaries for this Gantt view.",
    };
  }
  if (summary.completed > 0) {
    return {
      title: "Composing Gantt chart",
      detail: "The final composer is merging completed summaries into display blocks.",
    };
  }
  return {
    title: "Waiting for summaries",
    detail: "No required summary buckets are ready for this selected range yet.",
  };
}

function learningItems(items: TimelineSource[], project: string) {
  const focus = strongestItem(items, "deep");
  const interruption = items.find((item) => item.ignored_noise)?.ignored_noise;
  const meeting = strongestItem(items, "meetings");

  return [
    {
      label: "Active project",
      value: project,
      iconSrc: `${ICON_BASE}/folder-badge.svg`,
    },
    {
      label: "Pattern",
      value: interruption || (meeting ? `${meeting.headline} tends to interrupt focus blocks` : "Patterns will sharpen as more rollups complete"),
      iconSrc: `${ICON_BASE}/music-badge.svg`,
    },
    {
      label: "Focus pattern",
      value: focus ? `${focus.headline} held the clearest attention` : "Deep work patterns are still forming",
      iconSrc: `${ICON_BASE}/sunrise-badge.svg`,
    },
  ];
}

function DashboardTimeline({
  blocks,
  mode,
  rangeStart,
  rangeEnd,
  selectedDay,
  loading,
  loadingCopy,
  error,
}: {
  blocks: ActivityGanttBlock[];
  mode: GranularityValue;
  rangeStart: Date;
  rangeEnd: Date;
  selectedDay: string;
  loading: boolean;
  loadingCopy: GanttLoadingCopy;
  error: boolean;
}) {
  const bounds = { start: rangeStart, end: rangeEnd };
  const ticks = ticksForBounds(bounds.start, bounds.end, mode);
  const rangeMs = Math.max(1, bounds.end.getTime() - bounds.start.getTime());
  const now = new Date();
  const showNow = now >= bounds.start && now <= bounds.end;
  const nowLeft = showNow ? clampPercent(((now.getTime() - bounds.start.getTime()) / rangeMs) * 100) : null;

  if (loading) {
    return (
      <div className="lens-empty-state">
        <strong>{loadingCopy.title}</strong>
        <span>{loadingCopy.detail}</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="lens-empty-state lens-empty-state--error">
        <strong>This view could not load</strong>
        <span>The local API did not return the selected activity summaries.</span>
      </div>
    );
  }

  if (!blocks.length) {
    return (
      <div className="lens-empty-state">
        <strong>{loadingCopy.title}</strong>
        <span>{loadingCopy.detail}</span>
      </div>
    );
  }

  return (
    <div className="lens-timeline">
      <div className="lens-timeline__axis">
        <div className="lens-timeline__axis-spacer" />
        <div className="lens-timeline__axis-track">
          {ticks.map((tick) => {
            const left = clampPercent(((tick.getTime() - bounds.start.getTime()) / rangeMs) * 100);
            return (
              <span key={tick.toISOString()} style={{ left: `${left}%` }}>
                {formatTick(tick, mode)}
              </span>
            );
          })}
          {showNow && <span className="lens-timeline__now-label" style={{ left: `${nowLeft}%` }}>Now</span>}
        </div>
      </div>

      <div className="lens-timeline__lanes">
        {TIMELINE_LANES.map((lane) => {
          const laneBlocks = blocks.filter((block) => block.lane === lane.id);
          return (
            <div key={lane.id} className="lens-timeline__lane">
              <div className="lens-timeline__lane-label">
                <IconImage className="lens-lane-icon" src={lane.iconSrc} size={28} />
                <span>{lane.label}</span>
              </div>
              <div className="lens-timeline__track">
                {ticks.map((tick) => {
                  const left = clampPercent(((tick.getTime() - bounds.start.getTime()) / rangeMs) * 100);
                  return <span key={tick.toISOString()} className="lens-timeline__guide" style={{ left: `${left}%` }} />;
                })}
                {showNow && <span className="lens-timeline__now-line" style={{ left: `${nowLeft}%` }} />}
                {laneBlocks.map((block) => {
                  const startMs = new Date(block.captured_from).getTime();
                  const endMs = new Date(block.captured_to).getTime();
                  const left = clampPercent(((startMs - bounds.start.getTime()) / rangeMs) * 100);
                  const right = clampPercent(((endMs - bounds.start.getTime()) / rangeMs) * 100);
                  const isGap = Boolean(block.is_gap);
                  const displayLabel = isGap ? "Away from keyboard" : block.label;
                  const visualTone = ganttVisualTone(block);
                  const width = block.is_marker ? Math.max(1.4, right - left) : isGap ? Math.max(1, right - left) : Math.max(mode === "week" ? 4 : 3, right - left);
                  const tooltipAlign = left > 78 ? " is-right" : left < 14 ? " is-left" : "";
                  return (
                    <article
                      key={block.id}
                      className={`lens-timeline__block lens-timeline__block--${lane.id} lens-timeline__block--tone-${visualTone}${block.is_marker ? " lens-timeline__block--marker" : ""}${isGap ? " lens-timeline__block--gap" : ""}`}
                      style={{ left: `${left}%`, width: `${width}%` }}
                      tabIndex={0}
                      aria-label={`${displayLabel}. ${blockRangeLabel(block)}. ${block.project}. ${block.summary}`}
                    >
                      <span>{displayLabel}</span>
                      <small>{isGap ? "No analyzed activity" : block.is_marker ? block.source_level : block.project}</small>
                      <div className={`lens-timeline__tooltip${tooltipAlign}`} role="tooltip">
                        <div className="lens-timeline__tooltip-title">{displayLabel}</div>
                        <div className="lens-timeline__tooltip-meta">
                          {blockRangeLabel(block)} - {block.source_level} - {block.project || (isGap ? "Uncovered time" : "General work")}
                        </div>
                        {!isGap && block.visual_group && <div className="lens-timeline__tooltip-meta">Workstream: {block.visual_group}</div>}
                        <p>{block.summary}</p>
                        {block.reason && <p><strong>Composer reason:</strong> {block.reason}</p>}
                        {block.evidence && <p><strong>Evidence:</strong> {block.evidence}</p>}
                        {!isGap && <div className="lens-timeline__tooltip-score">Priority {Math.round(block.priority_score)}</div>}
                      </div>
                    </article>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function PersonalDashboard() {
  const [selectedDay, setSelectedDay] = useState(initialDayValue);
  const [showSettings, setShowSettings] = useState(false);
  const [selectedGranularity, setSelectedGranularity] = useState<GranularityValue>("day");
  const [granularityReady, setGranularityReady] = useState(false);
  const [selectedHour, setSelectedHour] = useState(() => new Date().getHours());
  const [selectedFourHour, setSelectedFourHour] = useState(() => Math.floor(new Date().getHours() / 4) * 4);
  const dateInputRef = useRef<HTMLInputElement | null>(null);
  const today = todayDateValue();
  const canMoveForward = selectedDay < today;
  const currentHour = new Date().getHours();
  const maxHourForSelectedDay = selectedDay === today ? currentHour : 23;
  const maxFourHourForSelectedDay = selectedDay === today ? Math.floor(currentHour / 4) * 4 : 20;
  const canMovePeriodBack =
    selectedGranularity === "1h" ? selectedHour > 0 : selectedGranularity === "4h" ? selectedFourHour > 0 : false;
  const canMovePeriodForward =
    selectedGranularity === "1h"
      ? selectedHour < maxHourForSelectedDay
      : selectedGranularity === "4h"
        ? selectedFourHour < maxFourHourForSelectedDay
        : false;

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
    enabled: Boolean(setupQuery.data && !setupQuery.data.needs_setup && granularityReady && selectedGranularity === "day"),
    refetchInterval:
      selectedDay === today && granularityReady && selectedGranularity === "day" ? DEFAULT_POLL_INTERVAL : false,
  });

  const selectedGranularityOption =
    GRANULARITY_OPTIONS.find((option) => option.value === selectedGranularity) ?? GRANULARITY_OPTIONS[1];
  const selectedRange = useMemo(
    () => rangeForGranularity(selectedDay, selectedGranularityOption.value, selectedHour, selectedFourHour),
    [selectedDay, selectedFourHour, selectedGranularityOption.value, selectedHour],
  );
  const selectedRangeStartIso = selectedRange.start.toISOString();
  const selectedRangeEndIso = selectedRange.end.toISOString();
  const selectedRequiredLevels = GANTT_REQUIRED_LEVELS[selectedGranularity];
  const selectedGanttEnabled = Boolean(
    setupQuery.data && isGanttEnabled(setupQuery.data.runtime_settings, selectedGranularity),
  );
  const rollupStatusQueries = useQueries({
    queries: selectedRequiredLevels.map((level) => ({
      queryKey: ["activity-rollup-status", level, selectedRangeStartIso, selectedRangeEndIso],
      queryFn: () => fetchActivityRollupsRange(level, selectedRangeStartIso, selectedRangeEndIso),
      enabled: Boolean(
        setupQuery.data &&
          !setupQuery.data.needs_setup &&
          granularityReady &&
          selectedGanttEnabled,
      ),
      refetchInterval:
        selectedDay === today && granularityReady && selectedGanttEnabled
          ? DEFAULT_POLL_INTERVAL
          : false,
    })),
  });
  const ganttQuery = useQuery({
    queryKey: ["activity-gantt", selectedGranularity, selectedRangeStartIso, selectedRangeEndIso],
    queryFn: () => fetchActivityGantt(selectedGranularity, selectedRangeStartIso, selectedRangeEndIso),
    enabled: Boolean(
      setupQuery.data &&
        !setupQuery.data.needs_setup &&
        granularityReady &&
        selectedGanttEnabled,
    ),
    refetchInterval:
      selectedDay === today && granularityReady && selectedGanttEnabled
        ? DEFAULT_POLL_INTERVAL
        : false,
  });

  const setup = setupQuery.data;
  const dashboard = dashboardQuery.data;
  const ganttBlocks = ganttQuery.data?.blocks ?? EMPTY_GANTT_BLOCKS;
  const viewItems = useMemo(
    () => [...ganttBlocks].sort((left, right) => new Date(left.captured_from).getTime() - new Date(right.captured_from).getTime()).map(ganttBlockToSource),
    [ganttBlocks],
  );
  const metricItems = useMemo(() => {
    const workItems = viewItems.filter((item) => !item.is_marker && !item.is_gap);
    if (selectedDay !== today) {
      return workItems;
    }
    const nowMs = Date.now();
    return workItems.map((item) => clampSourceToNow(item, nowMs)).filter((item): item is TimelineSource => Boolean(item));
  }, [selectedDay, today, viewItems]);
  const metrics = useMemo(() => buildMetrics(metricItems), [metricItems]);
  const topProject = useMemo(() => dominantProject(metricItems), [metricItems]);
  const story = useMemo(
    () =>
      storyForView(
        selectedDay,
        selectedGranularity,
        selectedRange.start,
        selectedRange.end,
        metricItems,
        selectedDay === today
          ? undefined
          : {
              headline: dashboard?.story_headline,
              summary: dashboard?.story_summary,
            },
      ),
    [dashboard?.story_headline, dashboard?.story_summary, metricItems, selectedDay, selectedGranularity, selectedRange.end, selectedRange.start, today],
  );
  const learned = useMemo(() => learningItems(metricItems, topProject), [metricItems, topProject]);
  const rollupStatus = useMemo(() => summarizeRollupStatus(rollupStatusQueries), [rollupStatusQueries]);
  const timelineLoading = ganttQuery.isLoading || (rollupStatus.checking && !ganttQuery.data);
  const timelineCopy = useMemo(() => ganttLoadingCopy(rollupStatus, selectedGranularity), [rollupStatus, selectedGranularity]);
  const timelineError = ganttQuery.isError;
  const rollupsDisabled = !selectedGanttEnabled;

  useEffect(() => {
    setSelectedGranularity(savedGranularityValue());
    setGranularityReady(true);
  }, []);

  useEffect(() => {
    if (selectedDay !== today) {
      return;
    }
    setSelectedHour((current) => Math.min(current, maxHourForSelectedDay));
    setSelectedFourHour((current) => Math.min(current, maxFourHourForSelectedDay));
  }, [maxFourHourForSelectedDay, maxHourForSelectedDay, selectedDay, today]);

  useEffect(() => {
    if (!granularityReady) {
      return;
    }
    try {
      window.localStorage.setItem(GRANULARITY_STORAGE_KEY, selectedGranularity);
    } catch {
      // Browser storage can be unavailable in stricter privacy modes.
    }
  }, [granularityReady, selectedGranularity]);

  async function refreshSetupAndDashboard() {
    const setupResult = await setupQuery.refetch();
    if (setupResult.data && !setupResult.data.needs_setup) {
      if (selectedGranularity === "day") {
        await dashboardQuery.refetch();
      }
      if (selectedGanttEnabled) {
        await ganttQuery.refetch();
      }
    }
  }

  function shiftPeriod(offset: number) {
    if (selectedGranularity === "1h") {
      setSelectedHour((current) => Math.max(0, Math.min(maxHourForSelectedDay, current + offset)));
    } else if (selectedGranularity === "4h") {
      setSelectedFourHour((current) => Math.max(0, Math.min(maxFourHourForSelectedDay, current + offset * 4)));
    }
  }

  if (setupQuery.isLoading) {
    return (
      <section className="panel-card lens-setup-state">
        <p className="muted">Checking local setup for this machine.</p>
      </section>
    );
  }

  if (setupQuery.isError || !setup) {
    return (
      <section className="panel-card lens-setup-state">
        <p className="error">The app could not read local setup status from the local API.</p>
      </section>
    );
  }

  if (setup.needs_setup) {
    return <SetupPanel setup={setup} onSaved={refreshSetupAndDashboard} mode="setup" />;
  }

  const profileName = setup.runtime_settings.display_name.trim() || "You";
  const learnedTitle =
    profileName === "You"
      ? "What Workday Lens learned about you"
      : `What Workday Lens learned about ${profileName}`;

  return (
    <div className="lens-dashboard">
      {showSettings && (
        <div className="lens-settings-layer">
          <SetupPanel
            setup={setup}
            onSaved={refreshSetupAndDashboard}
            mode="manage"
            onClose={() => setShowSettings(false)}
          />
        </div>
      )}

      <aside className="lens-sidebar">
        <div className="lens-brand">
          <IconImage className="lens-brand__mark" src={WORKDAY_LENS_LOGO_SRC} size={48} />
          <strong>Workday Lens</strong>
        </div>

        <nav className="lens-nav" aria-label="Workday Lens sections">
          <Link href="/" className="lens-nav__item is-active">
            <IconImage className="lens-nav__icon" src={`${ICON_BASE}/sidebar-today.svg`} size={28} />
            Today
          </Link>
          {SIDEBAR_ITEMS.map((item) => (
            item.href ? (
              <Link key={item.label} href={item.href} className="lens-nav__item">
                <IconImage className="lens-nav__icon" src={item.iconSrc} size={28} />
                {item.label}
              </Link>
            ) : (
              <button key={item.label} type="button" className="lens-nav__item" disabled>
              <IconImage className="lens-nav__icon" src={item.iconSrc} size={28} />
              {item.label}
              </button>
            )
          ))}
        </nav>

        <div className="lens-sidebar__art" aria-hidden="true" />

        <div className="lens-profile">
          <div className="lens-profile__avatar" aria-hidden="true">{profileInitial(profileName)}</div>
          <div>
            <strong>{profileName}</strong>
            <span>Focus mode</span>
          </div>
          <button type="button" aria-label="Open local settings" onClick={() => setShowSettings(true)}>
            Settings
          </button>
        </div>
      </aside>

      <main className="lens-main">
        <header className="lens-topbar">
          <div className="lens-date-control">
            <button type="button" aria-label="Previous day" onClick={() => setSelectedDay((current) => shiftDayValue(current, -1))}>
              <span aria-hidden="true">{"<"}</span>
            </button>
            <button
              type="button"
              className="lens-date-control__picker"
              aria-label={`Choose viewing day. Current selection is ${formatDatePickerLabel(selectedDay)}`}
              onClick={openDatePicker}
            >
              <span className="lens-calendar-icon" aria-hidden="true" />
              {selectedGranularity === "week"
                ? formatViewRange(selectedRange.start, selectedRange.end, selectedGranularity)
                : formatDatePickerLabel(selectedDay)}
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
              className="lens-date-control__native"
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

          <div className="lens-granularity" role="tablist" aria-label="Summary granularity">
            {GRANULARITY_OPTIONS.map((option) => (
              <button
                key={option.value}
                type="button"
                className={selectedGranularity === option.value ? "is-active" : ""}
                onClick={() => setSelectedGranularity(option.value)}
                aria-selected={selectedGranularity === option.value}
                role="tab"
              >
                {option.label}
              </button>
            ))}
          </div>
        </header>

        <section className="lens-metrics" aria-label="Activity totals">
          <article className="lens-metric">
            <IconImage className="lens-metric__icon" src={`${ICON_BASE}/focus-time-badge.svg`} size={60} />
            <div>
              <span>Focus Time</span>
              <strong>{formatMinutes(metrics.deep)}</strong>
              <small>{metricItems.filter((item) => laneForSource(item) === "deep").length} focus blocks</small>
            </div>
          </article>
          <article className="lens-metric">
            <IconImage className="lens-metric__icon" src={`${ICON_BASE}/meetings-time-badge.svg`} size={60} />
            <div>
              <span>Meetings Time</span>
              <strong>{formatMinutes(metrics.meetings)}</strong>
              <small>{metricItems.filter((item) => laneForSource(item) === "meetings").length} meeting blocks</small>
            </div>
          </article>
          <article className="lens-metric">
            <IconImage className="lens-metric__icon" src={`${ICON_BASE}/comms-time-badge.svg`} size={60} />
            <div>
              <span>Comms Time</span>
              <strong>{formatMinutes(metrics.comms)}</strong>
              <small>{metricItems.filter((item) => laneForSource(item) === "comms").length} comms blocks</small>
            </div>
          </article>
        </section>

        <section className="lens-story-grid">
          <article className="lens-story-card">
            <div className="lens-card-title">
              <IconImage className="lens-spark" src={`${ICON_BASE}/starburst.svg`} size={26} />
              <div>
                <h2>{story.title}</h2>
                <p>{story.subtitle}</p>
              </div>
            </div>
            <ul className="lens-story-card__copy">
              {story.lines.map((line, index) => (
                <li key={`${index}:${line}`}>{line}</li>
              ))}
            </ul>
            <div className="lens-story-card__art" aria-hidden="true" />
          </article>

          <article className="lens-memory-card">
            <div className="lens-card-title">
              <IconImage className="lens-bulb" src={`${ICON_BASE}/insight-bulb.svg`} size={28} />
              <h2>{learnedTitle}</h2>
            </div>
            <div className="lens-learning-list">
              {learned.map((item) => (
                <div key={item.label} className="lens-learning-row">
                  <IconImage className="lens-learning-icon" src={item.iconSrc} size={42} />
                  <div>
                    <strong>{item.label}</strong>
                    <span>{item.value}</span>
                  </div>
                </div>
              ))}
            </div>
            <button type="button" className="lens-correct-button" disabled>
              Correct memory
            </button>
          </article>
        </section>

        <section className="lens-timeline-card">
          <div className="lens-timeline-card__header">
            <div>
              <h2>{selectedGranularity === "week" ? "This Week's Flow" : "Workday Flow"}</h2>
              <span>{formatViewRange(selectedRange.start, selectedRange.end, selectedGranularity)}</span>
            </div>
            <div className="lens-timeline-card__actions">
              {(selectedGranularity === "1h" || selectedGranularity === "4h") && (
                <div className="lens-period-control" aria-label={`${selectedGranularity} navigation`}>
                  <button type="button" onClick={() => shiftPeriod(-1)} disabled={!canMovePeriodBack}>
                    <span aria-hidden="true">{"<"}</span>
                  </button>
                  <strong>
                    {TIME_FORMATTER.format(selectedRange.start)} - {TIME_FORMATTER.format(selectedRange.end)}
                  </strong>
                  <button type="button" onClick={() => shiftPeriod(1)} disabled={!canMovePeriodForward}>
                    <span aria-hidden="true">{">"}</span>
                  </button>
                </div>
              )}
              {ganttQuery.data?.status === "fallback" && <span>Using deterministic fallback</span>}
              {ganttQuery.data?.status === "provisional" && <span>Using recent windows</span>}
              {ganttQuery.data?.status === "partial" && <span>Updating recent windows</span>}
              {rollupsDisabled && <span>Required rollups are disabled</span>}
            </div>
          </div>
          {rollupsDisabled ? (
            <div className="lens-empty-state">
              <strong>Required rollups are disabled</strong>
              <span>Turn the needed hierarchy levels back on in local settings to compute this chart.</span>
            </div>
          ) : (
            <DashboardTimeline
              blocks={ganttBlocks}
              mode={selectedGranularity}
              rangeStart={selectedRange.start}
              rangeEnd={selectedRange.end}
              selectedDay={selectedDay}
              loading={timelineLoading}
              loadingCopy={timelineCopy}
              error={timelineError}
            />
          )}
        </section>

        <section className="lens-interruption-card">
          <IconImage className="lens-spark" src={`${ICON_BASE}/starburst.svg`} size={26} />
          <p>
            <strong>Main interruption:</strong> {story.interruption}
          </p>
        </section>
      </main>
    </div>
  );
}
