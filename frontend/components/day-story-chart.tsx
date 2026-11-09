"use client";

import { useMemo, useState } from "react";

import { ActivitySegment } from "../lib/api";

interface DayStoryChartProps {
  day: string;
  segments: ActivitySegment[];
  storyHeadline?: string | null;
  storySummary?: string | null;
}

type StoryLaneId = "deep_work" | "meetings" | "comms" | "breaks";

interface StorySeed {
  id: string;
  lane: StoryLaneId;
  capturedFrom: string;
  capturedTo: string;
  durationMinutes: number;
  trackedMinutes: number;
  segmentCount: number;
  title: string;
  summary: string;
  project: string;
  focusLabel: string;
  isGap: boolean;
  segments: ActivitySegment[];
}

interface StorySession {
  id: string;
  lane: StoryLaneId;
  capturedFrom: string;
  capturedTo: string;
  startMinutes: number;
  endMinutes: number;
  durationMinutes: number;
  trackedMinutes: number;
  segmentCount: number;
  title: string;
  shortLabel: string;
  summary: string;
  project: string;
  focusLabel: string;
  isGap: boolean;
  segments: ActivitySegment[];
}

interface StoryMetrics {
  deep_work: number;
  meetings: number;
  comms: number;
  breaks: number;
}

interface StoryBoardModel {
  sessions: StorySession[];
  sessionsByLane: Record<StoryLaneId, StorySession[]>;
  metrics: StoryMetrics;
  insight: string;
  subtitle: string;
  axisStart: number;
  axisEnd: number;
  axisTicks: number[];
  nowMinute: number | null;
}

const STORY_LANES: Array<{ id: StoryLaneId; label: string }> = [
  { id: "deep_work", label: "Deep Work" },
  { id: "meetings", label: "Meetings" },
  { id: "comms", label: "Comms" },
  { id: "breaks", label: "Breaks" },
];

const GENERIC_HEADLINES = new Set([
  "building and drafting",
  "organizing the next move",
  "reading and investigating",
  "reviewing existing work",
  "coordinating with others",
  "handling routine work",
  "stepping away",
  "general activity",
  "making progress on a core task",
  "organizing the next chunk of work",
  "reading and collecting context",
  "reviewing existing work or feedback",
  "coordinating with other people",
  "handling operational work",
  "paused away from active work",
  "moving through general work",
]);

const MEETING_KEYWORDS = [
  "meeting",
  "meetings",
  "zoom",
  "teams call",
  "google meet",
  "standup",
  "sync",
  "1:1",
  "one-on-one",
  "interview",
  "demo",
  "retro",
  "workshop",
  "kickoff",
  "calendar invite",
  "call",
];

const COMMON_TITLE_WORDS = new Set([
  "and",
  "for",
  "the",
  "with",
  "from",
  "into",
  "that",
  "this",
  "work",
  "task",
  "general",
  "current",
  "likely",
  "project",
  "setup",
  "review",
]);

const OFFLINE_GAP_MINUTES = 20;

