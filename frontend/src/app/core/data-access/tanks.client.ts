/** Cliente HTTP para la red estratégica de tanques de cosecha de lluvia (/api/alerts/tanks). */

export type TankRole = 'dual' | 'drought' | 'fire';

export interface DroughtLinkTarget {
  id: string;
  name_es: string;
  name_en: string;
  distance_km: number;
  elevation_diff_m: number;
  gravity_fed: boolean;
  drought_score: number;
  dry_days_60d: number;
  rain_30d_mm: number;
  lon: number;
  lat: number;
}

export interface FireLinkTarget {
  id: string;
  zone_label: string;
  distance_km: number;
  elevation_diff_m: number;
  gravity_fed: boolean;
  hotspots_count: number;
  max_frp_mw: number;
  latest_date: string;
  lon: number;
  lat: number;
}

export interface StrategicTankNode {
  id: string;
  name_es: string;
  name_en: string;
  subbasin_id: string;
  subbasin_name_es: string;
  subbasin_name_en: string;
  subsystem: 'north' | 'central' | 'south';
  role: TankRole;
  priority_score: number;
  lon: number;
  lat: number;
  elevation_m: number;
  slope_deg: number;
  flow_acc_cells: number;
  twi: number;
  subbasin_steep_gt25_pct: number;
  rain_7d_mm: number;
  rain_30d_mm: number;
  rain_60d_mm: number;
  max_24h_30d_mm: number;
  dry_days_60d: number;
  effective_capture_ha: number;
  runoff_coeff: number;
  harvest_30d_m3: number;
  storm_capture_m3: number;
  recommended_capacity_m3: number;
  gravity_ready: boolean;
  nearby_drought_targets: DroughtLinkTarget[];
  nearby_fire_targets: FireLinkTarget[];
}

export interface DroughtTargetSummary {
  id: string;
  name_es: string;
  name_en: string;
  lon: number;
  lat: number;
  elevation_m: number;
  subbasin_id: string;
  rain_30d_mm: number;
  dry_days_60d: number;
  max_dry_spell_days: number;
  drought_score: number;
}

export interface FireClusterSummary {
  id: string;
  lon: number;
  lat: number;
  elevation_m: number | null;
  subbasin_id: string | null;
  zone_label: string;
  hotspots_count: number;
  max_frp_mw: number;
  latest_date: string;
  severity_score: number;
}

export interface TankNetworkAnalysis {
  headline: string;
  executive_summary: string;
  drought_strategy: string;
  wildfire_strategy: string;
  priority_actions: { tank_id: string; title: string; impact: string }[];
  data_caveats: string[];
}

export interface TankNetworkResponse {
  generated_at: string;
  sources: {
    dem: string;
    precip: string;
    fires: string;
    districts: string;
  };
  summary: {
    tanks_count: number;
    total_storage_m3: number;
    estimated_30d_harvest_m3: number;
    drought_targets_covered: number;
    drought_targets_total: number;
    fire_clusters_covered: number;
    fire_clusters_total: number;
    fire_hotspots_covered: number;
    fire_hotspots_total: number;
    gravity_fed_tanks: number;
  };
  tanks: StrategicTankNode[];
  drought_targets: DroughtTargetSummary[];
  fire_clusters: FireClusterSummary[];
  analysis: TankNetworkAnalysis;
  analysis_source: 'gemini' | 'hydro_deterministic';
  llm_model: string | null;
  analysis_note: string;
  focus_question?: string | null;
}

export async function fetchTankNetwork(apiBaseUrl: string, refresh = false): Promise<TankNetworkResponse> {
  const qs = refresh ? '?refresh=true' : '';
  const res = await fetch(`${apiBaseUrl}/alerts/tanks${qs}`);
  if (!res.ok) {
    throw new Error(`Tank network error (${res.status})`);
  }
  return (await res.json()) as TankNetworkResponse;
}

export async function analyzeTankNetwork(
  apiBaseUrl: string,
  focus: string | null,
  lang: 'es' | 'en',
): Promise<TankNetworkResponse> {
  const res = await fetch(`${apiBaseUrl}/alerts/tanks/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ focus, lang }),
  });
  if (!res.ok) {
    throw new Error(`Tank analysis error (${res.status})`);
  }
  return (await res.json()) as TankNetworkResponse;
}
