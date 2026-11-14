## Context

El cambio 06 dejó un SPA Angular 22 con dos motores (Cesium para el planeta, MapLibre para la cuenca), i18n en vivo y un `ViewStore` mínimo (solo idioma). El agente de las fases 2–4 necesita leer y modificar la UI de forma estructurada, segura y verificable. El Proyecto 02 del GAMC entrega 7 servicios WMS reales a través de un proxy municipal que exige una API key.

## Goals / Non-Goals

**Goals:**
- Un solo documento JSON (`SceneState`) describe todo lo modificable de la UI.
- Usuario, URL y agente cambian la UI por el mismo canal (parches), con validación y versión.
- Configuración editable sin tocar código (JSON + schema).
- Capas municipales reales de Cochabamba visibles ya, sin exponer la key.

**Non-Goals:**
- El agente en sí (fase 2), la clasificación de eventos (fase 3) y la voz (fase 4).
- Implementar `gamc-proxy` en `gateway-ts` (lo hace el equipo backend con el mismo contrato).

## Decisions

### D1. Shadow: estado deseado + reportado
- `desired`: `SceneState` en el `SceneStore` (NgRx SignalStore). Es lo que la UI intenta mostrar.
- `reported`: lo que los motores confirman (cámara real, ruta activa, capas cargadas o con error). Lo publican los adaptadores de motor con throttle.
- El agente (fase 2) recibe `reported` en cada turno; así sabe qué está viendo el usuario.
- *Alternativa descartada:* que el agente edite archivos JSON en disco. Mezclaría las sesiones de distintos usuarios y obligaría a escribir en el servidor por cada interacción.

### D2. Parches con origen, versión y lista blanca
```
ScenePatch = { origin: 'user' | 'url' | 'agent', baseVersion?: number, ops: PatchOp[] }
PatchOp    = { op: 'replace' | 'add' | 'remove', path: string, value?: unknown }
```
- Rutas permitidas (`PATCHABLE_PATHS`): `/route`, `/lang`, `/camera/*`, `/time/*`, `/layers` y `/layers/{i}/*`, `/search/*`, `/panels/*`.
- Origen `agent`: se valida el estado resultante contra `scene-state.schema.json` (ajv, cargado de forma diferida) y se exige que `presetId`, `placeId` y `tourId` existan en la configuración. Si `baseVersion` no coincide con la versión actual y el parche toca una ruta que cambió el usuario después, se rechaza (el usuario manda).
- Origen `user` y `url`: generado por código tipado; se valida la lista blanca pero no se carga ajv.
- Cada parche aplicado incrementa `version`. Se guarda un historial corto (últimos 50) para depurar.

### D3. Configuración en JSON
| Archivo | Contenido | Quién lo usa |
| :--- | :--- | :--- |
| `routes.json` | id, path, claves i18n, descripción para el agente, `engine` (`globe`/`map`/`none`) | router, agente |
| `places.json` | id, nombres es/en, alias, tipo, bbox, fuente | buscador, cámara, agente |
| `layers.json` | presets: `gibs-xyz` (mapa base), `gamc-wms` (service_id, bbox, leyenda, featureInfo) | motores, agente |
| `camera-tours.json` | recorridos: pasos con `placeId` o destino, altitud, duración, pausa | motor 3D, agente |

- Angular no puede declarar rutas lazy solo con JSON: `routes.json` define qué existe y `app.routes.ts` mapea cada `id` a su `loadChildren`. En desarrollo, el arranque advierte en consola si no coinciden.
- Los JSON se cargan al iniciar (son pequeños) junto con `runtime-config.json`.

### D4. URL como subconjunto del shadow
Query params: `lang`, `place`, `layers` (ids separados por coma). La ruta va en el path. Se actualizan con debounce y `replaceUrl`. Al abrir un enlace se aplica un parche de origen `url`.

### D5. Capas GAMC por proxy
- Motor 2.5D: fuente raster MapLibre con plantilla `/api/gamc/wms?service_id=…&SERVICE=WMS&VERSION=1.1.1&REQUEST=GetMap&LAYERS=&FORMAT=image/png&TRANSPARENT=true&SRS=EPSG:3857&BBOX={bbox-epsg-3857}&WIDTH=256&HEIGHT=256`.
- Leyenda: `<img>` a `/api/gamc/wms?service_id=…&REQUEST=GetLegendGraphic&VERSION=1.0.0&FORMAT=image/png`.
- Clic: `GetFeatureInfo` (`INFO_FORMAT=application/json`, `FEATURE_COUNT=5`) sobre las capas visibles, con BBOX/X/Y calculados del viewport actual (EPSG:3857).
- **Desarrollo:** `proxy.conf.mjs` (servidor de `ng serve`, Node) lee `GAMC_WMS_KEY` de `.env`, descarta cualquier `key` del cliente, verifica que `service_id` esté en `layers.json` y reescribe a `https://serviciosgamc.cochabamba.bo/api/gs/wms?…&key=…`. La key nunca llega al navegador.
- **Producción:** `gateway-ts/gamc-proxy` implementa exactamente el mismo contrato (`docs/02` §1.2).

### D6. Buscador
Búsqueda local sobre `places.json`, sin acentos ni mayúsculas, por nombre y alias en ambos idiomas. Seleccionar un lugar aplica `/search/selectedPlaceId` y `/camera/placeId`. En fase 2 el agente usa la misma tabla.

### D7. Recorridos de cámara
`camera-tours.json` define secuencias. El motor 3D las ejecuta con `camera.flyTo` encadenado y reporta el paso actual. Cualquier interacción manual del usuario cancela el recorrido (se aplica `/camera/tourId = null`).

## Risks / Trade-offs

- **[Riesgo] Bucles router ↔ shadow** → Mitigación: cada sincronizador compara antes de navegar o parchear; los parches de origen `url` no vuelven a escribir la URL.
- **[Riesgo] La key del GAMC en desarrollo** → Mitigación: `.env` ignorado por git, `.env.example` sin valor, y el proxy elimina cualquier `key` del cliente.
- **[Riesgo] Capas WMS lentas** → Mitigación: teselas de 256 px, opacidad configurable, caché del navegador; en producción `gamc-proxy` puede cachear.
- **[Trade-off] ajv (~120 kB)** → Solo se carga cuando llega un parche de origen `agent`; el bundle inicial no crece.

## Open Questions

1. ¿Los atributos de `GetFeatureInfo` de cada servicio GAMC necesitan etiquetas legibles (diccionario de campos)? Se definirá al ver las respuestas reales.
2. ¿El bbox exacto de "Limite Distritos"? El portal repite el de "Cota 2750"; usamos el del proyecto 03 hasta que el GAMC lo confirme.
