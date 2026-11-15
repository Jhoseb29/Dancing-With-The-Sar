/** Cliente HTTP para Qucha-SAR (`basin_risk`: DEM Copernicus 30 m, GPM/POWER, OPERA, NISAR). */

export type AlertLevel = 'verde' | 'amarillo' | 'naranja' | 'rojo';
export type SubsystemId = 'north' | 'central' | 'south';

export interface I18nPair {
  es: string;
  en: string;
}

export interface SubsystemSummary {
  id: SubsystemId;
  name: I18nPair;
  focus: I18nPair;
  level: AlertLevel;
  max_score: number;
  subbasin_ids: string[];
  summary_metric: I18nPair;
}

export interface BasinZoneRisk {
  id: string;
  subsystem: SubsystemId;
  downstream_target?: string | null;
  name: I18nPair;
  description: I18nPair;
  hazard: 'slope_mudflow' | 'flood_saturation' | 'water_balance';
  area_km2: number;
  bbox: [number, number, number, number];
  centroid: [number, number];
  geometry: { type: 'Polygon' | 'MultiPolygon'; coordinates: unknown };
  score: number;
  level: AlertLevel;
  dominant_driver?: I18nPair;
  terrain: {
    elevation_min_m?: number;
    elevation_mean_m?: number;
    elevation_max_m?: number;
    slope_mean_deg?: number;
    slope_p90_deg?: number;
    steep_pct_gt20?: number;
    steep_pct_gt25?: number;
    steep_pct_gt30?: number;
    low_slope_pct_lt5?: number;
    above_2750_pct?: number;
    twi_p90?: number;
    torrent_density_pct?: number;
  };
  precipitation: {
    source?: string;
    imerg_spatial_active?: boolean;
    latest_mm: number;
    sum_7d_mm: number;
    sum_30d_mm: number;
    max_24h_30d_mm: number;
  };
  fire_hotspots_30d: number | null;
  surface_water?: {
    opera_water_km2: number;
    baseline_dry_km2: number;
    water_anomaly_km2: number;
    sar_change_index: number | null;
    note?: string;
  };
  drivers: { label_es: string; label_en: string; value: string }[];
  caveats: string[];
}

export interface PrecipPoint {
  date: string;
  mm: number;
}

export interface NisarGranuleSummary {
  title: string;
  date: string;
  product: string;
  maturity: string;
  collection: string;
  track: string;
  frame: string;
  direction: string;
  pol: string;
}

export interface BasinOverview {
  generated_at: string;
  basin: string;
  overall: {
    level: AlertLevel;
    max_score: number;
    priority_zone_id: string;
    priority_zone_name: I18nPair;
    cota_urbana_m: number;
  };
  subsystems: SubsystemSummary[];
  zones: BasinZoneRisk[];
  precipitation: {
    source: string;
    gpm_cmr: {
      earthdata_configured: boolean;
      earthdata_auth_status?: 'ok' | 'password_reset_required' | 'invalid_credentials' | 'unconfigured' | 'unreachable';
      gesdisc_eula_status?: string;
      eula_resolution_url?: string | null;
      collections: Record<string, { available_hits?: number; latest_start?: string | null; latest_title?: string | null; error?: string }>;
    };
    series: PrecipPoint[];
  };
  nisar: {
    source: string;
    retrieved_at: string;
    total_granules: number;
    by_product: Record<string, number>;
    by_maturity: Record<string, number>;
    tracks_frames: string[];
    verified_gibs_dates: string[];
    opera_dswx_dates?: string[];
    sar_change_default?: {
      before_day: string;
      after_day: string;
      sensor: string;
    } | null;
    latest_granule: NisarGranuleSummary | null;
    granules: NisarGranuleSummary[];
  };
  satellite_processing?: {
    scope: string;
    opera_dswx: {
      date: string;
      baseline_date?: string | null;
      open_water_km2: number;
      inundated_veg_km2: number;
      total_water_km2: number;
      by_zone_km2: Record<string, number>;
    } | null;
    nisar_basin: {
      date: string;
      basin_coverage_pct: number;
      classes_pct: {
        specular_water: number;
        vegetation_canopy: number;
        urban_double_bounce: number;
        bare_soil: number;
      };
    } | null;
    anchor_harness: {
      status: 'ready' | 'standby';
      runs_count: number;
      latest_metrics: {
        granule_id?: string;
        date?: string;
        classes_pct?: Record<string, number>;
      } | null;
    };
  };
  sources: Record<string, string>;
}

export interface BasinPointDiagnostics {
  inside_basin: boolean;
  lon: number;
  lat: number;
  zone?: { id: string; subsystem?: SubsystemId; name: I18nPair } | null;
  dem?: {
    elevation_m: number;
    slope_deg: number;
    tpi_m: number;
    above_cota_2750: boolean;
    drainage_channel_hint: boolean;
    sar_terrain_caution: boolean;
    hydro?: {
      subbasin_id: string | null;
      twi: number | null;
      flow_acc_cells: number | null;
      in_torrent_network: boolean;
    };
  };
  precipitation?: {
    latest_date: string | null;
    latest_mm: number;
    sum_7d_mm: number;
    sum_30d_mm: number;
    max_24h_30d_mm: number;
  } | null;
  source?: string;
}

export async function fetchBasinOverview(apiBaseUrl: string, days = 45): Promise<BasinOverview> {
  const res = await fetch(`${apiBaseUrl}/basin/overview?days=${days}`);
  if (!res.ok) {
    throw new Error(`Basin overview respondió ${res.status}`);
  }
  return (await res.json()) as BasinOverview;
}

export async function fetchBasinPoint(apiBaseUrl: string, lon: number, lat: number): Promise<BasinPointDiagnostics> {
  const res = await fetch(`${apiBaseUrl}/basin/point?lon=${encodeURIComponent(lon)}&lat=${encodeURIComponent(lat)}`);
  if (!res.ok) {
    throw new Error(`Basin point respondió ${res.status}`);
  }
  return (await res.json()) as BasinPointDiagnostics;
}

export function basinBulletinUrl(apiBaseUrl: string): string {
  return `${apiBaseUrl}/basin/bulletin`;
}
