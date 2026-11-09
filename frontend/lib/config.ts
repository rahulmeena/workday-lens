export const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";

export const DEFAULT_POLL_INTERVAL = Number(process.env.NEXT_PUBLIC_POLL_INTERVAL_MS ?? 60_000);

export const DEMO_MODE = process.env.NEXT_PUBLIC_DEMO_MODE === "true";

export function initialDayValue(): string {
  const date = new Date();
  if (DEMO_MODE) date.setDate(date.getDate() - 1);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}