const WEEKDAY_FORMATTER = new Intl.DateTimeFormat("en-US", {
  weekday: "long",
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

function formatAxisHour(totalMinutes: number) {
  const hours = Math.floor(totalMinutes / 60) % 24;
  const normalized = hours % 12 || 12;
  return `${normalized}${hours < 12 ? "A" : "P"}`;
}

function formatClockTime(value: string) {
  const date = new Date(value);
  const hours = date.getHours();
  const minutes = date.getMinutes();
  const normalized = hours % 12 || 12;
  const suffix = hours < 12 ? "am" : "pm";
  if (!minutes) {
    return `${normalized}${suffix}`;
  }
  return `${normalized}:${String(minutes).padStart(2, "0")}${suffix}`;
}

function formatDaySubtitle(day: string, segments: ActivitySegment[]) {
  const sourceDate = new Date(`${day}T12:00:00`);
  const weekday = WEEKDAY_FORMATTER.format(sourceDate);
  const count = segments.length;
  return `${weekday} - summarized from ${count} captured ${count === 1 ? "moment" : "moments"}`;
}

function minutesBetween(start: string, end: string) {
  const diff = Math.max(0, new Date(end).getTime() - new Date(start).getTime());
  return Math.max(1, Math.round(diff / 60000));
}

function clockMinutes(value: string) {
  const date = new Date(value);
  return date.getHours() * 60 + date.getMinutes();
}

function normalizeText(value: string) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
}

function keywordTokens(value: string) {
  return normalizeText(value)
    .split(" ")
    .filter((token) => token && token.length > 2 && !COMMON_TITLE_WORDS.has(token));
}

function titleSimilarity(left: string, right: string) {
  const leftTokens = keywordTokens(left);
  const rightTokens = keywordTokens(right);
  if (!leftTokens.length || !rightTokens.length) {
    return false;
  }
  const rightSet = new Set(rightTokens);
  return leftTokens.some((token) => rightSet.has(token));
}

function normalizedProject(project: string) {
  return normalizeText(project || "general work");
}

function pickStoryTitle(segment: ActivitySegment) {
  const headline = segment.headline.trim();
  if (headline && !GENERIC_HEADLINES.has(normalizeText(headline))) {
    return headline;
  }

  const summary = segment.summary
    .split(/[.!?]/)[0]
    ?.replace(/\s+/g, " ")
    .trim();
  if (summary) {
    return summary.charAt(0).toUpperCase() + summary.slice(1);
  }

  if (segment.goal.trim()) {
    return segment.goal.trim();
  }

  return segment.activity_label;
}

function buildShortLabel(title: string, fallback: string) {
  const tokens = title
    .replace(/[^a-zA-Z0-9]+/g, " ")
    .trim()
    .split(/\s+/)
    .filter(Boolean);

  if (!tokens.length) {
    return fallback;
  }

  if (tokens[0].length >= 3) {
    return tokens[0].slice(0, 4).toUpperCase();
  }

  if (tokens.length > 1 && `${tokens[0]}${tokens[1]}`.length >= 3) {
    return `${tokens[0]}${tokens[1]}`.slice(0, 4).toUpperCase();
  }

  return tokens
    .slice(0, 2)
    .map((token) => token[0]?.toUpperCase() ?? "")
    .join("")
    .slice(0, 3) || fallback;
}

function isMeetingLike(segment: ActivitySegment) {
  const haystack = [
    segment.headline,
    segment.summary,
    segment.goal,
    segment.project,
    segment.raw_excerpt,
  ]
    .join(" ")
    .toLowerCase();

  return MEETING_KEYWORDS.some((keyword) => haystack.includes(keyword));
}

function storyLaneFor(segment: ActivitySegment): StoryLaneId {
  if (segment.activity_type === "break") {
    return "breaks";
  }
  if (segment.activity_type === "communication") {
    return isMeetingLike(segment) ? "meetings" : "comms";
  }
  if (segment.activity_type === "admin") {
    return isMeetingLike(segment) ? "meetings" : "comms";
  }
  return "deep_work";
}

function laneMergeLimitMinutes(lane: StoryLaneId) {
  if (lane === "deep_work") {
    return 18;
  }
  if (lane === "meetings") {
    return 14;
  }
  if (lane === "comms") {
    return 12;
  }
  return 32;
}

function strongestSegment(segments: ActivitySegment[]) {
  return [...segments].sort((left, right) => right.duration_minutes - left.duration_minutes)[0] ?? null;
}

function sessionFallback(lane: StoryLaneId) {
  if (lane === "meetings") {
    return "MTG";
  }
  if (lane === "comms") {
    return "CHAT";
  }
  if (lane === "breaks") {
    return "BRK";
  }
  return "FOCS";
}

function seedFromSegment(segment: ActivitySegment): StorySeed {
  return {
    id: segment.window_id,
    lane: storyLaneFor(segment),
    capturedFrom: segment.captured_from,
    capturedTo: segment.captured_to,
    durationMinutes: segment.duration_minutes,
    trackedMinutes: segment.duration_minutes,
    segmentCount: 1,
    title: pickStoryTitle(segment),
    summary: segment.summary,
    project: segment.project,
    focusLabel: segment.focus_label,
    isGap: false,
    segments: [segment],
  };
}

function seedForGap(previous: ActivitySegment, current: ActivitySegment): StorySeed {
  return {
    id: `gap-${previous.window_id}-${current.window_id}`,
    lane: "breaks",
    capturedFrom: previous.captured_to,
    capturedTo: current.captured_from,
    durationMinutes: minutesBetween(previous.captured_to, current.captured_from),
    trackedMinutes: 0,
    segmentCount: 0,
    title: "Away from keyboard",
    summary: "No windows were captured in this stretch, so the story treats it as a pause or uncaptured away time.",
    project: "Offline gap",
    focusLabel: "Idle",
    isGap: true,
    segments: [],
  };
}

function sessionFromSeed(seed: StorySeed): StorySession {
  return {
    id: seed.id,
    lane: seed.lane,
    capturedFrom: seed.capturedFrom,
    capturedTo: seed.capturedTo,
    startMinutes: clockMinutes(seed.capturedFrom),
    endMinutes: clockMinutes(seed.capturedTo),
    durationMinutes: seed.durationMinutes,
    trackedMinutes: seed.trackedMinutes,
    segmentCount: seed.segmentCount,
    title: seed.title,
    shortLabel: buildShortLabel(seed.title, sessionFallback(seed.lane)),
    summary: seed.summary,
    project: seed.project,
    focusLabel: seed.focusLabel,
    isGap: seed.isGap,
    segments: seed.segments,
  };
}

function mergeSeedIntoSession(session: StorySession, seed: StorySeed) {
  session.capturedTo = seed.capturedTo;
  session.endMinutes = clockMinutes(seed.capturedTo);
  session.durationMinutes = minutesBetween(session.capturedFrom, seed.capturedTo);
  session.trackedMinutes += seed.trackedMinutes;
  session.segmentCount += seed.segmentCount;
  session.isGap = session.isGap && seed.isGap;
  session.segments = [...session.segments, ...seed.segments];

  const focusSource = strongestSegment(session.segments);
  if (focusSource) {
    session.title = pickStoryTitle(focusSource);
    session.summary = focusSource.summary;
    session.project = focusSource.project;
    session.focusLabel = focusSource.focus_label;
  } else if (seed.durationMinutes >= session.durationMinutes || session.isGap) {
    session.title = seed.title;
    session.summary = seed.summary;
    session.project = seed.project;
    session.focusLabel = seed.focusLabel;
  }

  session.shortLabel = buildShortLabel(session.title, sessionFallback(session.lane));
}

function shouldMergeSession(previous: StorySession, seed: StorySeed) {
  const gapMinutes = minutesBetween(previous.capturedTo, seed.capturedFrom);
  if (gapMinutes > laneMergeLimitMinutes(seed.lane)) {
    return false;
  }

  if (previous.isGap || seed.isGap) {
    return true;
  }

  if (normalizedProject(previous.project) === normalizedProject(seed.project)) {
    return true;
  }

  if (titleSimilarity(previous.title, seed.title)) {
    return true;
  }

  const previousIsMicro = previous.trackedMinutes <= 8 || previous.durationMinutes <= 10;
  const seedIsMicro = seed.trackedMinutes <= 8 || seed.durationMinutes <= 10;
  if (previousIsMicro || seedIsMicro) {
    return gapMinutes <= 10;
  }

  return gapMinutes <= 4;
}

function mergeLaneSeeds(seeds: StorySeed[]) {
  const ordered = [...seeds].sort(
    (left, right) => new Date(left.capturedFrom).getTime() - new Date(right.capturedFrom).getTime(),
  );

  const sessions: StorySession[] = [];
  for (const seed of ordered) {
    const previous = sessions[sessions.length - 1];
    if (!previous || !shouldMergeSession(previous, seed)) {
      sessions.push(sessionFromSeed(seed));
      continue;
    }
    mergeSeedIntoSession(previous, seed);
  }
  return sessions;
}

function buildStorySessions(segments: ActivitySegment[]) {
  if (!segments.length) {
    return [];
  }

  const ordered = [...segments].sort(
    (left, right) => new Date(left.captured_from).getTime() - new Date(right.captured_from).getTime(),
  );

  const seedsByLane: Record<StoryLaneId, StorySeed[]> = {
    deep_work: [],
    meetings: [],
    comms: [],
    breaks: [],
  };

  for (const [index, segment] of ordered.entries()) {
    const previous = ordered[index - 1];
    if (previous) {
      const gapMinutes = minutesBetween(previous.captured_to, segment.captured_from);
      if (gapMinutes >= OFFLINE_GAP_MINUTES) {
        seedsByLane.breaks.push(seedForGap(previous, segment));
      }
    }

    const seed = seedFromSegment(segment);
    seedsByLane[seed.lane].push(seed);
  }

  return STORY_LANES.flatMap((lane) => mergeLaneSeeds(seedsByLane[lane.id])).sort(
    (left, right) => new Date(left.capturedFrom).getTime() - new Date(right.capturedFrom).getTime(),
  );
}

function buildAxisTicks(axisStart: number, axisEnd: number) {
  const span = axisEnd - axisStart;
  const step = span > 12 * 60 ? 120 : 60;
  const ticks: number[] = [];
  for (let minute = axisStart; minute <= axisEnd; minute += step) {
    ticks.push(minute);
  }
  if (ticks[ticks.length - 1] !== axisEnd) {
    ticks.push(axisEnd);
  }
  return ticks;
}

function laneMetrics(sessions: StorySession[]): StoryMetrics {
  return sessions.reduce<StoryMetrics>(
    (totals, session) => {
      if (session.lane === "breaks") {
        totals.breaks += session.durationMinutes;
      } else {
        totals[session.lane] += session.trackedMinutes;
      }
      return totals;
    },
    {
      deep_work: 0,
      meetings: 0,
      comms: 0,
      breaks: 0,
    },
  );
}

function storyInsight(sessions: StorySession[], metrics: StoryMetrics) {
  if (!sessions.length) {
    return "The timeline will build a concise story once a few analyzed windows are available.";
  }

  const deepestFocus =
    sessions
      .filter((session) => session.lane === "deep_work" && !session.isGap)
      .sort((left, right) => right.trackedMinutes - left.trackedMinutes)[0] ?? null;

  if (deepestFocus) {
    const focusClause = `Deepest focus landed ${formatClockTime(deepestFocus.capturedFrom)}-${formatClockTime(deepestFocus.capturedTo)} on ${deepestFocus.title}.`;
    const coordinationMinutes = metrics.meetings + metrics.comms;
    if (coordinationMinutes) {
      return `${focusClause} Coordination stayed at ${formatMinutes(coordinationMinutes)}, so the day still left room for heads-down work.`;
    }
    return `${focusClause} Most of the captured day stayed in maker mode instead of coordination.`;
  }

  if (metrics.meetings) {
    return `The day leaned toward live coordination, with ${formatMinutes(metrics.meetings)} in meetings and shorter solo work blocks around them.`;
  }

  if (metrics.comms) {
    return "The story is communication-heavy so far, suggesting more check-ins and follow-ups than uninterrupted build time.";
  }

  return "Most captured activity looked transitional, so the chart is grouping lighter movement instead of one long focus run.";
}

function buildBoard(day: string, segments: ActivitySegment[]): StoryBoardModel {
  const sessions = buildStorySessions(segments);
  const sessionsByLane: Record<StoryLaneId, StorySession[]> = {
    deep_work: [],
    meetings: [],
    comms: [],
    breaks: [],
  };

  for (const session of sessions) {
    sessionsByLane[session.lane].push(session);
  }

  const metrics = laneMetrics(sessions);
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const nowMinute = day === today ? now.getHours() * 60 + now.getMinutes() : null;
  let axisStart = 0;
  let axisEnd = 24 * 60;
  if (sessions.length) {
    const startCandidates = sessions.map((session) => session.startMinutes);
    const endCandidates = sessions.map((session) => session.endMinutes);
    if (nowMinute !== null) {
      startCandidates.push(nowMinute);
      endCandidates.push(nowMinute);
    }
    const earliest = Math.min(...startCandidates);
    const latest = Math.max(...endCandidates);
    axisStart = Math.max(0, Math.floor(earliest / 60) * 60);
    axisEnd = Math.min(24 * 60, Math.max(axisStart + 6 * 60, Math.ceil(latest / 60) * 60));
  }

  return {
    sessions,
    sessionsByLane,
    metrics,
    insight: storyInsight(sessions, metrics),
    subtitle: formatDaySubtitle(day, segments),
    axisStart,
    axisEnd,
    axisTicks: buildAxisTicks(axisStart, axisEnd),
    nowMinute,
  };
}

function leftPercent(start: number, axisStart: number, axisEnd: number) {
  const total = Math.max(1, axisEnd - axisStart);
  return ((start - axisStart) / total) * 100;
}

function widthPercent(start: number, end: number, axisStart: number, axisEnd: number) {
  const total = Math.max(1, axisEnd - axisStart);
  return ((end - start) / total) * 100;
}

function rangeAriaLabel(session: StorySession) {
  return `${session.title} from ${formatClockTime(session.capturedFrom)} to ${formatClockTime(session.capturedTo)} for ${formatMinutes(session.durationMinutes)}`;
}

function laneAriaSummary(session: StorySession) {
  if (session.isGap) {
    return "No captured windows";
  }
  return `${session.project} - ${formatMinutes(session.trackedMinutes)} tracked`;
}

function laneTagLabel(lane: StoryLaneId) {
  if (lane === "deep_work") {
    return "Deep Work";
  }
  if (lane === "meetings") {
    return "Meetings";
  }
  if (lane === "comms") {
    return "Comms";
  }
  return "Breaks";
}

export function DayStoryChart({ day, segments, storyHeadline, storySummary }: DayStoryChartProps) {
  const board = useMemo(() => buildBoard(day, segments), [day, segments]);
  const [hoveredSessionId, setHoveredSessionId] = useState<string | null>(null);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(null);

  const defaultSession =
    board.sessions.find((session) => session.lane === "deep_work" && !session.isGap) ??
    board.sessions[board.sessions.length - 1] ??
    null;
  const detailSession =
    board.sessions.find((session) => session.id === hoveredSessionId) ??
    board.sessions.find((session) => session.id === selectedSessionId) ??
    defaultSession;

  return (
    <section className="story-card">
      <div className="story-card__shell">
        <div className="story-card__header">
          <div className="story-card__title-group">
            <div className="story-card__badge" aria-hidden="true">
              <span />
            </div>
            <div>
              <p className="story-card__eyebrow">Today&apos;s Story</p>
              <p className="story-card__subtitle">{board.subtitle}</p>
            </div>
          </div>

          <div className="story-card__totals" aria-label="Story totals">
            <div className="story-card__total">
              <strong>{formatMinutes(board.metrics.deep_work)}</strong>
              <span>Focus</span>
            </div>
            <div className="story-card__total">
              <strong>{formatMinutes(board.metrics.meetings)}</strong>
              <span>Meetings</span>
            </div>
            <div className="story-card__total">
              <strong>{formatMinutes(board.metrics.comms)}</strong>
              <span>Comms</span>
            </div>
          </div>
        </div>

        <div className="story-board">
          <div className="story-board__axis">
            <div className="story-board__axis-spacer" />
            <div className="story-board__axis-track">
              {board.axisTicks.map((tick) => {
                const isNow = board.nowMinute !== null && Math.abs(board.nowMinute - tick) < 30;
                return (
                  <div key={tick} className={`story-board__tick${isNow ? " is-now" : ""}`}>
                    {isNow ? "NOW" : formatAxisHour(tick)}
                  </div>
                );
              })}
            </div>
          </div>

          <div className="story-board__lanes">
            {STORY_LANES.map((lane) => (
              <div key={lane.id} className="story-lane">
                <div className="story-lane__label">
                  <span className={`story-lane__icon story-lane__icon--${lane.id}`} aria-hidden="true" />
                  <span>{lane.label}</span>
                </div>

                <div className="story-lane__track">
                  {board.axisTicks.map((tick) => (
                    <span
                      key={`${lane.id}-${tick}`}
                      className="story-lane__guide"
                      style={{ left: `${leftPercent(tick, board.axisStart, board.axisEnd)}%` }}
                      aria-hidden="true"
                    />
                  ))}

                  {board.nowMinute !== null && board.nowMinute >= board.axisStart && board.nowMinute <= board.axisEnd && (
                    <span
                      className="story-lane__now"
                      style={{ left: `${leftPercent(board.nowMinute, board.axisStart, board.axisEnd)}%` }}
                      aria-hidden="true"
                    />
                  )}

                  {board.sessionsByLane[lane.id].map((session) => {
                    const isActive = detailSession?.id === session.id;
                    const compact = session.durationMinutes < 42;
                    const startPercent = leftPercent(session.startMinutes, board.axisStart, board.axisEnd);
                    const sessionWidth = Math.max(
                      widthPercent(session.startMinutes, session.endMinutes, board.axisStart, board.axisEnd),
                      compact ? 4.5 : 8,
                    );
                    const endPercent = startPercent + sessionWidth;
                    const popoverEdgeClass =
                      startPercent < 10
                        ? " story-block--edge-left"
                        : endPercent > 92
                          ? " story-block--edge-right"
                          : "";
                    return (
                      <button
                        key={session.id}
                        type="button"
                        className={`story-block story-block--${lane.id}${session.isGap ? " story-block--gap" : ""}${compact ? " story-block--compact" : ""}${isActive ? " is-active" : ""}${popoverEdgeClass}`}
                        style={{
                          left: `${startPercent}%`,
                          width: `${sessionWidth}%`,
                        }}
                        aria-label={rangeAriaLabel(session)}
                        title={`${session.title} - ${formatClockTime(session.capturedFrom)}-${formatClockTime(session.capturedTo)}`}
                        onMouseEnter={() => setHoveredSessionId(session.id)}
                        onMouseLeave={() => setHoveredSessionId((current) => (current === session.id ? null : current))}
                        onFocus={() => setHoveredSessionId(session.id)}
                        onBlur={() => setHoveredSessionId((current) => (current === session.id ? null : current))}
                        onClick={() => setSelectedSessionId((current) => (current === session.id ? null : session.id))}
                      >
                        <span className="story-block__content">
                          {compact ? (
                            <span className="story-block__short">{session.isGap ? "Away" : session.shortLabel}</span>
                          ) : (
                            <span className="story-block__title">{session.title}</span>
                          )}
                        </span>

                        <span className="story-block__popover" role="tooltip">
                          <strong>{session.title}</strong>
                          <span>{laneAriaSummary(session)}</span>
                          <span>{`${formatClockTime(session.capturedFrom)} - ${formatClockTime(session.capturedTo)}`}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>

        {detailSession ? (
          <div className="story-detail">
            <div className="story-detail__heading">
              <span className={`story-detail__lane story-detail__lane--${detailSession.lane}`}>{laneTagLabel(detailSession.lane)}</span>
              <h4>{detailSession.title}</h4>
            </div>
            <p className="story-detail__summary">
              {detailSession.isGap
                ? "This stretch had no captured windows, so it is summarized as time away or uncaptured activity."
                : detailSession.summary}
            </p>
            <div className="story-detail__meta">
              <span>{`${formatClockTime(detailSession.capturedFrom)} - ${formatClockTime(detailSession.capturedTo)}`}</span>
              <span>{detailSession.isGap ? formatMinutes(detailSession.durationMinutes) : `${formatMinutes(detailSession.trackedMinutes)} tracked`}</span>
              <span>{detailSession.project}</span>
              {!detailSession.isGap && <span>{detailSession.focusLabel}</span>}
              {detailSession.segmentCount > 1 && <span>{`${detailSession.segmentCount} grouped windows`}</span>}
            </div>
          </div>
        ) : (
          <div className="story-detail story-detail--empty">
            <div className="story-detail__heading">
              <span className="story-detail__lane story-detail__lane--breaks">Empty day</span>
              <h4>No analyzed activity has landed on this chart yet.</h4>
            </div>
            <p className="story-detail__summary">
              The full day board stays visible so you can keep the same timeline frame even before the first captured window arrives.
            </p>
            <div className="story-detail__meta">
              <span>0 tracked minutes</span>
              <span>4 empty lanes ready</span>
              {board.nowMinute !== null && <span>Today&apos;s marker is still visible</span>}
            </div>
          </div>
        )}

        <div className="story-insight">
          <div className="story-insight__marker" aria-hidden="true" />
          <p>
            <strong>{storyHeadline || "Today's insight"}:</strong> {storySummary || board.insight}
          </p>
        </div>
      </div>
    </section>
  );
}
