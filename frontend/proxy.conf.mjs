// Proxy de DESARROLLO para `ng serve` (Node, no llega al navegador).
// En producción estas rutas las sirve backend/gateway-ts con el mismo contrato.
import { readFileSync } from 'node:fs';

// 12-Factor III: credenciales desde .env (raíz del repo, ignorado por git).
try {
  process.loadEnvFile(new URL('../.env', import.meta.url));
} catch {
  // Sin .env: las capas GAMC responderán 503 con un mensaje claro.
}

const GAMC_UPSTREAM = 'https://serviciosgamc.cochabamba.bo';
const GAMC_KEY = process.env.GAMC_WMS_KEY ?? '';
// backend/compute-py (harness + alertas); se puede apuntar a otro puerto con COMPUTE_URL.
const COMPUTE_URL = process.env.COMPUTE_URL ?? 'http://localhost:8000';

// Solo los service_id declarados en layers.json (OpenSpec 07, gamc-local-layers).
const layers = JSON.parse(readFileSync(new URL('./src/assets/config/layers.json', import.meta.url), 'utf8')).layers;
const ALLOWED_SERVICE_IDS = new Set(layers.filter((l) => l.kind === 'gamc-wms').map((l) => l.serviceId));

function gamcQuery(url) {
  const query = new URL(url, 'http://localhost').searchParams;
  query.delete('key'); // nunca aceptar una key del cliente
  return query;
}

export default {
  '/api/orbit/nisar': {
    target: 'https://celestrak.org',
    secure: true,
    changeOrigin: true,
    rewrite: () => '/NORAD/elements/gp.php?NAME=NISAR&FORMAT=TLE',
  },
  // Sentinel-1 (ESA): todos los de la constelación; el cliente descarta los que ya no operan.
  '/api/orbit/sentinel1': {
    target: 'https://celestrak.org',
    secure: true,
    changeOrigin: true,
    rewrite: () => '/NORAD/elements/gp.php?NAME=SENTINEL-1&FORMAT=TLE',
  },
  '/api/gamc/wms': {
    target: GAMC_UPSTREAM,
    secure: true,
    changeOrigin: true,
    bypass: (req, res) => {
      const serviceId = gamcQuery(req.url).get('service_id');
      if (!GAMC_KEY) {
        res.writeHead(503, { 'content-type': 'text/plain; charset=utf-8' });
        res.end('GAMC_WMS_KEY no configurada en .env');
        return false;
      }
      if (!serviceId || !ALLOWED_SERVICE_IDS.has(serviceId)) {
        res.writeHead(403, { 'content-type': 'text/plain; charset=utf-8' });
        res.end('service_id no autorizado');
        return false;
      }
      return undefined;
    },
    rewrite: (path) => {
      const query = gamcQuery(path);
      query.set('key', GAMC_KEY);
      return `/api/gs/wms?${query.toString()}`;
    },
  },
  // Harness NISAR: compute-py en desarrollo; gateway-ts en producción.
  // Respuesta en streaming (NDJSON): el proxy no debe bufferizar.
  '/api/harness': {
    target: COMPUTE_URL,
    changeOrigin: true,
    timeout: 1_300_000,
    proxyTimeout: 1_300_000,
  },
  // Alertas tempranas (alert-harness): REST + WebSocket en compute-py.
  '/api/alerts': {
    target: COMPUTE_URL,
    ws: true,
    changeOrigin: true,
  },
  // Eventos (OpenSpec 09): estadísticas FIRMS en compute-py.
  // Voz a texto (respaldo de la Web Speech API): Gemini en compute-py.
  '/api/voice': {
    target: COMPUTE_URL,
    changeOrigin: true,
  },
  '/api/events': {
    target: COMPUTE_URL,
    changeOrigin: true,
  },
  // Riesgo de cuenca, Copernicus DEM y precipitación NASA en compute-py.
  '/api/basin': {
    target: COMPUTE_URL,
    changeOrigin: true,
  },
  '/api': {
    target: 'http://localhost:3000',
    secure: false,
    changeOrigin: true,
  },
};
