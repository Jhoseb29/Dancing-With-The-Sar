## ADDED Requirements

### Requirement: Focos filtrados por lugar real
`compute-py` SHALL obtener focos de NASA FIRMS (API `area`) y SHALL filtrarlos por el polígono real de Bolivia (Natural Earth) para `bolivia` o por el bbox del lugar para lugares de Cochabamba. MUST NOT contar focos de países vecinos dentro del bbox.

#### Scenario: Frontera con Brasil
- **WHEN** hay un foco en Brasil dentro del rectángulo de Bolivia
- **THEN** no se cuenta para `bolivia`

### Requirement: Estadísticas y caché
`GET /api/events/fires/stats` SHALL devolver total, serie mensual, día pico, fuente y fecha de consulta para rangos de hasta 2 años, usando caché en disco por bloque de 5 días. `FIRMS_MAP_KEY` MUST leerse solo del entorno del backend.

#### Scenario: Segunda consulta
- **WHEN** se repite la misma consulta
- **THEN** responde desde caché sin nuevas peticiones a FIRMS

#### Scenario: Sin key
- **WHEN** falta `FIRMS_MAP_KEY`
- **THEN** responde `503` con código `firms_not_configured`

### Requirement: El agente usa cifras reales
Para preguntas sobre incendios el agente SHALL llamar `get_fire_stats` y SHALL citar solo las cifras devueltas (total, meses, día pico) indicando la fuente; si la herramienta falla, SHALL decirlo.

#### Scenario: Incendios en Bolivia
- **WHEN** el usuario pregunta por incendios en Bolivia los últimos 2 años
- **THEN** el agente muestra el evento `wildfire`, consulta las estadísticas y responde con el total y el día pico de FIRMS, saltando a ese día en la vista
