## Why

La estrella de la web será un **agente propio** que conversa con el usuario (voz y teclado) y maneja la página en tiempo real: cambia de vista, mueve el planeta, busca lugares y muestra las imágenes del satélite adecuado para cada tipo de evento. Para que eso sea posible y seguro, **todo lo que el usuario puede modificar debe vivir en JSON**, como un *shadow* de dispositivo IoT: un estado deseado (lo que pide el usuario o el agente) y un estado reportado (lo que la pantalla muestra de verdad).

Además, el foco local del proyecto (Proyecto 02 GAMC, "Alerta Temprana de Riesgos en Cuencas") requiere mostrar ya las **capas municipales reales de Cochabamba** (cuencas, drenaje, emergencias, distritos, Cota 2750) a través del proxy del GAMC, sin exponer su API key.

Este cambio es la **Fase 1** de cuatro. Prepara la base sobre la que se construyen las demás.

## Hoja de ruta del agente

| Fase | Cambio OpenSpec | Contenido | Depende de |
| :--- | :--- | :--- | :--- |
| **1** | `07-scene-shadow-and-local-layers` (este) | Shadow `SceneState` + parches validados, configuración en JSON (rutas, lugares, capas, recorridos), buscador, capas WMS del GAMC | — |
| 2 | `08-ui-agent-text` | Agente por teclado con **Gemini** (`ui-agent` en `compute-py`, `agent-gateway` WebSocket en `gateway-ts`), `agent-dock` en el frontend | Fase 1 + backend |
| 3 | `09-event-visualization` | `events.json`, clasificación de eventos, presets de imágenes por tipo (inundación, incendio, deformación, vegetación), FIRMS y GIBS | Fase 2 |
| 4 | `10-agent-voice` | Voz: Web Speech API del navegador y luego proveedor de voz con keys en backend | Fase 2 |

## What Changes

- **`SceneState`** (JSON) como única fuente de verdad del estado modificable de la UI: ruta, idioma, cámara, tiempo, capas, búsqueda y paneles. Reemplaza al `ViewStore`.
- **Parches JSON Patch** (subconjunto RFC 6902: `replace`/`add`/`remove`) con origen (`user`/`url`/`agent`), versión y lista blanca de rutas. Los parches de origen `agent` se validan contra JSON Schema antes de aplicarse.
- **Estado reportado**: los motores (Cesium, MapLibre) reportan la cámara real y las capas cargadas.
- **Configuración en JSON** (`frontend/src/assets/config/`): `routes.json`, `places.json`, `layers.json`, `camera-tours.json`.
- **JSON Schemas** compartidos en `backend/shared/schemas/` (contrato con backend y agente).
- **Buscador** de lugares en la barra superior, alimentado por `places.json`.
- **Recorridos de cámara** (`camera-tours.json`) para el "movimiento del planeta".
- **Capas WMS del GAMC** (7 servicios del Proyecto 02) en `basin-map`, con leyenda (`GetLegendGraphic`) y consulta al hacer clic (`GetFeatureInfo`), siempre vía `/api/gamc/wms`.
- **Proxy de desarrollo** que inyecta `GAMC_WMS_KEY` desde `.env` en el servidor de desarrollo (nunca en el navegador) y solo permite los `service_id` autorizados. En producción esa ruta la sirve `gamc-proxy` de `gateway-ts`.
- **Gancho de desarrollo** `window.dwsScene` (solo en modo desarrollo) para aplicar parches como lo hará el agente y probar el shadow antes de que exista el backend.

## Capabilities

### New Capabilities
- `scene-shadow`: documento `SceneState`, parches validados, estado reportado, sincronización con router y URL.
- `ui-config-json`: rutas, lugares, capas y recorridos definidos en JSON con su schema.
- `gamc-local-layers`: capas municipales reales de Cochabamba vía proxy (GetMap, GetLegendGraphic, GetFeatureInfo).

### Modified Capabilities
- `frontend-geo-engine` y `frontend-performance` (cambio 06): el estado de vista pasa del `ViewStore` al `SceneStore`; la URL serializa un subconjunto del `SceneState`.

## Impact

- **Frontend:** `core/scene/` (nuevo), `core/config/` (cargador de JSON), `core/services/` (adaptadores de motores reportan estado), `layout/main-shell` (buscador), `features/basin-map` (capas GAMC), `features/orbit-view` (velocidad, seguimiento y recorridos desde el shadow), `assets/config/*.json`.
- **Backend (contrato, sin implementar aquí):** `backend/shared/schemas/*.schema.json`; `gateway-ts/gamc-proxy` debe exponer `GET /api/gamc/wms` con el mismo comportamiento que el proxy de desarrollo.
- **Fuentes reales:** GAMC WMS Proyecto 02 (`data-map.json` → `gamc_wms`, 7 servicios), NASA GIBS (mapa base), CelesTrak vía `/api/orbit/nisar`.
- **Cero mocks:** los lugares y capas son reales (bbox de `data-map.json` y del portal GAMC); el bbox de Bolivia es aproximado y está rotulado como tal.
- **Seguridad:** `GAMC_WMS_KEY` solo en `.env` (ignorado por git); el proxy rechaza `service_id` fuera de la lista y descarta cualquier `key` enviada por el cliente.
- **Dependencia nueva:** `ajv` (MIT), cargado de forma diferida solo para validar parches de origen `agent`.
