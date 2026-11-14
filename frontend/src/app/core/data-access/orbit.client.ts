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
    : parseTle(await response.text(), 'CelesTrak (proxy de desarrollo)');

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
