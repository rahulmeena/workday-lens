"use client";

import { FormEvent, useEffect, useState } from "react";

import {
  SetupStatusResponse,
  deleteRuntimeApiKey,
  prepareLocalModel,
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

const LOCAL_QWEN_PROVIDER = "local_qwen35_4b";
const LOCAL_QWEN_DISPLAY_MODEL = "Qwen3.5-4B-Q4_K_M+generic_v8";

function storageMessage(storageMode: string) {
  if (storageMode === "windows_dpapi") {
    return "Saved API keys are encrypted with Windows account protection before they are written to disk.";
  }
  return "Saved API keys stay on this device in a local settings store.";
}

export function SetupPanel({ setup, onSaved, mode = "setup", onClose }: SetupPanelProps) {
  const runtime = setup.runtime_settings;
  const [apiKey, setApiKey] = useState("");
  const [displayName, setDisplayName] = useState(runtime.display_name);
  const [llmProvider, setLlmProvider] = useState(runtime.llm_provider);
  const [fakeLlmMode, setFakeLlmMode] = useState(runtime.fake_llm_mode);
  const [llmModel, setLlmModel] = useState(runtime.llm_model);
  const [dashboardStoryEnabled, setDashboardStoryEnabled] = useState(runtime.dashboard_story_llm_enabled);
  const [dashboardStoryModel, setDashboardStoryModel] = useState(runtime.dashboard_story_model);
  const [rollup5mEnabled, setRollup5mEnabled] = useState(runtime.rollup_5m_enabled);
  const [rollup15mEnabled, setRollup15mEnabled] = useState(runtime.rollup_15m_enabled);
  const [rollup1hEnabled, setRollup1hEnabled] = useState(runtime.rollup_1h_enabled);
  const [rollup4hEnabled, setRollup4hEnabled] = useState(runtime.rollup_4h_enabled);
  const [rollup1dEnabled, setRollup1dEnabled] = useState(runtime.rollup_1d_enabled);
  const [rollup1wEnabled, setRollup1wEnabled] = useState(runtime.rollup_1w_enabled);
  const [llmTimeoutSeconds, setLlmTimeoutSeconds] = useState(String(runtime.llm_timeout_seconds));
  const [contextSummaryLimit, setContextSummaryLimit] = useState(String(runtime.context_summary_limit));
  const [rollup5mContextSummaryLimit, setRollup5mContextSummaryLimit] = useState(String(runtime.rollup_5m_context_summary_limit));
  const [rollup15mContextSummaryLimit, setRollup15mContextSummaryLimit] = useState(String(runtime.rollup_15m_context_summary_limit));
  const [rollup1hContextSummaryLimit, setRollup1hContextSummaryLimit] = useState(String(runtime.rollup_1h_context_summary_limit));
  const [rollup4hContextSummaryLimit, setRollup4hContextSummaryLimit] = useState(String(runtime.rollup_4h_context_summary_limit));
  const [windowMinSeconds, setWindowMinSeconds] = useState(String(runtime.window_min_seconds));
  const [windowMaxSeconds, setWindowMaxSeconds] = useState(String(runtime.window_max_seconds));
  const [windowTokenLimit, setWindowTokenLimit] = useState(String(runtime.window_token_limit));
  const [rollup5mRawTokenLimit, setRollup5mRawTokenLimit] = useState(String(runtime.rollup_5m_raw_token_limit));
  const [preferredLocalPort, setPreferredLocalPort] = useState(String(runtime.preferred_local_port));
  const [isSaving, setIsSaving] = useState(false);
  const [isRemovingKey, setIsRemovingKey] = useState(false);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const [isPreparingModel, setIsPreparingModel] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    setDisplayName(runtime.display_name);
    setLlmProvider(runtime.llm_provider);
    setFakeLlmMode(runtime.fake_llm_mode);
    setLlmModel(runtime.llm_model);
    setDashboardStoryEnabled(runtime.dashboard_story_llm_enabled);
    setDashboardStoryModel(runtime.dashboard_story_model);
    setRollup5mEnabled(runtime.rollup_5m_enabled);
    setRollup15mEnabled(runtime.rollup_15m_enabled);
    setRollup1hEnabled(runtime.rollup_1h_enabled);
    setRollup4hEnabled(runtime.rollup_4h_enabled);
    setRollup1dEnabled(runtime.rollup_1d_enabled);
    setRollup1wEnabled(runtime.rollup_1w_enabled);
    setLlmTimeoutSeconds(String(runtime.llm_timeout_seconds));
    setContextSummaryLimit(String(runtime.context_summary_limit));
    setRollup5mContextSummaryLimit(String(runtime.rollup_5m_context_summary_limit));
    setRollup15mContextSummaryLimit(String(runtime.rollup_15m_context_summary_limit));
    setRollup1hContextSummaryLimit(String(runtime.rollup_1h_context_summary_limit));
    setRollup4hContextSummaryLimit(String(runtime.rollup_4h_context_summary_limit));
    setWindowMinSeconds(String(runtime.window_min_seconds));
    setWindowMaxSeconds(String(runtime.window_max_seconds));
    setWindowTokenLimit(String(runtime.window_token_limit));
    setRollup5mRawTokenLimit(String(runtime.rollup_5m_raw_token_limit));
    setPreferredLocalPort(String(runtime.preferred_local_port));
  }, [
    runtime.context_summary_limit,
    runtime.dashboard_story_llm_enabled,
    runtime.dashboard_story_model,
    runtime.display_name,
    runtime.fake_llm_mode,
    runtime.llm_provider,
    runtime.llm_model,
    runtime.llm_timeout_seconds,
    runtime.preferred_local_port,
    runtime.rollup_15m_enabled,
    runtime.rollup_15m_context_summary_limit,
    runtime.rollup_1d_enabled,
    runtime.rollup_1h_enabled,
    runtime.rollup_1h_context_summary_limit,
    runtime.rollup_1w_enabled,
    runtime.rollup_4h_enabled,
    runtime.rollup_4h_context_summary_limit,
    runtime.rollup_5m_enabled,
    runtime.rollup_5m_context_summary_limit,
    runtime.rollup_5m_raw_token_limit,
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
      const trimmedDisplayName = displayName.trim();
      const useLocalQwen = !fakeLlmMode && llmProvider === LOCAL_QWEN_PROVIDER;
      const trimmedLlmModel = useLocalQwen ? LOCAL_QWEN_DISPLAY_MODEL : llmModel.trim();
      const trimmedStoryModel = (dashboardStoryModel.trim() || trimmedLlmModel).trim();
      const parsedLlmTimeoutSeconds = Number(llmTimeoutSeconds);
      const parsedContextSummaryLimit = Number(contextSummaryLimit);
      const parsedRollup5mContextSummaryLimit = Number(rollup5mContextSummaryLimit);
      const parsedRollup15mContextSummaryLimit = Number(rollup15mContextSummaryLimit);
      const parsedRollup1hContextSummaryLimit = Number(rollup1hContextSummaryLimit);
      const parsedRollup4hContextSummaryLimit = Number(rollup4hContextSummaryLimit);
      const parsedWindowMinSeconds = Number(windowMinSeconds);
      const parsedWindowMaxSeconds = Number(windowMaxSeconds);
      const parsedWindowTokenLimit = Number(windowTokenLimit);
      const parsedRollup5mRawTokenLimit = Number(rollup5mRawTokenLimit);
      const parsedPreferredLocalPort = Number(preferredLocalPort);

      if (!trimmedDisplayName) {
        throw new Error("Enter the display name Workday Lens should use.");
      }
      if (!trimmedLlmModel) {
        throw new Error("Enter the model name you want Workday Lens to use.");
      }
      if (!fakeLlmMode && llmProvider === "openai" && !setup.openai_api_key_configured && !trimmedApiKey) {
        throw new Error("Enter an OpenAI API key, choose Local Qwen, or use fake demo mode.");
      }
      if (!Number.isInteger(parsedLlmTimeoutSeconds) || parsedLlmTimeoutSeconds < 1 || parsedLlmTimeoutSeconds > 300) {
        throw new Error("LLM timeout must be between 1 and 300 seconds.");
      }
      if (!Number.isInteger(parsedContextSummaryLimit) || parsedContextSummaryLimit < 0 || parsedContextSummaryLimit > 50) {
        throw new Error("1m context summary limit must be between 0 and 50.");
      }
      const rollupContextLimits = [
        ["5m", parsedRollup5mContextSummaryLimit],
        ["15m", parsedRollup15mContextSummaryLimit],
        ["1h", parsedRollup1hContextSummaryLimit],
        ["4h", parsedRollup4hContextSummaryLimit],
      ] as const;
      for (const [label, value] of rollupContextLimits) {
        if (!Number.isInteger(value) || value < 0 || value > 50) {
          throw new Error(`${label} context summary limit must be between 0 and 50.`);
        }
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
      if (!Number.isInteger(parsedWindowTokenLimit) || parsedWindowTokenLimit < 100 || parsedWindowTokenLimit > 64000) {
        throw new Error("1m token limit must be between 100 and 64000.");
      }
      if (!Number.isInteger(parsedRollup5mRawTokenLimit) || parsedRollup5mRawTokenLimit < 0 || parsedRollup5mRawTokenLimit > 64000) {
        throw new Error("5m raw transcript token limit must be between 0 and 64000.");
      }
      if (!Number.isInteger(parsedPreferredLocalPort) || parsedPreferredLocalPort < 1024 || parsedPreferredLocalPort > 65535) {
        throw new Error("Choose a local port between 1024 and 65535.");
      }

      await updateRuntimeSettings({
        openai_api_key: trimmedApiKey || undefined,
        display_name: trimmedDisplayName,
        llm_provider: llmProvider,
        fake_llm_mode: fakeLlmMode,
        llm_model: trimmedLlmModel,
        dashboard_story_llm_enabled: dashboardStoryEnabled,
        dashboard_story_model: trimmedStoryModel,
        rollup_5m_enabled: rollup5mEnabled,
        rollup_15m_enabled: rollup15mEnabled,
        rollup_1h_enabled: rollup1hEnabled,
        rollup_4h_enabled: rollup4hEnabled,
        rollup_1d_enabled: rollup1dEnabled,
        rollup_1w_enabled: rollup1wEnabled,
        llm_timeout_seconds: parsedLlmTimeoutSeconds,
        context_summary_limit: parsedContextSummaryLimit,
        rollup_5m_context_summary_limit: parsedRollup5mContextSummaryLimit,
        rollup_15m_context_summary_limit: parsedRollup15mContextSummaryLimit,
        rollup_1h_context_summary_limit: parsedRollup1hContextSummaryLimit,
        rollup_4h_context_summary_limit: parsedRollup4hContextSummaryLimit,
        window_min_seconds: parsedWindowMinSeconds,
        window_max_seconds: parsedWindowMaxSeconds,
        window_token_limit: parsedWindowTokenLimit,
        rollup_5m_raw_token_limit: parsedRollup5mRawTokenLimit,
        preferred_local_port: parsedPreferredLocalPort,
      });
      if (useLocalQwen) {
        setIsPreparingModel(true);
        await prepareLocalModel();
        setIsPreparingModel(false);
      }
      setApiKey("");
      setSuccess(
        useLocalQwen
          ? "Local Qwen setup started. Workday Lens will use it once the model is ready."
          : mode === "setup"
          ? "Local settings saved. Workday Lens can start using them right away."
          : "Local settings updated. Workday Lens is now using the latest values.",
      );
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save the local settings.");
    } finally {
      setIsSaving(false);
      setIsPreparingModel(false);
    }
  }

  async function handlePrepareLocalModel() {
    setIsPreparingModel(true);
    setError(null);
    setSuccess(null);
    try {
      const status = await prepareLocalModel();
      setSuccess(status.running || status.ready ? status.message : "Local Qwen setup started.");
      await onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not prepare the local Qwen model.");
    } finally {
      setIsPreparingModel(false);
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
  const enabledRollups = [
    rollup5mEnabled,
    rollup15mEnabled,
    rollup1hEnabled,
    rollup4hEnabled,
    rollup1dEnabled,
    rollup1wEnabled,
  ].filter(Boolean).length;
  const analysisEngine = fakeLlmMode ? "fake" : llmProvider;
  const connectionStatus =
    analysisEngine === "fake"
      ? "Fake summaries"
      : analysisEngine === LOCAL_QWEN_PROVIDER
        ? setup.local_model.ready
          ? "Local Qwen"
          : "Qwen setup needed"
        : "OpenAI";
  const storyStatus = fakeLlmMode
    ? "Paused offline"
    : dashboardStoryEnabled
      ? analysisEngine === LOCAL_QWEN_PROVIDER
        ? "Local Qwen"
        : "Enabled"
      : "Off";
  const rollupSettings: Array<{
    label: string;
    description: string;
    checked: boolean;
    setChecked: (value: boolean) => void;
  }> = [
    {
      label: "5-minute rollups",
      description: "Combine minute summaries with raw accessibility context.",
      checked: rollup5mEnabled,
      setChecked: setRollup5mEnabled,
    },
    {
      label: "15-minute rollups",
      description: "Summarize completed 5-minute blocks.",
      checked: rollup15mEnabled,
      setChecked: setRollup15mEnabled,
    },
    {
      label: "1-hour rollups",
      description: "Summarize completed 15-minute blocks.",
      checked: rollup1hEnabled,
      setChecked: setRollup1hEnabled,
    },
    {
      label: "4-hour rollups",
      description: "Summarize completed hourly blocks.",
      checked: rollup4hEnabled,
      setChecked: setRollup4hEnabled,
    },
    {
      label: "Daily rollups",
      description: "Summarize completed 4-hour blocks for each day.",
      checked: rollup1dEnabled,
      setChecked: setRollup1dEnabled,
    },
    {
      label: "Weekly rollups",
      description: "Summarize completed day results into a week view.",
      checked: rollup1wEnabled,
      setChecked: setRollup1wEnabled,
    },
  ];

  return (
    <section className="setup-card">
      <div className="setup-card__header">
        <div className="setup-card__intro">
          <p className="section-kicker">{mode === "setup" ? "Local Setup" : "Local Settings"}</p>
          <h2>{mode === "setup" ? "Choose how this device should run Workday Lens." : "Settings that keep Workday Lens running."}</h2>
          <p>
            Manage your local profile, API key, model behavior, capture windows, summary hierarchy, and launcher port.
          </p>
          <p>{storageMessage(setup.openai_api_key_storage)}</p>
        </div>

        {mode === "manage" && onClose && (
          <button type="button" className="button button--ghost setup-card__close" onClick={onClose}>
            Close
          </button>
        )}
      </div>

      <div className="setup-card__status">
        <div className="setup-chip">
          <span className="setup-chip__label">Profile</span>
          <strong>{displayName || "Not set"}</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">API key</span>
          <strong>{analysisEngine === "openai" ? configuredKeyLabel : "Not required"}</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">Analysis</span>
          <strong>{connectionStatus}</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">Primary model</span>
          <strong>{llmModel || runtime.llm_model}</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">Local model</span>
          <strong>{setup.local_model.state.replaceAll("_", " ")}</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">Day Story</span>
          <strong>{storyStatus}</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">Rollups</span>
          <strong>{enabledRollups}/6 enabled</strong>
        </div>
        <div className="setup-chip">
          <span className="setup-chip__label">Launcher port</span>
          <strong>{preferredLocalPort}</strong>
        </div>
      </div>

      <form className="setup-form" onSubmit={handleSubmit}>
        <section className="settings-section settings-section--connection">
          <div className="settings-section__header">
            <h3>Connection</h3>
            <p>Profile name, keys, and operating mode for this machine.</p>
          </div>
          <div className="settings-grid settings-grid--two">
            <label className="form-field form-field--highlight">
              <span>
                Analysis engine
                <em>Required</em>
              </span>
              <select
                value={analysisEngine}
                onChange={(event) => {
                  const next = event.target.value;
                  if (next === "fake") {
                    setFakeLlmMode(true);
                    setDashboardStoryEnabled(false);
                    return;
                  }
                  setFakeLlmMode(false);
                  setLlmProvider(next as "openai" | "local_qwen35_4b");
                  if (next === LOCAL_QWEN_PROVIDER) {
                    setLlmModel(LOCAL_QWEN_DISPLAY_MODEL);
                  }
                }}
              >
                <option value="openai">OpenAI cloud models</option>
                <option value={LOCAL_QWEN_PROVIDER}>Local Qwen3.5 4B</option>
                <option value="fake">Fake demo summaries</option>
              </select>
              <small>Local Qwen runs text-only analysis through llama.cpp on this Mac.</small>
            </label>

            <label className="form-field form-field--highlight">
              <span>
                Display name
                <em>Required</em>
              </span>
              <input
                type="text"
                autoComplete="name"
                placeholder="Your name"
                value={displayName}
                onChange={(event) => setDisplayName(event.target.value)}
              />
              <small>Used in the sidebar, timeline, and personal insights.</small>
            </label>

            <label className="form-field form-field--highlight">
              <span>
                OpenAI API key
                <em>Live mode</em>
              </span>
              <input
                type="password"
                autoComplete="off"
                placeholder={setup.openai_api_key_configured ? "Enter a new key only if you want to rotate it" : "sk-..."}
                value={apiKey}
                disabled={analysisEngine !== "openai"}
                onChange={(event) => setApiKey(event.target.value)}
              />
              <small>
                {analysisEngine !== "openai"
                  ? "Not needed when using Local Qwen or fake demo mode."
                  : setup.openai_api_key_configured
                  ? "Leave this blank to keep the saved key."
                  : "Add a key for live analysis, or use offline mode without one."}
              </small>
            </label>
            <label className="settings-toggle">
              <span className="settings-toggle__copy">
                <strong>Daily story summaries</strong>
                <span>Add the higher-level headline and story pass to the dashboard.</span>
              </span>
              <input
                type="checkbox"
                checked={dashboardStoryEnabled}
                disabled={analysisEngine === "fake"}
                onChange={(event) => setDashboardStoryEnabled(event.target.checked)}
              />
              <span className="settings-toggle__switch" aria-hidden="true" />
            </label>
          </div>
        </section>

        <section className="settings-section settings-section--model">
          <div className="settings-section__header">
            <h3>Analysis Models</h3>
            <p>Core models used for window analysis and dashboard stories.</p>
          </div>
          <div className="settings-grid settings-grid--two">
            <label className="form-field">
              <span>Primary model</span>
              <input
                type="text"
                placeholder="gpt-5-nano"
                value={llmModel}
                disabled={analysisEngine === LOCAL_QWEN_PROVIDER}
                onChange={(event) => setLlmModel(event.target.value)}
              />
              <small>
                {analysisEngine === LOCAL_QWEN_PROVIDER
                  ? "Validated local setting from the Qwen3.5 4B benchmark."
                  : "Handles per-window activity analysis."}
              </small>
            </label>
            <label className="form-field">
              <span>Day story model</span>
              <input
                type="text"
                placeholder="Uses the primary model if left blank"
                value={analysisEngine === LOCAL_QWEN_PROVIDER ? LOCAL_QWEN_DISPLAY_MODEL : dashboardStoryModel}
                disabled={analysisEngine !== "openai"}
                onChange={(event) => setDashboardStoryModel(event.target.value)}
              />
              <small>
                {analysisEngine === "openai"
                  ? "Uses the 1d anchor plus selected 4h and 1h rollup cards."
                  : analysisEngine === LOCAL_QWEN_PROVIDER
                    ? "Uses the same local Qwen engine as the primary analysis pass."
                    : "Disabled in fake demo mode."}
              </small>
            </label>
          </div>
          {analysisEngine === LOCAL_QWEN_PROVIDER && (
            <div className="settings-local-model">
              <div>
                <strong>{setup.local_model.display_name}</strong>
                <span>{setup.local_model.message}</span>
                <small>
                  Runtime: {setup.local_model.runtime_model}. Context starts at {setup.local_model.ctx_size.toLocaleString()} and can grow to{" "}
                  {setup.local_model.max_ctx_size.toLocaleString()}.
                </small>
              </div>
              <button
                type="button"
                className="button button--secondary"
                onClick={handlePrepareLocalModel}
                disabled={isSaving || isPreparingModel || isRemovingKey || isReprocessing}
              >
                {isPreparingModel
                  ? "Preparing..."
                  : setup.local_model.running
                    ? "Check Local Qwen"
                    : setup.local_model.ready
                      ? "Start Local Qwen"
                      : "Download / Prepare Qwen"}
              </button>
            </div>
          )}
        </section>

        <section className="settings-section settings-section--summary">
          <div className="settings-section__header">
            <h3>Summary Hierarchy</h3>
            <p>These rollups power the timeline, day, week, and Gantt views.</p>
          </div>
          <div className="settings-toggle-list settings-toggle-list--rollups">
            {rollupSettings.map((item) => (
              <label className="settings-toggle settings-toggle--compact" key={item.label}>
                <span className="settings-toggle__copy">
                  <strong>{item.label}</strong>
                  <span>{item.description}</span>
                </span>
                <input
                  type="checkbox"
                  checked={item.checked}
                  onChange={(event) => item.setChecked(event.target.checked)}
                />
                <span className="settings-toggle__switch" aria-hidden="true" />
              </label>
            ))}
          </div>
        </section>

        <section className="settings-section settings-section--advanced">
          <div className="settings-section__header settings-section__header--with-action">
            <div>
              <h3>Advanced</h3>
              <p>Prompt, token, capture-window, and launcher tuning.</p>
            </div>
            <button
              type="button"
              className="settings-advanced-toggle"
              aria-expanded={showAdvanced}
              onClick={() => setShowAdvanced((current) => !current)}
            >
              {showAdvanced ? "Hide advanced" : "Show advanced"}
            </button>
          </div>
          {showAdvanced && (
            <div className="settings-advanced-body">
              <div className="settings-advanced-group">
                <h4>Prompt Tuning</h4>
                <div className="settings-grid settings-grid--three">
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
                    <small>How long Workday Lens waits for each request.</small>
                  </label>
                  <label className="form-field">
                    <span>1m context summaries</span>
                    <input
                      type="number"
                      min={0}
                      max={50}
                      step={1}
                      value={contextSummaryLimit}
                      onChange={(event) => setContextSummaryLimit(event.target.value)}
                    />
                    <small>Recent 1m summaries fed into the next 1m prompt.</small>
                  </label>
                  <label className="form-field">
                    <span>5m context summaries</span>
                    <input
                      type="number"
                      min={0}
                      max={50}
                      step={1}
                      value={rollup5mContextSummaryLimit}
                      onChange={(event) => setRollup5mContextSummaryLimit(event.target.value)}
                    />
                    <small>Recent 5m summaries fed into the next 5m prompt.</small>
                  </label>
                  <label className="form-field">
                    <span>15m context summaries</span>
                    <input
                      type="number"
                      min={0}
                      max={50}
                      step={1}
                      value={rollup15mContextSummaryLimit}
                      onChange={(event) => setRollup15mContextSummaryLimit(event.target.value)}
                    />
                    <small>Recent 15m summaries fed into the next 15m prompt.</small>
                  </label>
                  <label className="form-field">
                    <span>1h context summaries</span>
                    <input
                      type="number"
                      min={0}
                      max={50}
                      step={1}
                      value={rollup1hContextSummaryLimit}
                      onChange={(event) => setRollup1hContextSummaryLimit(event.target.value)}
                    />
                    <small>Recent 1h summaries fed into the next 1h prompt.</small>
                  </label>
                  <label className="form-field">
                    <span>4h context summaries</span>
                    <input
                      type="number"
                      min={0}
                      max={50}
                      step={1}
                      value={rollup4hContextSummaryLimit}
                      onChange={(event) => setRollup4hContextSummaryLimit(event.target.value)}
                    />
                    <small>Recent 4h summaries fed into the next 4h prompt.</small>
                  </label>
                  <label className="form-field">
                    <span>1m token limit</span>
                    <input
                      type="number"
                      min={100}
                      max={64000}
                      step={50}
                      value={windowTokenLimit}
                      onChange={(event) => setWindowTokenLimit(event.target.value)}
                    />
                    <small>Large 1m transcripts split into ordered LLM chunks.</small>
                  </label>
                  <label className="form-field">
                    <span>5m raw transcript token limit</span>
                    <input
                      type="number"
                      min={0}
                      max={64000}
                      step={100}
                      value={rollup5mRawTokenLimit}
                      onChange={(event) => setRollup5mRawTokenLimit(event.target.value)}
                    />
                    <small>1m raw accessibility blocks attached to each 5m prompt; 0 disables raw text.</small>
                  </label>
                </div>
              </div>

              <div className="settings-advanced-group">
                <h4>Capture And Launcher</h4>
                <p className="settings-advanced-note">
                  Window min and max are set to 60 seconds so the raw timeline cards stay true one-minute cards.
                </p>
                <div className="settings-grid settings-grid--three">
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
                    <small>Use 60 for one-minute raw cards.</small>
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
                    <small>Use 60 so one capture window cannot grow past one minute.</small>
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
                    <small>Used the next time the services start.</small>
                  </label>
                </div>
              </div>
            </div>
          )}
        </section>

        {(error || success) && (
          <p className={error ? "form-message form-message--error" : "form-message form-message--success"}>
            {error || success}
          </p>
        )}

        <div className="setup-form__actions">
          <button className="button button--primary" type="submit" disabled={isSaving || isRemovingKey || isReprocessing || isPreparingModel}>
            {isSaving || isPreparingModel ? "Saving..." : mode === "setup" ? "Save Local Setup" : "Save Settings"}
          </button>

          {mode === "manage" && (
            <button
              type="button"
              className="button button--secondary"
              onClick={handleReprocessToday}
              disabled={isSaving || isRemovingKey || isReprocessing || isPreparingModel}
            >
              {isReprocessing ? "Queueing..." : "Reprocess Today"}
            </button>
          )}

          {setup.openai_api_key_configured && (
            <button
              type="button"
              className="button button--danger"
              onClick={handleRemoveApiKey}
              disabled={isSaving || isRemovingKey || isReprocessing || isPreparingModel}
            >
              {isRemovingKey ? "Removing..." : "Remove Saved API Key"}
            </button>
          )}
        </div>
      </form>
    </section>
  );
}
