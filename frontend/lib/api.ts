import { DEFAULT_API_BASE_URL } from "./config";

let apiBaseUrlPromise: Promise<string> | null = null;

function normalizeApiBaseUrl(value: string) {
  return value.trim().replace(/\/+$/, "");
}

async function resolveApiBaseUrl(): Promise<string> {
  if (typeof window === "undefined") {
    return normalizeApiBaseUrl(DEFAULT_API_BASE_URL);
  }

  if (!apiBaseUrlPromise) {
    apiBaseUrlPromise = fetch("/api/runtime-config", { cache: "no-store" })
      .then(async (resp) => {
        if (!resp.ok) {
          throw new Error(resp.statusText);
        }
        const payload = (await resp.json()) as { apiBaseUrl?: unknown };
        return typeof payload.apiBaseUrl === "string" && payload.apiBaseUrl.trim()
          ? normalizeApiBaseUrl(payload.apiBaseUrl)
          : normalizeApiBaseUrl(DEFAULT_API_BASE_URL);
      })
      .catch(() => normalizeApiBaseUrl(DEFAULT_API_BASE_URL));
  }

  return apiBaseUrlPromise;
}

async function request<T>(input: string, init?: RequestInit): Promise<T> {
  const apiBaseUrl = await resolveApiBaseUrl();
  const resp = await fetch(`${apiBaseUrl}${input}`, {
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

export interface RuntimeSettingsResponse {
  fake_llm_mode: boolean;
  llm_model: string;
  dashboard_story_llm_enabled: boolean;
  dashboard_story_model: string;
  dashboard_story_segment_limit: number;
  llm_timeout_seconds: number;
  context_summary_limit: number;
  window_min_seconds: number;
  window_max_seconds: number;
  window_token_limit: number;
  preferred_local_port: number;
}

export interface SetupStatusResponse {
  needs_setup: boolean;
  openai_api_key_configured: boolean;
  openai_api_key_last4?: string | null;
  openai_api_key_storage: string;
  runtime_settings: RuntimeSettingsResponse;
  reanalysis_queued_windows: number;
}

export interface RuntimeSettingsUpdateRequest {
  openai_api_key?: string;
  fake_llm_mode?: boolean;
  llm_model?: string;
  dashboard_story_llm_enabled?: boolean;
  dashboard_story_model?: string;
  dashboard_story_segment_limit?: number;
  llm_timeout_seconds?: number;
  context_summary_limit?: number;
  window_min_seconds?: number;
  window_max_seconds?: number;
  window_token_limit?: number;
  preferred_local_port?: number;
}

export async function fetchActivity(): Promise<ActivityResponse> {
  return request<ActivityResponse>("/employee/activity");
}

export async function fetchActivityDashboard(day?: string): Promise<ActivityDashboardResponse> {
  const params = day ? `?day=${encodeURIComponent(day)}` : "";
  return request<ActivityDashboardResponse>(`/activity/dashboard${params}`);
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

export async function deleteRuntimeApiKey(): Promise<SetupStatusResponse> {
  return request<SetupStatusResponse>("/setup/api-key", {
    method: "DELETE",
  });
}
