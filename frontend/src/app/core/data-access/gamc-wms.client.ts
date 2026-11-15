/**
 * Cliente del proxy WMS del GAMC (contrato `GET {api}/gamc/wms`, OpenSpec 07 D5).
 * La API key nunca viaja desde el navegador: la agrega el proxy en servidor.
 */

const EARTH_HALF_CIRCUMFERENCE = 20037508.342789244;

export function gamcTileUrl(apiBaseUrl: string, serviceId: string): string {
  const params = new URLSearchParams({
    service_id: serviceId,
    SERVICE: 'WMS',
    VERSION: '1.1.1',
    REQUEST: 'GetMap',
    LAYERS: '',
    FORMAT: 'image/png',
    TRANSPARENT: 'true',
    SRS: 'EPSG:3857',
    WIDTH: '256',
    HEIGHT: '256',
  });
  // {bbox-epsg-3857} lo reemplaza MapLibre por tesela; no debe codificarse.
  return `${apiBaseUrl}/gamc/wms?${params.toString()}&BBOX={bbox-epsg-3857}`;
}

export function gamcLegendUrl(apiBaseUrl: string, serviceId: string): string {
  const params = new URLSearchParams({
    service_id: serviceId,
    REQUEST: 'GetLegendGraphic',
    VERSION: '1.0.0',
    FORMAT: 'image/png',
  });
  return `${apiBaseUrl}/gamc/wms?${params.toString()}`;
}

export interface FeatureInfoQuery {
  /** Extensión visible en EPSG:3857 [minX, minY, maxX, maxY]. */
  bbox3857: [number, number, number, number];
  width: number;
  height: number;
  x: number;
  y: number;
}

export interface GamcFeature {
  id?: string | number;
  properties: Record<string, unknown>;
}

export async function gamcFeatureInfo(apiBaseUrl: string, serviceId: string, query: FeatureInfoQuery): Promise<GamcFeature[]> {
  const params = new URLSearchParams({
    service_id: serviceId,
    SERVICE: 'WMS',
    VERSION: '1.1.1',
    REQUEST: 'GetFeatureInfo',
    LAYERS: '',
    QUERY_LAYERS: '',
    SRS: 'EPSG:3857',
    BBOX: query.bbox3857.join(','),
    WIDTH: String(Math.round(query.width)),
    HEIGHT: String(Math.round(query.height)),
    X: String(Math.round(query.x)),
    Y: String(Math.round(query.y)),
    INFO_FORMAT: 'application/json',
    FEATURE_COUNT: '5',
  });
  const response = await fetch(`${apiBaseUrl}/gamc/wms?${params.toString()}`, { headers: { Accept: 'application/json' } });
  if (!response.ok) {
    throw new Error(`GetFeatureInfo respondió ${response.status}`);
  }
  const body = (await response.json()) as { features?: GamcFeature[] };
  return body.features ?? [];
}

/** Campos que nunca se muestran (datos personales). */
const PERSONAL_DATA = /(denunciante|celular|telefono|tel[eé]fono|nombre|apellido|correo|email|^ci$|carnet|direccion_particular)/i;

/**
 * Filtra los atributos de GetFeatureInfo: aplica la lista blanca del preset (si
 * existe), elimina siempre los datos personales y limpia entidades HTML.
 */
export function sanitizeFeatureProperties(
  properties: Record<string, unknown>,
  allowed?: string[],
): Record<string, string> {
  const allow = allowed ? new Set(allowed.map(normalizeKey)) : null;
  const result: Record<string, string> = {};
  for (const [key, value] of Object.entries(properties)) {
    if (value === null || value === undefined || value === '') continue;
    if (PERSONAL_DATA.test(normalizeKey(key))) continue;
    if (allow && !allow.has(normalizeKey(key))) continue;
    result[key] = decodeEntities(String(value)).trim();
  }
  return result;
}

function normalizeKey(key: string): string {
  return key
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[\s-]+/g, '_');
}

function decodeEntities(text: string): string {
  return text.replace(/&nbsp;/gi, ' ').replace(/&amp;/gi, '&').replace(/&lt;/gi, '<').replace(/&gt;/gi, '>').replace(/&quot;/gi, '"');
}

export function lonLatTo3857(lon: number, lat: number): [number, number] {
  const x = (lon * EARTH_HALF_CIRCUMFERENCE) / 180;
  const clamped = Math.max(Math.min(lat, 85.05112878), -85.05112878);
  const y = (Math.log(Math.tan(((90 + clamped) * Math.PI) / 360)) / (Math.PI / 180)) * (EARTH_HALF_CIRCUMFERENCE / 180);
  return [x, y];
}
