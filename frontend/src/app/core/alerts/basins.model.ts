/** Cuencas torrenciales (alert-harness/alerts/basins.py → GET /api/alerts/basins). */
import type { FeatureCollection, MultiPolygon, Polygon } from 'geojson';

export type BasinType = 'mazamorra' | 'crecida_torrencial' | 'inundacion';

export interface BasinProps {
  id: string;
  nombre: string;
  area_km2: number;
  cota_min_m: number;
  cota_max_m: number;
  pendiente_media_grados: number;
  ladera_fuerte_pct: number;
  /** Relieve / √área (km). > 0,6 mazamorra; 0,3–0,6 crecida torrencial; < 0,3 inundación. */
  melton: number;
  tipo: BasinType;
  sedimento_radar: { area_km2: number; desde: string; hasta: string; corrida: string } | null;
  centro: [number, number];
  bbox: [number, number, number, number];
}

export type BasinsFC = FeatureCollection<Polygon | MultiPolygon, BasinProps>;
