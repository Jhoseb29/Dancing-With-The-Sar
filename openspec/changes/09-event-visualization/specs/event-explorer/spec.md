## ADDED Requirements

### Requirement: Catálogo de eventos en JSON
Los tipos de evento SHALL definirse en `assets/config/events.json` (id, nombres y palabras clave es/en, capas en orden, guía de lectura, fuente de estadísticas, disponibilidad), conforme a `ui-config.schema.json`. El agente y la UI MUST usar solo esos tipos.

#### Scenario: Tipo no disponible
- **WHEN** el usuario pide deformación del suelo
- **THEN** el agente explica que ese tipo todavía no tiene datos (`available: false`) y ofrece otro

### Requirement: Imágenes del satélite correcto por tipo
Al mostrar un evento, la vista `events` SHALL dibujar exactamente las capas del tipo en `events.json`, para el día `/time/date`, con su leyenda oficial y la guía "cómo leer esta imagen".

#### Scenario: Inundación
- **WHEN** se muestra un evento `flood` en Cochabamba
- **THEN** se ve la capa MODIS Flood 2-Day (celeste agua, rojo inundación, amarillo recurrente, gris sin datos) sobre el falso color 7-2-1, con su leyenda

#### Scenario: Las capas de la cuenca no se pierden
- **WHEN** el usuario tiene capas GAMC en `basin`, abre un evento y vuelve a `basin`
- **THEN** las capas GAMC siguen activas y en `events` no se dibujan (cada vista tiene sus capas)

#### Scenario: Radar NISAR sobre Cochabamba
- **WHEN** se muestra un evento `radar` en Cochabamba el 2026-10-25
- **THEN** se ve la imagen NISAR GCOV real de ese día y la vista ofrece saltar a las otras fechas con cobertura verificada

### Requirement: Selector de día
La vista SHALL permitir cambiar el día (anterior, siguiente, fecha) dentro del rango del evento, aplicando `/time/date`. Si un día no tiene cobertura, SHALL indicarlo sin ocultar el resto.

#### Scenario: Día siguiente
- **WHEN** el usuario pulsa "día siguiente"
- **THEN** `/time/date` avanza un día y las capas se recargan para esa fecha

### Requirement: Estadísticas de incendios
Para `wildfire` la vista SHALL mostrar el total de focos, la serie mensual y el día pico desde `GET /api/events/fires/stats`, y los focos del día desde `GET /api/events/fires`, citando la fuente FIRMS. Si FIRMS no está configurado SHALL indicarlo.

#### Scenario: Sin MAP_KEY
- **WHEN** `FIRMS_MAP_KEY` no está configurada
- **THEN** la vista muestra las imágenes MODIS y un aviso de que las estadísticas no están disponibles
