# Frontend · Dancing with the SARs (Angular 22)

Arquitectura: [`docs/03-frontend-architecture.md`](../docs/03-frontend-architecture.md) · Diseño: [`docs/06-design-system.md`](../docs/06-design-system.md) · Spec: [`openspec/changes/06-frontend-geo-engine-and-performance/`](../openspec/changes/06-frontend-geo-engine-and-performance/proposal.md)

## Correr en local

```bash
npm install
npm start            # http://localhost:4200
npm run build        # producción en dist/
```

## Proxy de desarrollo (`proxy.conf.mjs`)

Copia `.env.example` a `.env` en la raíz del repo y completa `GAMC_WMS_KEY` (portal del GAMC, Proyecto 02).

| Ruta | Destino en desarrollo | En producción |
| :--- | :--- | :--- |
| `/api/gamc/wms` | Proxy WMS del GAMC; agrega la key desde `.env`, rechaza `service_id` fuera de `layers.json` | `gateway-ts/gamc-proxy` |
| `/api/orbit/nisar` | CelesTrak (TLE público de NISAR, texto) | `gateway-ts` → JSON `OrbitElements` |
| `/api/*` | `gateway-ts` en `http://localhost:3000` | `gateway-ts` |

## Agente (OpenSpec 08)

1. Completa `GEMINI_API_KEY` (y opcionalmente `GEMINI_MODEL`) en el `.env` de la raíz.
2. Levanta `compute-py` (desde `backend/compute-py`, con su `.venv`):

```bash
python -m venv .venv && .venv/Scripts/python -m pip install "fastapi==0.163.0" "uvicorn[standard]==0.54.0" "google-genai==3.3.0" pydantic-settings jsonschema "httpx==0.28.1"
```

```bash
.venv/Scripts/python -m uvicorn main:app --app-dir src --port 8000
```

3. `npm start` en `frontend/`: el proxy enruta `/api/agent` (WebSocket) a `localhost:8000`.

## Shadow de la UI (OpenSpec 07)

- Todo lo modificable vive en `SceneState` (`core/scene/`), contrato en `backend/shared/schemas/`.
- Configuración editable sin código en `src/assets/config/` (rutas, lugares, capas, recorridos).
- `npm start` y `npm run build` copian los schemas desde `backend/shared/schemas` (`scripts/sync-schemas.mjs`).
- En desarrollo, simula al agente desde la consola:

```js
await dwsScene.patch([{ op: 'replace', path: '/route', value: 'basin' }], 'agent')
await dwsScene.patch([{ op: 'replace', path: '/camera/tourId', value: 'welcome' }], 'agent')
dwsScene.reported()
```

- El cliente acepta las dos formas de `/api/orbit/nisar` (texto TLE o JSON) y cachea el resultado 2 h en el navegador para no consultar CelesTrak más seguido de lo que se actualiza.
- Mientras `gateway-ts` no esté corriendo, las vistas que dependen del catálogo muestran un estado "no disponible" (sin datos inventados).

## Qué funciona hoy

- `orbita`: globo 3D (Cesium + NASA GIBS) con NISAR en tiempo real, órbita, trazas, franja ilustrativa, próximos pasos sobre Cochabamba y cuenta regresiva.
- `cuenca`: mapa 2.5D (MapLibre) con las 7 capas WMS reales del GAMC, leyendas y datos por punto (sin datos personales).
- Buscador de lugares, recorridos de cámara y enlaces compartibles (`?place=…&layers=…&lang=…`).
- Idioma es/en en vivo (`?lang=en`), sistema de diseño, carga diferida de Cesium y MapLibre.

## Pendiente

Ver [`tasks.md`](../openspec/changes/06-frontend-geo-engine-and-performance/tasks.md): capas GCOV/GUNW con deck.gl, `temporal-lab` (uPlot), `risk-dashboard`, deformación 3D, Service Worker y regla ESLint de imports.
