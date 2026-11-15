/**
 * Contrato del harness NISAR (nisar-harness/lib/interpreter.py → interpretacion_didactica_nisar.json)
 * y de los eventos de progreso que re-emite backend/compute-py/src/modules/harness.
 */

export type AlertLevel = 'verde' | 'amarillo' | 'naranja' | 'rojo' | 'sin_datos';

export type PayloadStatus = 'complete' | 'data_only' | 'needs_clarification' | 'no_data';

export interface HarnessChat {
  message: string;
  alert_level: AlertLevel;
  alert_reason: string;
  highlights: string[];
  follow_up_questions?: string[];
}

export interface HarnessMedia {
  format: 'rgb' | 'classes' | 'png' | 'histogram' | 'tif' | 'kml' | 'geojson';
  kind: 'image' | 'download' | 'geojson';
  overlay: boolean;
  title: string;
  caption: string;
  date: string;
  /** Relativa a la carpeta de la corrida. */
  path: string;
  bounds_lonlat: [number, number, number, number] | null;
}

export interface HarnessQuery {
  text: string;
  place_name: string | null;
  bbox: [number, number, number, number] | null;
  theme: string;
  start_date: string;
  end_date: string;
}

export interface HarnessDateMetrics {
  date: string;
  season: string | null;
  scattering_pct: Record<string, number>;
  mean_db: number | null;
  rvi_mean: number | null;
  valid_pixels_pct: number | null;
  pixel_spacing_m: number | null;
}

export interface HarnessPayload {
  schema_version: string;
  run_id: string;
  status: PayloadStatus;
  query: HarnessQuery | null;
  chat: HarnessChat | null;
  lesson_markdown: string | null;
  metrics?: HarnessDateMetrics | null;
  time_series?: HarnessDateMetrics[];
  change?: {
    from_date: string;
    to_date: string;
    significant_changes: string[];
    caveats: string[];
  } | null;
  media: HarnessMedia[];
  globe?: HarnessGlobe | null;
}

export type GlobeLayerId = 'objects' | 'classes' | 'co' | 'cross';

/** Una toma (fecha) del análisis: grilla de datos que el globo colorea en el navegador. */
export interface GlobeTake {
  date: string;
  granule_id: string;
  orbit: string | null;
  /** Ruta (relativa a la corrida) del *_globe.json. */
  data: string;
  /** Ruta del *_objects.geojson (polígonos por clase), si se generó. */
  objects?: string | null;
  scattering_pct: Record<string, number>;
  classification_method: string | null;
}

export interface HotspotKindSummary {
  cells: number;
  area_km2: number;
  pct_of_area: number;
}

export interface HotspotSummary {
  from_date: string;
  to_date: string;
  theme: string;
  cell_area_km2: number;
  kinds: Record<string, HotspotKindSummary>;
  points_shown: number;
  points_total: number;
}

export interface HarnessGlobe {
  bbox: [number, number, number, number];
  takes: GlobeTake[];
  hotspots: string | null;
  hotspots_summary: HotspotSummary | null;
  layers: Record<GlobeLayerId | 'hotspots', { title: string; caption: string }>;
}

/** Contenido de *_globe.json (nisar-harness/lib/globe.py). */
export interface GlobeGrid {
  version: number;
  date: string;
  bbox: [number, number, number, number];
  width: number;
  height: number;
  classes: string;
  co_pol: string | null;
  co_db: string;
  cross_pol: string | null;
  cross_db: string | null;
  db_encoding: { offset: number; scale: number; nodata: number };
}

/** Una línea del stream NDJSON de POST /api/harness/ask. */
export interface HarnessEvent {
  ts: string;
  stage: 'intent' | 'query' | 'process' | 'change' | 'interpret' | 'done' | 'result' | 'error';
  message: string;
  progress?: number | null;
  run_id?: string;
  level?: 'warning' | 'error';
  code?: string;
  payload?: HarnessPayload | null;
}
