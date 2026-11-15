import { OrbitElements } from './orbit.model';

const CACHE_KEY = 'dws.orbit.nisar';

/**
 * Obtiene los elementos orbitales de NISAR desde el gateway (`GET {api}/orbit/nisar`).
 *
 * - Respuesta del backend: JSON con el contrato OrbitElements.
 * - En desarrollo, el proxy de `ng serve` reenvía la misma ruta a CelesTrak y
 *   devuelve el TLE en texto; se interpreta aquí con el mismo resultado.
 *
 * Se cachea en el navegador `cacheHours` horas para no consultar la fuente más
 * seguido de lo que se actualiza (CelesTrak lo pide expresamente).
 */
export async function fetchOrbitElements(apiBaseUrl: string, cacheHours: number): Promise<OrbitElements> {
  const cached = readCache(cacheHours);
  if (cached) {
    return cached;
  }

  const response = await fetch(`${apiBaseUrl}/orbit/nisar`, { headers: { Accept: 'application/json, text/plain' } });
  if (!response.ok) {
    throw new Error(`orbit/nisar respondió ${response.status}`);
  }

  const contentType = response.headers.get('content-type') ?? '';
  const elements = contentType.includes('application/json')
    ? ((await response.json()) as OrbitElements)
    : parseTle(await response.text(), 'CelesTrak');

  writeCache(elements);
  return elements;
}

export function parseTle(text: string, source: string): OrbitElements {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line.length > 0);
  const line1 = lines.find((line) => line.startsWith('1 '));
  const line2 = lines.find((line) => line.startsWith('2 '));
  if (!line1 || !line2) {
    throw new Error('La respuesta no contiene un TLE válido');
  }
  const name = lines.length >= 3 && !lines[0].startsWith('1 ') ? lines[0] : 'NISAR';
  return {
    satellite: name,
    noradId: line1.substring(2, 7).trim(),
    line1,
    line2,
    epoch: tleEpochToIso(line1),
    source,
    fetchedAt: new Date().toISOString(),
  };
}

/** Columnas 19–32 de la línea 1: AA DDD.DDDDDDDD (año de 2 dígitos + día del año fraccional). */
export function tleEpochToIso(line1: string): string {
  const yy = Number(line1.substring(18, 20));
  const dayOfYear = Number(line1.substring(20, 32));
  const year = yy < 57 ? 2000 + yy : 1900 + yy;
  const ms = Date.UTC(year, 0, 1) + (dayOfYear - 1) * 86_400_000;
  return new Date(ms).toISOString();
}

function readCache(cacheHours: number): OrbitElements | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY);
    if (!raw) {
      return null;
    }
    const elements = JSON.parse(raw) as OrbitElements;
    const ageMs = Date.now() - Date.parse(elements.fetchedAt);
    return ageMs < cacheHours * 3_600_000 ? elements : null;
  } catch {
    return null;
  }
}

function writeCache(elements: OrbitElements): void {
  try {
    localStorage.setItem(CACHE_KEY, JSON.stringify(elements));
  } catch {
    // Sin almacenamiento disponible: se vuelve a pedir en la próxima carga.
  }
}

/** Satélites que ya no operan y se descartan de un grupo (Sentinel-1B falló en dic. 2021). */
const INACTIVE = /SENTINEL-1B\b/i;

/**
 * Elementos orbitales de todos los satélites de un grupo (p. ej. `GET {api}/orbit/sentinel1`
 * -> Sentinel-1A, 1C, 1D…). Igual que NISAR: TLE de CelesTrak, caché de `cacheHours` horas.
 */
export async function fetchOrbitGroup(apiBaseUrl: string, group: string, cacheHours: number): Promise<OrbitElements[]> {
  const key = `dws.orbit.${group}`;
  try {
    const raw = localStorage.getItem(key);
    if (raw) {
      const cached = JSON.parse(raw) as OrbitElements[];
      if (cached.length && Date.now() - Date.parse(cached[0].fetchedAt) < cacheHours * 3_600_000) return cached;
    }
  } catch {
    // Caché ilegible o bloqueada: se vuelve a pedir.
  }
  const response = await fetch(`${apiBaseUrl}/orbit/${group}`, { headers: { Accept: 'text/plain' } });
  if (!response.ok) {
    throw new Error(`orbit/${group} respondió ${response.status}`);
  }
  const elements = parseTleGroup(await response.text(), 'CelesTrak');
  try {
    localStorage.setItem(key, JSON.stringify(elements));
  } catch {
    // Sin almacenamiento: la próxima carga vuelve a consultar.
  }
  return elements;
}

/** Varios TLE de 3 líneas (nombre, línea 1, línea 2) en un mismo texto. */
export function parseTleGroup(text: string, source: string): OrbitElements[] {
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const out: OrbitElements[] = [];
  for (let i = 0; i + 2 < lines.length + 1; i++) {
    if (lines[i + 1]?.startsWith('1 ') && lines[i + 2]?.startsWith('2 ') && !lines[i].startsWith('1 ') && !lines[i].startsWith('2 ')) {
      if (!INACTIVE.test(lines[i])) {
        out.push({ ...parseTle(lines.slice(i, i + 3).join('\n'), source), satellite: lines[i] });
      }
      i += 2;
    }
  }
  if (!out.length) throw new Error('La respuesta no contiene TLE válidos');
  return out;
}
