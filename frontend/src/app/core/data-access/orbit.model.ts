/** Contrato OrbitElements (design D9). */
export interface OrbitElements {
  satellite: string;
  noradId: string;
  line1: string;
  line2: string;
  /** Época del TLE en ISO 8601 (UTC). */
  epoch: string;
  source: string;
  fetchedAt: string;
}

/** Paso previsto sobre el área de interés (no implica adquisición). */
export interface OrbitPass {
  /** Momento de máxima aproximación, ms desde epoch Unix. */
  timeMs: number;
  /** Distancia mínima del punto subsatelital al centro del área, km. */
  distanceKm: number;
  direction: 'ascending' | 'descending';
}

/** Muestra de posición en coordenadas geodésicas (grados, km). */
export type GeoSample = [lonDeg: number, latDeg: number, heightKm: number];

/** Muestra de posición inercial (ECI) en km. */
export type EciSample = [x: number, y: number, z: number];
