import { NextResponse } from "next/server";

export const dynamic = "force-dynamic";

const FALLBACK_API_BASE_URL = "http://127.0.0.1:8000/api/v1";

function normalizeApiBaseUrl(value?: string) {
  const normalized = value?.trim();
  if (!normalized) {
    return FALLBACK_API_BASE_URL;
  }
  return normalized.replace(/\/+$/, "");
}

export function GET() {
  return NextResponse.json({
    apiBaseUrl: normalizeApiBaseUrl(process.env.WFHS_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL),
  });
}
