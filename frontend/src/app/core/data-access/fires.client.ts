import type { MapPoints } from '../map-engine/geo-engine';

/** Contratos de backend/shared/schemas/fire-stats.schema.json (OpenSpec 09). */

export interface FireDay {
  place: string;
  date: string;
  count: number;
  source: string;
  retrieved_at: string;
  geojson: MapPoints;
}

export interface FireStats {
  place: string;
  start: string;
  end: string;
  total: number;
  monthly: { month: string; count: number }[];
  peak_day: { date: string; count: number } | null;
  source: string;
  retrieved_at: string;
}

export type FireResult<T> = { ok: true; day: T } | { ok: false; code: string; message: string };

async function getJson<T>(url: string): Promise<{ ok: true; body: T } | { ok: false; code: string; message: string }> {
  try {
    const response = await fetch(url, { headers: { Accept: 'application/json' } });
    const contentType = response.headers.get('content-type') ?? '';
    if (!contentType.includes('application/json')) {
      return { ok: false, code: 'backend_unavailable', message: `HTTP ${response.status}` };
    }
    const body = await response.json();
    if (!response.ok) {
      const detail = (body as { detail?: { code?: string; message?: string } }).detail ?? {};
      return { ok: false, code: detail.code ?? 'error', message: detail.message ?? `HTTP ${response.status}` };
    }
    return { ok: true, body: body as T };
  } catch (err) {
    return { ok: false, code: 'backend_unavailable', message: err instanceof Error ? err.message : String(err) };
  }
}

export async function fetchFireDay(apiBaseUrl: string, placeId: string, date: string): Promise<FireResult<FireDay>> {
  const params = new URLSearchParams({ place: placeId, date });
  const result = await getJson<FireDay>(`${apiBaseUrl}/events/fires?${params}`);
  return result.ok ? { ok: true, day: result.body } : result;
}

export async function fetchFireStats(apiBaseUrl: string, placeId: string, start: string, end: string): Promise<FireResult<FireStats>> {
  const params = new URLSearchParams({ place: placeId, start, end });
  const result = await getJson<FireStats>(`${apiBaseUrl}/events/fires/stats?${params}`);
  return result.ok ? { ok: true, day: result.body } : result;
}
