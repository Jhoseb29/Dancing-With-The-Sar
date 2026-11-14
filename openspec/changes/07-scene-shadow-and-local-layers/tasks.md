## 1. Contratos

- [x] 1.1 `backend/shared/schemas/scene-state.schema.json` y `scene-patch.schema.json`
- [x] 1.2 Schemas de configuración: `routes`, `places`, `layers`, `camera-tours`

## 2. Configuración en JSON

- [x] 2.1 `assets/config/routes.json` con las 6 vistas actuales
- [x] 2.2 `assets/config/places.json` (Bolivia aprox., área urbana y cuenca de `data-map.json`, extensiones GAMC)
- [x] 2.3 `assets/config/layers.json` (mapa base GIBS + 7 servicios GAMC con `service_id` real)
- [x] 2.4 `assets/config/camera-tours.json` (recorrido de bienvenida)
- [x] 2.5 Cargador de configuración en el arranque y advertencia de rutas sin registrar

## 3. Shadow

- [x] 3.1 `core/scene/scene.model.ts`, `scene.store.ts` (deseado, reportado, versión, historial)
- [x] 3.2 Aplicador de parches con lista blanca y validación ajv diferida para origen `agent`
- [x] 3.3 Sincronización router ↔ shadow y URL (`lang`, `place`, `layers`)
- [x] 3.4 Reemplazar `ViewStore` por `SceneStore` en shell, orbit-view y basin-map
- [x] 3.5 Gancho `window.dwsScene` solo en desarrollo

## 4. Capas GAMC

- [x] 4.1 `proxy.conf.mjs`: `/api/gamc/wms` con key desde `.env`, lista blanca de `service_id`, sin `key` del cliente
- [x] 4.2 `.env.example` en la raíz con `GAMC_WMS_KEY=`
- [x] 4.3 Motor 2.5D: capas raster GAMC desde `SceneState.layers`, reporte de estado por capa
- [x] 4.4 Panel de capas con leyendas y `GetFeatureInfo` al hacer clic

## 5. Buscador y recorridos

- [x] 5.1 Componente `place-search` (3 archivos) en la barra superior
- [x] 5.2 Cámara 3D y 2.5D obedecen `/camera/placeId`
- [x] 5.3 Recorridos 3D desde `camera-tours.json`, cancelables por interacción

## 6. Verificación

- [x] 6.1 `ng build` sin errores ni warnings; bundle inicial dentro del presupuesto
- [x] 6.2 Probar en navegador: capas GAMC reales, leyenda, clic, buscador, recorrido, enlace compartido, `dwsScene.patch` de origen `agent`
- [x] 6.3 Verificar que la key no aparece en `dist/`
