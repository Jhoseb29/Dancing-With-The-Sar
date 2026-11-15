import { EciSample, GeoSample, OrbitPass } from '../data-access/orbit.model';

/** API del worker orbital (Comlink). Cálculos SGP4 fuera del hilo principal. */
export interface OrbitWorkerApi {
  /** Periodo orbital en minutos. */
  periodMinutes(line1: string, line2: string): number;

  /** Puntos subsatelitales entre startMs y endMs (grados, altura 0). */
  groundTrack(line1: string, line2: string, startMs: number, endMs: number, stepSec: number): GeoSample[];

  /** Posiciones inerciales (ECI, km) durante una vuelta centrada en centerMs. */
  orbitRing(line1: string, line2: string, centerMs: number, samples: number): EciSample[];

  /** Pasos sobre un punto en las próximas `hours` horas. */
  passes(
    line1: string,
    line2: string,
    fromMs: number,
    hours: number,
    target: { lon: number; lat: number },
    maxDistanceKm: number,
  ): OrbitPass[];
}
