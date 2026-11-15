/** [minLon, minLat, maxLon, maxLat] en WGS84. */
export type BBox = [number, number, number, number];

export interface OrbitConfig {
  satellite: string;
  targetPlaceId: string;
  tleCacheHours: number;
  staleTleDays: number;
  passSearchHours: number;
  passMaxGroundDistanceKm: number;
  illustrativeSwathKm: number;
}

/**
 * Configuración de despliegue (12-Factor III): assets/runtime-config.json.
 * Lo editable por el usuario vive en assets/config/*.json.
 */
export interface RuntimeConfig {
  apiBaseUrl: string;
  orbit: OrbitConfig;
}

export function bboxCenter([minLon, minLat, maxLon, maxLat]: BBox): { lon: number; lat: number } {
  return { lon: (minLon + maxLon) / 2, lat: (minLat + maxLat) / 2 };
}
