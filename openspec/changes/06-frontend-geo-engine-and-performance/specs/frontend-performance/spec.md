## ADDED Requirements

### Requirement: Detección de cambios zoneless
La aplicación SHALL arrancar con detección de cambios zoneless (`provideZonelessChangeDetection()` o el valor por defecto equivalente de Angular 22) y MUST NOT incluir `zone.js` en los polyfills.

#### Scenario: Arranque
- **WHEN** se inspecciona `app.config.ts` y `angular.json`
- **THEN** la detección zoneless está activa y `zone.js` no aparece en `polyfills`

### Requirement: Carga diferida del motor geoespacial
`maplibre-gl`, `@deck.gl/*`, `geotiff`, `uplot`, `cesium` y `satellite.js` MUST NOT formar parte del bundle inicial. SHALL cargarse solo dentro de las rutas lazy que los usan (`basin-map`, `temporal-lab`, `risk-dashboard`, `orbit-view`, vista de deformación) o mediante `@defer`. Los assets estáticos de Cesium (`Workers/`, `Assets/`, `Widgets/`, `ThirdParty/`) SHALL copiarse como assets y solo pedirse al entrar a una vista 3D.

#### Scenario: Primera carga en la portada
- **WHEN** el usuario abre la ruta inicial sin entrar a una vista de mapa
- **THEN** el bundle inicial no contiene código de MapLibre, deck.gl ni Cesium

#### Scenario: Cambio entre vista 2.5D y 3D
- **WHEN** el usuario pasa de `basin-map` a `orbit-view`
- **THEN** Cesium se descarga en ese momento y MapLibre no se vuelve a descargar al regresar (queda en caché del navegador)

### Requirement: Presupuestos de tamaño
`angular.json` SHALL definir presupuestos de build: bundle inicial con advertencia en 350 kB y error en 500 kB (tamaño sin comprimir, que es lo que mide Angular), y estilos por componente con error en 8 kB. El build de producción MUST fallar si se exceden los límites de error.

#### Scenario: Dependencia pesada agregada al bundle inicial
- **WHEN** alguien importa deck.gl desde un archivo del bundle inicial
- **THEN** `ng build` falla por exceder el presupuesto

### Requirement: Caché de teselas y recursos
La aplicación SHALL registrar un Service Worker (`@angular/service-worker`) que cachee con estrategia `performance` las teselas COG/PMTiles/terrain (terrain-RGB y quantized-mesh), las imágenes base de NASA GIBS y las leyendas WMS, y con estrategia `freshness` el catálogo, las series y los elementos orbitales. Las respuestas de datos con credenciales o errores MUST NOT cachearse.

#### Scenario: Volver a una zona ya vista
- **WHEN** el usuario regresa a una zona y fecha ya visitadas
- **THEN** las teselas se sirven desde caché sin nuevas peticiones al gateway

#### Scenario: Nuevas adquisiciones
- **WHEN** el catálogo publica una nueva fecha `VALIDATED`
- **THEN** la app la muestra en la siguiente carga, porque el catálogo usa estrategia `freshness`

### Requirement: Fechas dirigidas por el catálogo
Las ventanas temporales y fechas disponibles en `temporal-lab` MUST obtenerse del endpoint de catálogo de `catalog-tiles`. El código del frontend MUST NOT contener fechas de adquisición fijas; las fechas de referencia del brief (temporada seca, inicio de lluvias, gap 2026-07-27 a 2026-08-10) SHALL llegar también como metadatos del catálogo.

#### Scenario: Nueva adquisición cada 12 días
- **WHEN** `catalog-tiles` agrega una adquisición nueva
- **THEN** aparece en el selector temporal sin cambiar código del frontend

### Requirement: Estado compartible en la URL
La vista activa (ruta, cuenca, fecha o par de fechas, capas visibles, polarización, centro y zoom del mapa, idioma) SHALL reflejarse en los query params del router, actualizándose con debounce, y SHALL restaurarse al abrir el enlace.

#### Scenario: Compartir una vista en la demo
- **WHEN** el usuario copia la URL con la cuenca sur, la capa `HVHV` y el par de fechas seca vs lluvias
- **THEN** otra persona que abre la URL ve exactamente la misma vista

### Requirement: Diseño responsive y accesible
Las vistas SHALL funcionar desde 360 px de ancho sin scroll horizontal. Los controles del mapa y la línea de tiempo MUST ser operables con teclado y tener etiquetas accesibles. Las escalas de color de capas SAR SHOULD ser perceptualmente uniformes y aptas para daltonismo.

#### Scenario: Uso en celular por defensa civil
- **WHEN** se abre `risk-dashboard` en un celular de 360 px de ancho
- **THEN** el mapa y el panel de riesgo son utilizables sin scroll horizontal

### Requirement: Idiomas español e inglés en vivo
La interfaz SHALL ofrecer español (por defecto) e inglés con `@jsverse/transloco`, cargando `assets/i18n/{lang}.json` bajo demanda. El cambio de idioma MUST aplicarse sin recargar la página. El idioma activo SHALL guardarse en el SignalStore y en la URL (`?lang=`). Los textos de UI MUST NOT estar fijos en componentes. Los textos generados por el backend (Harness 2) SHALL pedirse en el idioma activo.

#### Scenario: Jurado internacional
- **WHEN** el usuario cambia a inglés mientras mira `temporal-lab`
- **THEN** los textos de la interfaz se muestran en inglés al instante, sin recargar y sin perder la fecha ni las capas seleccionadas

#### Scenario: Compartir en inglés
- **WHEN** el usuario comparte la URL de una vista en inglés
- **THEN** quien la abre la ve en inglés

#### Scenario: Explicaciones didácticas
- **WHEN** `didactic-insights` está en inglés
- **THEN** pide al backend las explicaciones en inglés en vez de traducirlas en el cliente
