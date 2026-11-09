"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  SetupStatusResponse,
  deleteRuntimeApiKey,
  reprocessTodayActivity,
  updateRuntimeSettings,
} from "../lib/api";

type SetupPanelMode = "setup" | "manage";

type SetupPanelProps = {
  setup: SetupStatusResponse;
  onSaved: () => Promise<unknown> | void;
  mode?: SetupPanelMode;
  onClose?: () => void;
};

function storageMessage(storageMode: string) {
  if (storageMode === "windows_dpapi") {
    return "Saved API keys are encrypted with Windows account protection before they are written to disk.";
  }
  return "Saved API keys stay on this device in a local settings store.";
}

export function SetupPanel({ setup, onSaved, mode = "setup", onClose }: SetupPanelProps) {
  const runtime = setup.runtime_settings;
  const [apiKey, setApiKey] = useState("");
  const [fakeLlmMode, setFakeLlmMode] = useState(runtime.fake_llm_mode);
  const [llmModel, setLlmModel] = useState(runtime.llm_model);
  const [dashboardStoryEnabled, setDashboardStoryEnabled] = useState(runtime.dashboard_story_llm_enabled);
  const [dashboardStoryModel, setDashboardStoryModel] = useState(runtime.dashboard_story_model);
  const [dashboardStorySegmentLimit, setDashboardStorySegmentLimit] = useState(String(runtime.dashboard_story_segment_limit));
  const [llmTimeoutSeconds, setLlmTimeoutSeconds] = useState(String(runtime.llm_timeout_seconds));
  const [contextSummaryLimit, setContextSummaryLimit] = useState(String(runtime.context_summary_limit));
  const [windowMinSeconds, setWindowMinSeconds] = useState(String(runtime.window_min_seconds));
  const [windowMaxSeconds, setWindowMaxSeconds] = useState(String(runtime.window_max_seconds));
  const [windowTokenLimit, setWindowTokenLimit] = useState(String(runtime.window_token_limit));
  const [preferredLocalPort, setPreferredLocalPort] = useState(String(runtime.preferred_local_port));
  const [isSaving, setIsSaving] = useState(false);
  const [isRemovingKey, setIsRemovingKey] = useState(false);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    setFakeLlmMode(runtime.fake_llm_mode);
    setLlmModel(runtime.llm_model);
    setDashboardStoryEnabled(runtime.dashboard_story_llm_enabled);
    setDashboardStoryModel(runtime.dashboard_story_model);
    setDashboardStorySegmentLimit(String(runtime.dashboard_story_segment_limit));
    setLlmTimeoutSeconds(String(runtime.llm_timeout_seconds));
    setContextSummaryLimit(String(runtime.context_summary_limit));
    setWindowMinSeconds(String(runtime.window_min_seconds));
    setWindowMaxSeconds(String(runtime.window_max_seconds));
    setWindowTokenLimit(String(runtime.window_token_limit));
    setPreferredLocalPort(String(runtime.preferred_local_port));
  }, [
    runtime.context_summary_limit,
    runtime.dashboard_story_llm_enabled,
    runtime.dashboard_story_model,
    runtime.dashboard_story_segment_limit,
    runtime.fake_llm_mode,
    runtime.llm_model,
    runtime.llm_timeout_seconds,
    runtime.preferred_local_port,
    runtime.window_max_seconds,
    runtime.window_min_seconds,
    runtime.window_token_limit,
  ]);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsSaving(true);
    setError(null);
    setSuccess(null);

    try {
      const trimmedApiKey = apiKey.trim();
      const trimmedLlmModel = llmModel.trim();
      const trimmedStoryModel = (dashboardStoryModel.trim() || trimmedLlmModel).trim();
      const parsedDashboardStorySegmentLimit = Number(dashboardStorySegmentLimit);
      const parsedLlmTimeoutSeconds = Number(llmTimeoutSeconds);
      const parsedContextSummaryLimit = Number(contextSummaryLimit);
      const parsedWindowMinSeconds = Number(windowMinSeconds);
      const parsedWindowMaxSeconds = Number(windowMaxSeconds);
      const parsedWindowTokenLimit = Number(windowTokenLimit);
      const parsedPreferredLocalPort = Number(preferredLocalPort);

      if (!trimmedLlmModel) {
        throw new Error("Enter the model name you want Workday Lens to use.");
      }
      if (!fakeLlmMode && !setup.openai_api_key_configured && !trimmedApiKey) {
        throw new Error("Enter an OpenAI API key or turn fake mode back on.");
      }
      if (!Number.isInteger(parsedDashboardStorySegmentLimit) || parsedDashboardStorySegmentLimit < 1 || parsedDashboardStorySegmentLimit > 96) {
        throw new Error("Story segment limit must be between 1 and 96.");
      }
      if (!Number.isInteger(parsedLlmTimeoutSeconds) || parsedLlmTimeoutSeconds < 1 || parsedLlmTimeoutSeconds > 300) {
        throw new Error("LLM timeout must be between 1 and 300 seconds.");
      }
      if (!Number.isInteger(parsedContextSummaryLimit) || parsedContextSummaryLimit < 0 || parsedContextSummaryLimit > 50) {
        throw new Error("Context summary limit must be between 0 and 50.");
      }
      if (!Number.isInteger(parsedWindowMinSeconds) || parsedWindowMinSeconds < 10 || parsedWindowMinSeconds > 3600) {
        throw new Error("Window min seconds must be between 10 and 3600.");
      }
      if (!Number.isInteger(parsedWindowMaxSeconds) || parsedWindowMaxSeconds < 10 || parsedWindowMaxSeconds > 3600) {
        throw new Error("Window max seconds must be between 10 and 3600.");
      }
      if (parsedWindowMaxSeconds < parsedWindowMinSeconds) {
        throw new Error("Window max seconds must be greater than or equal to window min seconds.");
      }
      if (!Number.isInteger(parsedWindowTokenLimit) || parsedWindowTokenLimit < 100 || parsedWindowTokenLimit > 20000) {
        throw new Error("Window token limit must be between 100 and 20000.");
      }
      if (!Number.isInteger(parsedPreferredLocalPort) || parsedPreferredLocalPort < 1024 || parsedPreferredLocalPort > 65535) {
        throw new Error("Choose a local port between 1024 and 65535.");
      }

      await updateRuntimeSettings({
        openai_api_key: trimmedApiKey || undefined,
        fake_llm_mode: fakeLlmMode,
        llm_model: trimmedLlmModel,
        dashboard_story_llm_enabled: dashboardStoryEnabled,
        dashboard_story_model: trimmedStoryModel,
        dashboard_story_segment_limit: parsedDashboardStorySegmentLimit,
        llm_timeout_seconds: parsedLlmTimeoutSeconds,
        context_summary_limit: parsedContextSummaryLimit,
        window_min_seconds: parsedWindowMinSeconds,
        window_max_seconds: parsedWindowMaxSeconds,
        window_token_limit: parsedWindowTokenLimit,
        preferred_local_port: parsedPreferredLocalPort,
      });
      setApiKey("");
      setSuccess(
        mode === "setup"
          ? "Local settings saved. Workday Lens can start using them right away."
          : "Local settings updated. Workday Lens is now using the latest values.",
      );
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the local settings.");
    } finally {
      setIsSaving(false);
    }
  }

  async function handleReprocessToday() {
    setIsReprocessing(true);
    setError(null);
    setSuccess(null);
    try {
      const result = await reprocessTodayActivity();
      const queuedWindows = result.reanalysis_queued_windows;
      setSuccess(
        queuedWindows > 0
          ? `Reprocessing ${queuedWindows} captured ${queuedWindows === 1 ? "window" : "windows"} from today. The chart will refresh as results finish.`
          : "There are no captured windows from today to reprocess yet.",
      );
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reprocess today's activity.");
    } finally {
      setIsReprocessing(false);
    }
  }

  async function handleRemoveApiKey() {
    if (!setup.openai_api_key_configured) {
      return;
    }
    if (typeof window !== "undefined" && !window.confirm("Remove the saved OpenAI API key from this device?")) {
      return;
    }

    setIsRemovingKey(true);
    setError(null);
    setSuccess(null);
    try {
      await deleteRuntimeApiKey();
      setApiKey("");
      setSuccess("The saved OpenAI API key has been removed from this device.");
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove the saved API key.");
    } finally {
      setIsRemovingKey(false);
    }
  }

  const configuredKeyLabel = setup.openai_api_key_last4
    ? `Configured ending in ${setup.openai_api_key_last4}`
    : setup.openai_api_key_configured
      ? "Configured"
      : "Not saved";

  return (
    <section className="setup-card">
      <div className="setup-card__header">
        <div className="setup-card__intro">
          <p className="section-kicker">{mode === "setup" ? "Local Setup" : "Local Settings"}</p>
          <h2>{mode === "setup" ? "Choose how this device should run Workday Lens." : "Edit the local runtime settings any time."}</h2>
          <p>
            Save or rotate the OpenAI key for this machine, switch between live and fake LLM mode,
            tune the timeline analysis settings, and set the packaged launcher browser port.
          </p>
          <p>{storageMessage(setup.openai_api_key_storage)}</p>
        </div>

        {mode === "manage" && onClose && (
          <button type="button" className="button button--secondary" onClick={onClose}>
            Hide settings
          </button>
        )}
      </div>

      <div className="setup-card__status">
        <div className="setup-chip">
          <span className="setup-chip__label">API key</span>
          <strong>{configuredKeyLabel}</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">LLM mode</span>
          <strong>{fakeLlmMode ? "Fake / Offline" : "OpenAI live"}</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">Day story</span>
          <strong>{dashboardStoryEnabled ? "Enabled" : "Off"}</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">Launcher port</span>
          <strong>{preferredLocalPort}</strong>
        </div>
      </div>

      <form className="setup-form" onSubmit={handleSubmit}>
        <label className="form-field">
          <span>OpenAI API key</span>
          <input
            type="password"
            autoComplete="off"
            placeholder={setup.openai_api_key_configured ? "Enter a new key only if you want to rotate it" : "sk-..."}
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
          />
          <small>
            {setup.openai_api_key_configured
              ? "Leave this blank if you only want to update the other settings."
              : "Add a key if you want live OpenAI analysis instead of fake mode."}
          </small>
        </label>

        <div className="setup-form__checks">
          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={fakeLlmMode}
              onChange={(event) => setFakeLlmMode(event.target.checked)}
            />
            <span className="checkbox-field__copy">
              <strong>Use fake / offline LLM mode</strong>
              <span>Keep the product usable without sending activity to OpenAI.</span>
            </span>
          </label>

          <label className="checkbox-field">
            <input
              type="checkbox"
              checked={dashboardStoryEnabled}
              onChange={(event) => setDashboardStoryEnabled(event.target.checked)}
            />
            <span className="checkbox-field__copy">
              <strong>Generate day story summaries</strong>
              <span>Allow the day-level headline and story summary pass for the Gantt chart.</span>
            </span>
          </label>
        </div>

        <div className="setup-form__grid">
          <label className="form-field">
            <span>Primary model</span>
            <input
              type="text"
              placeholder="gpt-5-nano"
              value={llmModel}
              onChange={(event) => setLlmModel(event.target.value)}
            />
            <small>This model handles per-window activity analysis.</small>
          </label>

          <label className="form-field">
            <span>Day story model</span>
            <input
              type="text"
              placeholder="Uses the primary model if left blank"
              value={dashboardStoryModel}
              onChange={(event) => setDashboardStoryModel(event.target.value)}
            />
            <small>This is used for the higher-level daily story summary.</small>
          </label>

          <label className="form-field">
            <span>Story segment limit</span>
            <input
              type="number"
              min={1}
              max={96}
              step={1}
              value={dashboardStorySegmentLimit}
              onChange={(event) => setDashboardStorySegmentLimit(event.target.value)}
            />
            <small>Higher values send more analyzed windows into the day-story pass.</small>
          </label>
        </div>

        <div className="setup-form__grid">
          <label className="form-field">
            <span>LLM timeout (seconds)</span>
            <input
              type="number"
              min={1}
              max={300}
              step={1}
              value={llmTimeoutSeconds}
              onChange={(event) => setLlmTimeoutSeconds(event.target.value)}
            />
            <small>How long Workday Lens waits for each LLM request.</small>
          </label>

          <label className="form-field">
            <span>Context summaries</span>
            <input
              type="number"
              min={0}
              max={50}
              step={1}
              value={contextSummaryLimit}
              onChange={(event) => setContextSummaryLimit(event.target.value)}
            />
            <small>How many recent summaries are fed into the next analysis prompt.</small>
          </label>

          <label className="form-field">
            <span>Window token limit</span>
            <input
              type="number"
              min={100}
              max={20000}
              step={50}
              value={windowTokenLimit}
              onChange={(event) => setWindowTokenLimit(event.target.value)}
            />
            <small>The capture window closes once this token estimate is reached.</small>
          </label>
        </div>

        <div className="setup-form__grid">
          <label className="form-field">
            <span>Window min seconds</span>
            <input
              type="number"
              min={10}
              max={3600}
              step={5}
              value={windowMinSeconds}
              onChange={(event) => setWindowMinSeconds(event.target.value)}
            />
            <small>The earliest point where a capture window can be finalized.</small>
          </label>

          <label className="form-field">
            <span>Window max seconds</span>
            <input
              type="number"
              min={10}
              max={3600}
              step={5}
              value={windowMaxSeconds}
              onChange={(event) => setWindowMaxSeconds(event.target.value)}
            />
            <small>The hard cap for how long one capture window may stay open.</small>
          </label>

          <label className="form-field">
            <span>Preferred local port</span>
            <input
              type="number"
              min={1024}
              max={65535}
              step={1}
              value={preferredLocalPort}
              onChange={(event) => setPreferredLocalPort(event.target.value)}
            />
            <small>The packaged launcher uses this browser port the next time services start.</small>
          </label>
        </div>

        {(error || success) && (
          <p className={error ? "form-message form-message--error" : "form-message form-message--success"}>
            {error || success}
          </p>
        )}

        <div className="setup-form__actions">
          <button type="submit" disabled={isSaving || isRemovingKey || isReprocessing}>
            {isSaving ? "Saving..." : mode === "setup" ? "Save Local Setup" : "Save Settings"}
          </button>

          {mode === "manage" && (
            <button
              type="button"
              className="button button--secondary"
              onClick={handleReprocessToday}
              disabled={isSaving || isRemovingKey || isReprocessing}
            >
              {isReprocessing ? "Queueing..." : "Reprocess Today"}
            </button>
          )}

          {setup.openai_api_key_configured && (
            <button
              type="button"
              className="button button--danger"
              onClick={handleRemoveApiKey}
              disabled={isSaving || isRemovingKey || isReprocessing}
            >
              {isRemovingKey ? "Removing..." : "Remove Saved API Key"}
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
