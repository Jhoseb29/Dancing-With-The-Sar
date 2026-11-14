## ADDED Requirements

### Requirement: Capas municipales reales de Cochabamba
`basin-map` SHALL ofrecer como capas activables los 7 servicios WMS del Proyecto 02 del GAMC (Cuencas UH 8, Cuencas UH 7, Cuencas de Influencia, Drenaje e Influencia, Cota 2750, Limite Distritos, Emergencias), definidos en `layers.json` con su `service_id` real.

#### Scenario: Activar Emergencias
- **WHEN** el usuario activa "Emergencias"
- **THEN** el mapa pide teselas a `/api/gamc/wms` con `REQUEST=GetMap` y `service_id=e105a6ed-74bb-41a5-8c85-9360711ddf69`, y muestra la capa real

### Requirement: Leyenda e inspección
Cada capa GAMC visible SHALL mostrar su leyenda (`GetLegendGraphic`). Un clic en el mapa SHALL consultar `GetFeatureInfo` (`application/json`) sobre las capas visibles y mostrar los atributos devueltos, o "sin datos en este punto".

#### Scenario: Consultar una cuenca
- **WHEN** el usuario hace clic dentro de una cuenca con "Cuencas UH 8" activa
- **THEN** se muestran los atributos reales que devuelve el GAMC para ese punto

### Requirement: Sin datos personales
Los atributos de `GetFeatureInfo` MUST filtrarse antes de mostrarse o entregarse al agente: se aplica la lista blanca `featureInfoFields` del preset en `layers.json` cuando existe y, siempre, se descartan campos de datos personales (nombre del denunciante, celular, teléfono, correo, CI). Las entidades HTML se limpian.

#### Scenario: Emergencia con datos del denunciante
- **WHEN** el GAMC devuelve una emergencia con `Denunciante` y `Celular`
- **THEN** la UI muestra número, fecha, descripción, unidades y estado, y no muestra el nombre ni el celular

### Requirement: Key del GAMC solo en servidor
El navegador MUST NOT recibir ni enviar `GAMC_WMS_KEY`. Toda petición SHALL ir a `/api/gamc/wms`. En desarrollo, el proxy de `ng serve` SHALL leer la key de `.env`, eliminar cualquier `key` enviada por el cliente y rechazar (`403`) los `service_id` que no estén en `layers.json`. En producción `gateway-ts/gamc-proxy` SHALL cumplir el mismo contrato.

#### Scenario: Service id no autorizado
- **WHEN** se pide `/api/gamc/wms?service_id=00000000-0000-0000-0000-000000000000&REQUEST=GetMap`
- **THEN** el proxy responde `403` sin contactar al GAMC

#### Scenario: Revisión del bundle
- **WHEN** se busca la key en `dist/`
- **THEN** no aparece
