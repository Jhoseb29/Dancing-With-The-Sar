/// <reference lib="webworker" />
import { expose } from 'comlink';
import { degreesLat, degreesLong, eciToGeodetic, gstime, propagate, twoline2satrec, SatRec } from 'satellite.js';
import { EciSample, GeoSample, OrbitPass } from '../data-access/orbit.model';
import { OrbitWorkerApi } from './orbit.api';

const EARTH_RADIUS_KM = 6371;
const satrecCache = new Map<string, SatRec>();

function satrecFor(line1: string, line2: string): SatRec {
  const key = `${line1}\n${line2}`;
  let satrec = satrecCache.get(key);
  if (!satrec) {
    satrec = twoline2satrec(line1, line2);
    satrecCache.set(key, satrec);
  }
  return satrec;
}

function periodMinutes(satrec: SatRec): number {
  // satrec.no: movimiento medio en rad/min.
  return (2 * Math.PI) / satrec.no;
}

function subpoint(satrec: SatRec, date: Date): GeoSample | null {
  const state = propagate(satrec, date);
  if (!state) {
    return null;
  }
  const geo = eciToGeodetic(state.position, gstime(date));
  return [degreesLong(geo.longitude), degreesLat(geo.latitude), geo.height];
}

function haversineKm(lon1: number, lat1: number, lon2: number, lat2: number): number {
  const toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad;
  const dLon = (lon2 - lon1) * toRad;
  const a = Math.sin(dLat / 2) ** 2 + Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)));
}

const api: OrbitWorkerApi = {
  periodMinutes(line1, line2) {
    return periodMinutes(satrecFor(line1, line2));
  },

  groundTrack(line1, line2, startMs, endMs, stepSec) {
    const satrec = satrecFor(line1, line2);
    const track: GeoSample[] = [];
    for (let t = startMs; t <= endMs; t += stepSec * 1000) {
      const point = subpoint(satrec, new Date(t));
      if (point) {
        track.push([point[0], point[1], 0]);
      }
    }
    return track;
  },

  orbitRing(line1, line2, centerMs, samples) {
    const satrec = satrecFor(line1, line2);
    const periodMs = periodMinutes(satrec) * 60_000;
    const ring: EciSample[] = [];
    for (let i = 0; i <= samples; i++) {
      const t = centerMs - periodMs / 2 + (periodMs * i) / samples;
      const state = propagate(satrec, new Date(t));
      if (state) {
        ring.push([state.position.x, state.position.y, state.position.z]);
      }
    }
    return ring;
  },

  passes(line1, line2, fromMs, hours, target, maxDistanceKm) {
    const satrec = satrecFor(line1, line2);
    const stepMs = 20_000;
    const endMs = fromMs + hours * 3_600_000;
    const result: OrbitPass[] = [];

    let prev: { t: number; d: number; lat: number } | null = null;
    let prevPrev: { t: number; d: number; lat: number } | null = null;

    for (let t = fromMs; t <= endMs; t += stepMs) {
      const point = subpoint(satrec, new Date(t));
      if (!point) {
        continue;
      }
      const current = { t, d: haversineKm(point[0], point[1], target.lon, target.lat), lat: point[1] };
      // Mínimo local de distancia = máxima aproximación de un paso.
      if (prevPrev && prev && prev.d < prevPrev.d && prev.d <= current.d && prev.d <= maxDistanceKm) {
        result.push({
          timeMs: prev.t,
          distanceKm: Math.round(prev.d),
          direction: current.lat > prevPrev.lat ? 'ascending' : 'descending',
        });
      }
      prevPrev = prev;
      prev = current;
    }
    return result;
  },
};

expose(api);
