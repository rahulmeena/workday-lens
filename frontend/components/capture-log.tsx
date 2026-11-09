"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { CaptureMessageItem, fetchCaptureMessages } from "../lib/api";

const MAX_VISIBLE_MESSAGES = 500;
const INITIAL_LIMIT = 200;
const POLL_INTERVAL_MS = 1_000;

const TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

const DATE_TIME_FORMATTER = new Intl.DateTimeFormat("en-US", {
  month: "short",
  day: "numeric",
  hour: "numeric",
  minute: "2-digit",
  second: "2-digit",
});

function parseApiDate(value: string) {
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/.test(value) ? value : `${value}Z`;
  return new Date(normalized);
}

function messageKey(message: CaptureMessageItem) {
  return `${message.id}-${message.captured_at}`;
}

function sourceParts(source?: string | null) {
  const parts = (source ?? "").split(":");
  return {
    platform: parts[0] || "unknown",
    tag: parts[1] || "message",
    app: parts.slice(2).join(":") || "unknown",
  };
}

function formatTime(value: string) {
  const date = parseApiDate(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return TIME_FORMATTER.format(date);
}

function formatDateTime(value: string) {
  const date = parseApiDate(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return DATE_TIME_FORMATTER.format(date);
}

function appendMessages(current: CaptureMessageItem[], incoming: CaptureMessageItem[]) {
  if (incoming.length === 0) {
    return current;
  }
  const seen = new Set(current.map((message) => message.id));
  const merged = [...current];
  for (const message of incoming) {
    if (!seen.has(message.id)) {
      merged.push(message);
    }
  }
  merged.sort((a, b) => a.id - b.id);
  return merged.slice(-MAX_VISIBLE_MESSAGES);
}

export function CaptureLog() {
  const [messages, setMessages] = useState<CaptureMessageItem[]>([]);
  const [pendingMessages, setPendingMessages] = useState<CaptureMessageItem[]>([]);
  const [lastSeenId, setLastSeenId] = useState<number | null>(null);
  const [liveRefresh, setLiveRefresh] = useState(true);
  const [displayPaused, setDisplayPaused] = useState(false);
  const [keepLatestVisible, setKeepLatestVisible] = useState(true);
  const [filter, setFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);
  const loadingRef = useRef(false);
  const lastSeenIdRef = useRef<number | null>(null);

  const updateLastSeenId = useCallback((value: number | null) => {
    lastSeenIdRef.current = value;
    setLastSeenId(value);
  }, []);

  const loadMessages = useCallback(
    async (mode: "reset" | "append") => {
      if (loadingRef.current) {
        return;
      }
      loadingRef.current = true;
      setError(null);
      if (mode === "reset") {
        setLoading(true);
      }
      try {
        const response = await fetchCaptureMessages({
          limit: mode === "reset" ? INITIAL_LIMIT : 100,
          afterId: mode === "append" ? lastSeenIdRef.current : null,
        });
        if (mode === "reset") {
          setMessages(response.data);
          setPendingMessages([]);
        } else if (displayPaused) {
          setPendingMessages((current) => appendMessages(current, response.data));
        } else {
          setMessages((current) => appendMessages(current, response.data));
        }
        if (response.latest_id != null) {
          updateLastSeenId(response.latest_id);
        } else if (response.data.length > 0) {
          updateLastSeenId(response.data[response.data.length - 1].id);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not load capture messages.");
      } finally {
        loadingRef.current = false;
        setLoading(false);
      }
    },
    [displayPaused, updateLastSeenId],
  );

  useEffect(() => {
    void loadMessages("reset");
  }, [loadMessages]);

  useEffect(() => {
    if (!liveRefresh) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      void loadMessages("append");
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [liveRefresh, loadMessages]);

  useEffect(() => {
    if (!keepLatestVisible || !listRef.current) {
      return;
    }
    listRef.current.scrollTop = 0;
  }, [messages, pendingMessages, keepLatestVisible]);

  const visibleMessages = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) {
      return messages;
    }
    return messages.filter((message) => {
      const source = message.source ?? "";
      const windowId = message.window_id ?? "";
      return (
        source.toLowerCase().includes(query) ||
        message.text.toLowerCase().includes(query) ||
        windowId.toLowerCase().includes(query) ||
        String(message.id).includes(query)
      );
    });
  }, [filter, messages]);

  const displayedMessages = useMemo(() => [...visibleMessages].reverse(), [visibleMessages]);

  function clearView() {
    setMessages([]);
    setPendingMessages([]);
  }

  function toggleDisplayPaused() {
    if (displayPaused) {
      setPendingMessages([]);
      setDisplayPaused(false);
      return;
    }
    setDisplayPaused(true);
  }

  return (
    <div className="capture-log-page">
      <main className="capture-log-main">
        <header className="capture-log-hero">
          <div>
            <Link href="/timeline" className="capture-log-back">
              Timeline
            </Link>
            <h1>Capture Log</h1>
            <p>Raw transcript messages used for LLM prompt assembly</p>
          </div>
          <div className="capture-log-status" aria-live="polite">
            <span className={liveRefresh ? "is-live" : "is-off"}>{liveRefresh ? "Live refresh on" : "Live refresh off"}</span>
            {displayPaused && <span className="is-paused">Display paused</span>}
            <span>{messages.length} rows</span>
            {pendingMessages.length > 0 && <span className="is-pending">{pendingMessages.length} pending</span>}
            {lastSeenId != null && <span>#{lastSeenId}</span>}
          </div>
        </header>

        <section className="capture-log-toolbar" aria-label="Capture log controls">
          <button type="button" onClick={() => setLiveRefresh((current) => !current)}>
            {liveRefresh ? "Live Refresh On" : "Live Refresh Off"}
          </button>
          <button type="button" className="button--secondary" onClick={toggleDisplayPaused}>
            {displayPaused ? "Resume Display" : "Pause Display"}
          </button>
          <button type="button" className="button--secondary" onClick={() => void loadMessages("reset")}>
            Reload
          </button>
          <button type="button" className="button--secondary" onClick={clearView}>
            Clear View
          </button>
          <label className="capture-log-search">
            <span>Filter</span>
            <input value={filter} onChange={(event) => setFilter(event.target.value)} placeholder="source, text, window id" />
          </label>
          <label className="capture-log-toggle">
            <input type="checkbox" checked={keepLatestVisible} onChange={(event) => setKeepLatestVisible(event.target.checked)} />
            <span>Keep latest visible</span>
          </label>
        </section>

        {error && <div className="capture-log-error">{error}</div>}

        <section className="capture-log-panel" aria-label="Incoming capture messages">
          <div className="capture-log-table-head">
            <span>Time</span>
            <span>Source</span>
            <span>Message</span>
          </div>
          <div ref={listRef} className="capture-log-list">
            {loading && messages.length === 0 ? (
              <div className="capture-log-empty">Loading capture messages.</div>
            ) : displayedMessages.length === 0 ? (
              <div className="capture-log-empty">No matching capture messages.</div>
            ) : (
              displayedMessages.map((message) => {
                const parts = sourceParts(message.source);
                return (
                  <article key={messageKey(message)} className={`capture-log-row capture-log-row--${parts.tag}`}>
                    <div className="capture-log-time">
                      <time title={formatDateTime(message.captured_at)}>{formatTime(message.captured_at)}</time>
                      <span>#{message.id}</span>
                    </div>
                    <div className="capture-log-source">
                      <span>{parts.tag}</span>
                      <strong title={message.source ?? undefined}>{parts.app}</strong>
                      <small>{parts.platform}</small>
                      {message.window_id ? <small title={message.window_id}>window assigned</small> : <small>buffering</small>}
                    </div>
                    <pre>{message.text}</pre>
                  </article>
                );
              })
            )}
          </div>
        </section>
      </main>
    </div>
  );
}
