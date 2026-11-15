/**
 * Contratos del alert-harness: alert-harness/schemas/{indicator,alert}.schema.json
 * y los endpoints de backend/compute-py/src/modules/alerts.
 */
import type { FeatureCollection, MultiPolygon, Polygon } from 'geojson';

export type AlertLevel = 'verde' | 'amarillo' | 'naranja' | 'rojo';
export type Hazard = 'inundacion' | 'mazamorra' | 'deslizamiento';
export type Confidence = 'alta' | 'media' | 'baja';

/** Indicador diagnóstico validado (indicator.schema.json). */
export interface Indicator {
  id: string;
  valor: number;
  unidad: string;
  metodo: string;
  evidencia: string;
  confianza: Confidence;
  caveat?: string;
}

export interface RiskAlert {
  id: string;
  created_at: string;
  case_id: string | null;
  area: { nombre: string; bbox: [number, number, number, number] };
  fecha_referencia: string;
  peligro: Hazard;
  nivel: AlertLevel;
  /** 0–100. NO es una probabilidad. */
  indice_riesgo: number;
  confianza: { porcentaje: number; etiqueta: Confidence; faltantes: string[] };
  componentes: { disparo: number | null; susceptibilidad: number | null; evidencia_radar: number | null };
  indicadores: Indicator[];
  motivos: string[];
  acciones: { tecnicos: string[]; ciudadania: string[] };
  fuentes: string[];
  caveats?: string[];
}

/** Vista compacta para la UI (alert-harness/alerts/summary.py): señales 0..1 + valores. */
export interface DistrictData {
  senales: { lluvia: number | null; suelo: number | null; terreno: number | null; radar: number | null };
  causa: 'lluvia' | 'suelo' | 'radar' | 'calma';
  valores: {
    lluvia_24h_mm: number | null;
    lluvia_72h_mm: number | null;
    lluvia_antecedente_mm: number | null;
    ladera_fuerte_pct: number | null;
    pendiente_media_grados: number | null;
  };
  confianza: Confidence;
  alerta_id: string;
  /** Tormenta más fuerte de las últimas 24 h sobre el distrito (IMERG media hora). */
  rafaga?: { max_mm_h: number; cuando: string; acumulado_24h_mm: number } | null;
}

/** Lluvia IMERG cada 30 min sobre la ciudad (output/monitor/rain.json). Grillas [lon][lat]. */
export interface RainPayload {
  actualizado: string;
  fuente: string;
  productos: string[];
  lons: number[];
  lats: number[];
  celda_grados: number;
  slots: { inicio: string; producto: string; mm_h: (number | null)[][] }[];
  acumulado_mm: number[][];
  pico: { max_30min_mm_h: number | null; max_1h_mm: number | null; cuando: string | null; medias_horas: number };
  esperadas: number;
}

export interface RadarPass {
  ultima: string | null;
  recientes?: string[];
  proxima_estimada: string | null;
  ciclo_dias?: number;
}

/** Última y próxima pasada estimada del radar sobre Cochabamba (output/monitor/radar.json). */
export interface RadarSchedule {
  actualizado?: string;
  NISAR?: RadarPass;
  'Sentinel-1'?: RadarPass;
}

export interface DistrictState {
  datos?: DistrictData;
  nivel: AlertLevel;
  calculado: AlertLevel;
  indice: number;
  peligro: Hazard;
  actualizado: string;
  bajando_desde: string | null;
  /** El nivel no baja antes de esta hora (histéresis del monitor). */
  vigente_hasta?: string;
}

export type DistrictsFC = FeatureCollection<
  Polygon | MultiPolygon,
  {
    id: string;
    distrito: string;
    comuna: string;
    bbox: number[];
    centro?: [number, number];
    estado: DistrictState | null;
  }
>;

export interface EvalSummary {
  eval_id: string;
  puntaje: number;
  delta_vs_anterior: number | null;
  nota: string;
  componentes: { csi: number; nivel: number; expectativas: number; schema: number };
  pod: number | null;
  far: number | null;
  tabla: Record<string, number>;
  confianza_media_pct: number | null;
  casos: number;
  umbrales_version?: number;
}

export interface EvalCase {
  case_id: string;
  ocurrio: boolean;
  esperado: [AlertLevel, AlertLevel];
  nivel: AlertLevel | null;
  indice: number | null;
  resultado: 'acierto' | 'fallo' | 'falsa_alarma' | 'negativo_correcto' | 'error';
}

export interface EvalPayload {
  latest: { resumen: EvalSummary; casos: EvalCase[] } | null;
  history: EvalSummary[];
}

export type AlertsMessage = { type: 'snapshot'; alerts: RiskAlert[] } | { type: 'alert'; alert: RiskAlert };

export type DistrictProps = DistrictsFC['features'][number]['properties'];

/** 0..1 → banda corta para mostrar una señal con palabras (no números). */
export function signalBand(v: number | null | undefined): 'low' | 'mid' | 'high' | 'none' {
  if (v === null || v === undefined) return 'none';
  return v < 0.33 ? 'low' : v < 0.66 ? 'mid' : 'high';
}
