/** Sistema de alertas de HidroGlobe: estaciones, torrenteras y escenarios (assets/data/hidroglobe). */
import type { FeatureCollection, LineString, Polygon } from 'geojson';

export type StationAlert = 'ROJA' | 'NARANJA' | 'AMARILLA' | 'VERDE';

export interface Station {
  id: string;
  nombre: string;
  cuenca: string;
  rio: string;
  lat: number;
  lon: number;
  nivel_actual: number;
  nivel_roja: number;
  /** Metros que faltan para el desborde; ≤ 0 = desbordado. */
  falta_desborde: number;
  alerta: StationAlert;
  color: string;
  tendencia: string;
  precipitacion_24h: number;
  humedad_suelo_pct: number;
  glofas_prob_desborde: number;
  zona: string;
}

export interface FloodScenario
  extends FeatureCollection<Polygon, { zona: string; profundidad: string; color: string; evento: string }> {
  title: string;
  descripcion: string;
  tipo: string;
  severidad: string;
  lluvia_gpm_30m: number;
  smap_humedad: number;
  sar_backscatter_anomaly_db: number;
}

export type Torrenteras = FeatureCollection<LineString, { nombre: string; color?: string }>;

export const ALERT_ORDER: StationAlert[] = ['VERDE', 'AMARILLA', 'NARANJA', 'ROJA'];
export const ALERT_HEX: Record<StationAlert, string> = {
  ROJA: '#ef4444',
  NARANJA: '#f97316',
  AMARILLA: '#eab308',
  VERDE: '#10b981',
};
/** Distritos en alerta roja en HidroGlobe (Taquiña D13, Tunari D1/D2, Albarrancho D9). */
export const RED_DISTRICTS = new Set(['D13', 'D1', 'D2', 'D9']);

export interface ScenarioView {
  key: string;
  label: string;
  lon: number;
  lat: number;
  zoom: number;
  /** Pregunta para el harness radar (null = no es un evento histórico). */
  question: string | null;
}

/** Cámara y pregunta para el harness de cada escenario. */
export const SCENARIOS: ScenarioView[] = [
  { key: 'taquina_2018', label: 'Taquiña 2018 (mazamorra)', lon: -66.1772, lat: -17.3485, zoom: 13.2, question: 'Mazamorra de la torrentera Taquiña en Tiquipaya, febrero de 2018' },
  { key: 'albarrancho_2024', label: 'Albarrancho 2024 (inundación)', lon: -66.175, lat: -17.435, zoom: 13, question: 'Inundación de Albarrancho y La Maica en Cochabamba, enero de 2024' },
  { key: 'pasos_desnivel_2022', label: 'Pasos a desnivel 2022', lon: -66.16, lat: -17.398, zoom: 14, question: 'Inundación en el centro de Cochabamba en 2022' },
  { key: 'rocha_crecida_2026', label: 'Pronóstico 2026 (Aviso 48)', lon: -66.165, lat: -17.4, zoom: 12, question: null },
];
