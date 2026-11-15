// Coloreado de las grillas del harness (nisar-harness/lib/globe.py) en el navegador.
// TypeScript puro: no importa @angular/*. El harness entrega datos, no imágenes.
import type { GlobeGrid, GlobeLayerId } from './harness.model';

type Rgb = [number, number, number];

/** Colores de DATOS (no de interfaz): mecanismo de dispersión dominante. */
export const CLASS_LEGEND: { id: number; key: string; color: Rgb }[] = [
  { id: 0, key: 'water', color: [30, 110, 230] },
  { id: 1, key: 'soil', color: [200, 170, 120] },
  { id: 2, key: 'vegetation', color: [40, 170, 70] },
  { id: 3, key: 'urban', color: [225, 45, 45] },
];

/** Rampa de brillo radar (oscuro → claro) para HH/HV en dB. */
const DB_RAMP: Rgb[] = [
  [8, 12, 40],
  [40, 60, 140],
  [60, 150, 170],
  [170, 210, 120],
  [250, 245, 210],
];

/** Rango de estiramiento por capa (dB) para que el contraste sea útil. */
export const DB_RANGE: Record<'co' | 'cross', [number, number]> = {
  co: [-22, 0],
  cross: [-30, -8],
};

export function rampColor(t: number): Rgb {
  const x = Math.min(Math.max(t, 0), 1) * (DB_RAMP.length - 1);
  const i = Math.min(Math.floor(x), DB_RAMP.length - 2);
  const f = x - i;
  const [a, b] = [DB_RAMP[i], DB_RAMP[i + 1]];
  return [0, 1, 2].map((k) => Math.round(a[k] + (b[k] - a[k]) * f)) as Rgb;
}

export function rampCss(steps = 5): string {
  const stops = Array.from({ length: steps }, (_, i) => {
    const [r, g, b] = rampColor(i / (steps - 1));
    return `rgb(${r} ${g} ${b}) ${Math.round((100 * i) / (steps - 1))}%`;
  });
  return `linear-gradient(90deg, ${stops.join(', ')})`;
}

function decodeBase64(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function hasLayer(grid: GlobeGrid, layer: GlobeLayerId): boolean {
  if (layer === 'objects') return false; // los objetos vienen de *_objects.geojson, no de la grilla
  return layer === 'classes' ? !!grid.classes : layer === 'co' ? !!grid.co_db : !!grid.cross_db;
}

/** Pinta una capa de la grilla como imagen RGBA (data URL PNG). NoData = transparente. */
export function renderLayer(
  grid: GlobeGrid,
  layer: GlobeLayerId,
  hiddenClasses: ReadonlySet<number> = new Set(),
): string | null {
  if (layer === 'objects') return null;
  const source = layer === 'classes' ? grid.classes : layer === 'co' ? grid.co_db : grid.cross_db;
  if (!source) return null;
  const values = decodeBase64(source);
  const { width, height, db_encoding: enc } = grid;
  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) return null;
  const image = ctx.createImageData(width, height);
  const px = image.data;

  const classColors = new Map(CLASS_LEGEND.map((c) => [c.id, c.color]));
  const [lo, hi] = layer === 'classes' ? [0, 1] : DB_RANGE[layer];
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (v === enc.nodata) continue;
    let rgb: Rgb | undefined;
    if (layer === 'classes') {
      if (hiddenClasses.has(v)) continue;
      rgb = classColors.get(v);
    } else {
      const db = enc.offset + v * enc.scale;
      rgb = rampColor((db - lo) / (hi - lo));
    }
    if (!rgb) continue;
    const o = i * 4;
    px[o] = rgb[0];
    px[o + 1] = rgb[1];
    px[o + 2] = rgb[2];
    px[o + 3] = 255;
  }
  ctx.putImageData(image, 0, 0);
  return canvas.toDataURL('image/png');
}

/** Valor de una celda bajo el cursor (para inspeccionar el globo). */
export function cellAt(
  grid: GlobeGrid,
  lon: number,
  lat: number,
): { classId: number | null; coDb: number | null; crossDb: number | null } | null {
  const [w, s, e, n] = grid.bbox;
  if (lon < w || lon > e || lat < s || lat > n) return null;
  const col = Math.min(grid.width - 1, Math.floor(((lon - w) / (e - w)) * grid.width));
  const row = Math.min(grid.height - 1, Math.floor(((n - lat) / (n - s)) * grid.height));
  const idx = row * grid.width + col;
  const enc = grid.db_encoding;
  const at = (b64: string | null) => {
    if (!b64) return null;
    const v = decodeBase64(b64)[idx];
    return v === enc.nodata ? null : v;
  };
  const cls = at(grid.classes);
  const co = at(grid.co_db);
  const cross = at(grid.cross_db);
  return {
    classId: cls,
    coDb: co === null ? null : +(enc.offset + co * enc.scale).toFixed(1),
    crossDb: cross === null ? null : +(enc.offset + cross * enc.scale).toFixed(1),
  };
}
