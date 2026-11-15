## ADDED Requirements

### Requirement: Conversación natural
Al iniciar una sesión el agente SHALL saludar, presentarse y explicar brevemente lo que el usuario está viendo, terminando con una pregunta sobre qué le gustaría conocer. Las respuestas SHALL ser breves (2–4 frases) y en el idioma activo del `SceneState`.

#### Scenario: Saludo
- **WHEN** el usuario abre el panel del agente en `orbit-view`
- **THEN** el agente saluda, se presenta como guía de Dancing with the SARs, menciona que ve el satélite NISAR en órbita y pregunta qué quiere explorar

### Requirement: Operar la UI solo por parches validados
Toda acción del agente sobre la UI SHALL expresarse como `ScenePatch` de origen `agent`, validado en el servidor contra `scene-patch.schema.json` y los ids de la configuración, enviado como `scene.patch` y confirmado por el navegador con `scene.patch.result`. El agente MUST recibir el resultado (incluido el rechazo y su motivo) antes de responder.

#### Scenario: Pedir ver la cuenca
- **WHEN** el usuario escribe "muéstrame las emergencias en Cochabamba"
- **THEN** el agente aplica parches para abrir `basin`, encuadrar `cochabamba-city` y activar `gamc-emergencias`, y luego lo cuenta en su respuesta

#### Scenario: Parche rechazado
- **WHEN** el navegador rechaza un parche por conflicto con el usuario
- **THEN** el agente no afirma que el cambio se hizo y lo explica

### Requirement: Sin datos inventados
El agente MUST NOT afirmar cifras, fechas, eventos ni capas que no provengan de la configuración, del estado reportado o de resultados de herramientas. Si se le piden datos no disponibles, SHALL decirlo y ofrecer lo que sí existe.

#### Scenario: Pregunta por incendios
- **WHEN** el usuario pregunta "¿hubo incendios en Bolivia los últimos 2 años?"
- **THEN** el agente explica que esos datos aún no están conectados (llegan en la fase 3) y ofrece lo disponible

### Requirement: Secretos y límites
`GEMINI_API_KEY` MUST leerse solo del entorno del backend. El servicio SHALL limitar los mensajes a 500 caracteres y a 10 turnos por minuto por sesión, respondiendo un `error` con código `rate_limited` o `too_long`. Si falta la key SHALL responder `error` con código `llm_not_configured`.

#### Scenario: Sin key configurada
- **WHEN** se abre una sesión y `GEMINI_API_KEY` está vacía
- **THEN** el cliente recibe `error` `llm_not_configured` y la UI lo muestra sin romperse
