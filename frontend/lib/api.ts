import { API_BASE_URL } from "./config";

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE_URL}${input}`, {
    headers: {
      "Content-Type": "application/json",
    },
    ...init,
  });
  if (!resp.ok) {
    const detail = await resp.text();
    throw new Error(detail || resp.statusText);
  }
  if (resp.status === 204) {
    return undefined as T;
  }
  return (await resp.json()) as T;
}

export interface ActivityItem {
  window_id: string;
  captured_from: string;
  captured_to: string;
  raw_excerpt: string;
  llm_summary: string;
  verdict: "queued" | "processing" | "processed" | "violation" | "pending_llm";
  confidence: number;
}

export interface ActivityResponse {
  data: ActivityItem[];
  next_cursor?: string | null;
}

export interface ActivitySegment {
  window_id: string;
  captured_from: string;
  captured_to: string;
  duration_minutes: number;
  status: "queued" | "processing" | "processed" | "violation" | "pending_llm";
  headline: string;
  summary: string;
  goal: string;
  project: string;
  activity_type: string;
  activity_label: string;
  focus_state: string;
  focus_label: string;
  next_step: string;
  raw_excerpt: string;
  confidence: number;
  model_name?: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
}

export interface ActivityRollupItem {
  id: string;
  level: string;
  captured_from: string;
  captured_to: string;
  duration_minutes: number;
  status: "queued" | "processing" | "processed" | "violation" | "pending_llm";
  headline: string;
  summary: string;
  dominant_goal: string;
  project: string;
  activity_type: string;
  activity_label: string;
  focus_state: string;
  focus_label: string;
  secondary_goals: string[];
  important_intervals: string[];
  ignored_noise?: string | null;
  confidence: number;
  source_count: number;
  model_name?: string | null;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
}

export interface ActivityRollupResponse {
  level: string;
  data: ActivityRollupItem[];
}

export interface ActivityLLMDebugResponse {
  id: string;
  level: string;
  captured_from: string;
  captured_to: string;
  model_name?: string | null;
  prompt_text: string;
  response_text: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  reconstructed: boolean;
  notes: string[];
}

export interface CaptureMessageItem {
  id: number;
  session_id: string;
  source?: string | null;
  text: string;
  captured_at: string;
  window_id?: string | null;
}

export interface CaptureMessageResponse {
  data: CaptureMessageItem[];
  latest_id?: number | null;
  has_more: boolean;
}

export interface ActivityGanttBlock {
  id: string;
  lane: "deep" | "meetings" | "comms" | "breaks" | string;
  captured_from: string;
  captured_to: string;
  label: string;
  summary: string;
  project: string;
  activity_type: string;
  focus_state: string;
  source_level: string;
  source_ids: string[];
  priority_score: number;
  reason: string;
  is_marker: boolean;
  is_gap: boolean;
  evidence: string;
  visual_group: string;
  visual_tone: string;
}

export interface ActivityGanttResponse {
  mode: string;
  captured_from: string;
  captured_to: string;
  status: string;
  model_name?: string | null;
  generated_at?: string | null;
  blocks: ActivityGanttBlock[];
}

export interface ActivityReprocessResponse {
  level: string;
  mode: "all" | "pending";
  queued_windows: number;
  queued_rollups: number;
  invalidated_rollups: number;
}

export interface ActivityBreakdownItem {
  label: string;
  minutes: number;
  segments: number;
}

export interface ActivityDashboardSummary {
  total_tracked_minutes: number;
  focused_minutes: number;
  activity_switches: number;
  active_projects: number;
  captured_windows: number;
  pending_windows: number;
  longest_focus_block_minutes: number;
}

export interface ActivityDashboardResponse {
  date: string;
  summary: ActivityDashboardSummary;
  current_intent?: ActivitySegment | null;
  story_headline?: string | null;
  story_summary?: string | null;
  story_model_name?: string | null;
  breakdown: ActivityBreakdownItem[];
  project_breakdown: ActivityBreakdownItem[];
  segments: ActivitySegment[];
}

export interface PolicyResponse {
  id: string;
  text: string;
  examples: string[];
  active: boolean;
  created_at: string;
  updated_at: string;
}

export interface PolicyCreate {
  text: string;
  examples?: string[];
}

export interface PolicyUpdate {
  text?: string;
  examples?: string[];
  active?: boolean;
}

export interface ViolationItem {
  window_id: string;
  captured_from: string;
  captured_to: string;
  title: string;
  detail: string;
  created_at: string;
}

export interface ViolationResponse {
  data: ViolationItem[];
  next_cursor?: string | null;
}

export interface MetricsResponse {
  queue_depth: number;
  pending_windows: number;
  violations_today: number;
  last_worker_run?: string | null;
}

export interface ResourceProcessSnapshot {
  role: string;
  name: string;
  pid?: number | null;
  cpu_percent: number;
  memory_mb: number;
  command?: string | null;
  running: boolean;
}

export interface ResourceBacklogSnapshot {
  queue_depth: number;
  queued_windows: number;
  processing_windows: number;
  pending_windows: number;
  active_windows: number;
  active_window_tokens: number;
  active_window_minutes: number;
  queued_rollups: number;
  processing_rollups: number;
  pending_rollups: number;
  active_rollups: number;
}

export interface ResourceThroughputSnapshot {
  recent_window_runs: number;
  avg_window_latency_ms: number;
  avg_window_tokens: number;
  avg_prompt_tokens_per_second: number;
  avg_completion_tokens_per_second: number;
  avg_total_tokens_per_second: number;
  windows_per_minute_capacity: number;
  capture_windows_per_minute: number;
  keep_up_ratio: number;
  estimated_backlog_change_per_hour: number;
  estimated_backlog_drain_minutes?: number | null;
}

export interface LocalQwenCompletionMetric {
  started_at: string;
  finished_at: string;
  ctx_size: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  latency_ms: number;
  prompt_eval_ms: number;
  generation_ms: number;
  prompt_tokens_per_second: number;
  completion_tokens_per_second: number;
  total_tokens_per_second: number;
  compacted: boolean;
}

export interface ResourceQwenSnapshot {
  provider: string;
  display_name: string;
  runtime_model: string;
  state: string;
  running: boolean;
  ready: boolean;
  server_url?: string | null;
  ctx_size: number;
  max_ctx_size: number;
  predict_tokens: number;
  threads: number;
  threads_batch: number;
  cache_ram_mb: number;
  pid?: number | null;
  cpu_percent: number;
  memory_mb: number;
  recent_prompt_tokens_per_second: number;
  recent_completion_tokens_per_second: number;
  recent_total_tokens_per_second: number;
  recent_latency_ms: number;
}

export interface ResourceThermalSnapshot {
  state: string;
  rank: number;
  source: string;
  captured_at?: string | null;
  stale_seconds?: number | null;
}

export interface ResourceMonitorResponse {
  captured_at: string;
  qwen: ResourceQwenSnapshot;
  thermal: ResourceThermalSnapshot;
  processes: ResourceProcessSnapshot[];
  backlog: ResourceBacklogSnapshot;
  throughput: ResourceThroughputSnapshot;
  recent_completions: LocalQwenCompletionMetric[];
  recommendations: string[];
}

export interface RuntimeSettingsResponse {
  display_name: string;
  llm_provider: "openai" | "local_qwen35_4b";
  fake_llm_mode: boolean;
  llm_model: string;
  dashboard_story_llm_enabled: boolean;
  dashboard_story_model: string;
  llm_timeout_seconds: number;
  context_summary_limit: number;
  rollup_5m_context_summary_limit: number;
  rollup_15m_context_summary_limit: number;
  rollup_1h_context_summary_limit: number;
  rollup_4h_context_summary_limit: number;
  window_min_seconds: number;
  window_max_seconds: number;
  window_token_limit: number;
  rollup_5m_raw_token_limit: number;
  rollup_5m_enabled: boolean;
  rollup_15m_enabled: boolean;
  rollup_1h_enabled: boolean;
  rollup_4h_enabled: boolean;
  rollup_1d_enabled: boolean;
  rollup_1w_enabled: boolean;
  preferred_local_port: number;
}

export interface SetupStatusResponse {
  needs_setup: boolean;
  openai_api_key_configured: boolean;
  openai_api_key_last4?: string | null;
  openai_api_key_storage: string;
  runtime_settings: RuntimeSettingsResponse;
  local_model: LocalModelStatusResponse;
  reanalysis_queued_windows: number;
}

export interface RuntimeSettingsUpdateRequest {
  openai_api_key?: string;
  display_name?: string;
  llm_provider?: "openai" | "local_qwen35_4b";
  fake_llm_mode?: boolean;
  llm_model?: string;
  dashboard_story_llm_enabled?: boolean;
  dashboard_story_model?: string;
  llm_timeout_seconds?: number;
  context_summary_limit?: number;
  rollup_5m_context_summary_limit?: number;
  rollup_15m_context_summary_limit?: number;
  rollup_1h_context_summary_limit?: number;
  rollup_4h_context_summary_limit?: number;
  window_min_seconds?: number;
  window_max_seconds?: number;
  window_token_limit?: number;
  rollup_5m_raw_token_limit?: number;
  rollup_5m_enabled?: boolean;
  rollup_15m_enabled?: boolean;
  rollup_1h_enabled?: boolean;
  rollup_4h_enabled?: boolean;
  rollup_1d_enabled?: boolean;
  rollup_1w_enabled?: boolean;
  preferred_local_port?: number;
}

export interface LocalModelStatusResponse {
  provider: string;
  display_name: string;
  runtime_model: string;
  prompt_style: string;
  state: string;
  message: string;
  ready: boolean;
  running: boolean;
  server_url?: string | null;
  ctx_size: number;
  max_ctx_size: number;
  predict_tokens: number;
  threads: number;
  threads_batch: number;
  cache_ram_mb: number;
  model_path?: string | null;
  llama_server_path?: string | null;
  cache_root: string;
  hf_home: string;
  last_error?: string | null;
}

export async function fetchActivity(): Promise<ActivityResponse> {
  return request<ActivityResponse>("/employee/activity");
}

export async function fetchActivityDashboard(day?: string): Promise<ActivityDashboardResponse> {
  const params = day ? `?day=${encodeURIComponent(day)}` : "";
  return request<ActivityDashboardResponse>(`/activity/dashboard${params}`);
}

export async function fetchActivityRollups(level: string, day: string): Promise<ActivityRollupResponse> {
  const params = new URLSearchParams({ level, day });
  return request<ActivityRollupResponse>(`/activity/rollups?${params.toString()}`);
}

export async function fetchActivityRollupsRange(level: string, from: string, to: string): Promise<ActivityRollupResponse> {
  const params = new URLSearchParams({ level, from, to });
  return request<ActivityRollupResponse>(`/activity/rollups?${params.toString()}`);
}

export async function fetchActivityLLMDebug(level: string, id: string): Promise<ActivityLLMDebugResponse> {
  const params = new URLSearchParams({ level, id });
  return request<ActivityLLMDebugResponse>(`/activity/debug/llm?${params.toString()}`);
}

export async function fetchCaptureMessages(options: {
  limit?: number;
  afterId?: number | null;
  source?: string;
  q?: string;
} = {}): Promise<CaptureMessageResponse> {
  const params = new URLSearchParams();
  params.set("limit", String(options.limit ?? 200));
  if (options.afterId != null) {
    params.set("after_id", String(options.afterId));
  }
  if (options.source?.trim()) {
    params.set("source", options.source.trim());
  }
  if (options.q?.trim()) {
    params.set("q", options.q.trim());
  }
  return request<CaptureMessageResponse>(`/capture/messages?${params.toString()}`);
}

export async function fetchActivityGantt(mode: string, from: string, to: string): Promise<ActivityGanttResponse> {
  const params = new URLSearchParams({ mode, from, to });
  return request<ActivityGanttResponse>(`/activity/gantt?${params.toString()}`);
}

export async function reprocessActivityRange(
  level: string,
  from: string,
  to: string,
  mode: "all" | "pending" = "all",
): Promise<ActivityReprocessResponse> {
  return request<ActivityReprocessResponse>("/activity/reprocess", {
    method: "POST",
    body: JSON.stringify({ level, from, to, mode }),
  });
}

export async function fetchPolicies(): Promise<PolicyResponse[]> {
  return request<PolicyResponse[]>("/policy");
}

export async function createPolicy(body: PolicyCreate): Promise<PolicyResponse> {
  return request<PolicyResponse>("/policy", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export async function updatePolicy(policyId: string, body: PolicyUpdate): Promise<PolicyResponse> {
  return request<PolicyResponse>(`/policy/${policyId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function archivePolicy(policyId: string): Promise<void> {
  await request<void>(`/policy/${policyId}`, {
    method: "DELETE",
  });
}

export async function fetchViolations(): Promise<ViolationResponse> {
  return request<ViolationResponse>("/admin/violations");
}

export async function fetchMetrics(): Promise<MetricsResponse> {
  return request<MetricsResponse>("/metrics");
}

export async function fetchResourceMonitor(): Promise<ResourceMonitorResponse> {
  return request<ResourceMonitorResponse>("/resources/monitor");
}

export async function fetchSetupStatus(): Promise<SetupStatusResponse> {
  return request<SetupStatusResponse>("/setup/status");
}

export async function updateRuntimeSettings(body: RuntimeSettingsUpdateRequest): Promise<SetupStatusResponse> {
  return request<SetupStatusResponse>("/setup/config", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export async function reprocessTodayActivity(): Promise<SetupStatusResponse> {
  return request<SetupStatusResponse>("/setup/reprocess-today", {
    method: "POST",
  });
}

export async function prepareLocalModel(): Promise<LocalModelStatusResponse> {
  return request<LocalModelStatusResponse>("/setup/local-model/prepare", {
    method: "POST",
  });
}

export async function fetchLocalModelStatus(): Promise<LocalModelStatusResponse> {
  return request<LocalModelStatusResponse>("/setup/local-model/status");
}

export async function deleteRuntimeApiKey(): Promise<SetupStatusResponse> {
  return request<SetupStatusResponse>("/setup/api-key", {
    method: "DELETE",
  });
}
