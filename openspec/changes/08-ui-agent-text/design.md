## Context

`07` dejó el `SceneState` con parches validados y un gancho de desarrollo que simula al agente. `backend/` está vacío. El equipo eligió Gemini como proveedor LLM. La arquitectura (`docs/01`, `docs/02`) ubica la integración LLM en `compute-py` detrás de un puerto (`LLMProviderPort`).

## Goals / Non-Goals

**Goals:**
- Conversación natural por teclado: saludo y presentación al abrir, explicación de la vista, preguntas de seguimiento.
- El agente opera la UI solo mediante parches, que el navegador valida y confirma.
- Proveedor LLM intercambiable (puerto), Gemini como adaptador inicial.

**Non-Goals:**
- Voz (fase 4), eventos e imágenes por tipo (fase 3), `agent-gateway` en `gateway-ts` (el equipo backend lo agrega como relé).

## Decisions

### D1. Dónde corre
`compute-py` expone el WebSocket. En desarrollo `ng serve` lo enruta directo (`/api/agent` → `ws://localhost:8000`). En producción `gateway-ts/agent-gateway` hace de relé (autenticación, límites) sin lógica de agente.

### D2. Bucle del agente (manual, sin llamada automática de funciones)
1. El cliente envía `user.text` (o `session.start` para el saludo) junto con el `SceneState` y el estado reportado más recientes.
2. El servicio llama al LLM con: prompt de sistema, catálogo de la UI (rutas, lugares, capas, recorridos), estado actual, historial y declaraciones de herramientas.
3. Si el modelo pide herramientas: cada herramienta de UI se convierte en un `ScenePatch` → se valida en el servidor (schema + ids) → se envía `scene.patch` → se espera `scene.patch.result` (timeout 5 s) → el resultado (aceptado o rechazado con motivo, estado reportado nuevo) vuelve al modelo como respuesta de la función.
4. Se repite hasta que el modelo responde con texto (máximo 6 pasos por turno) → `agent.text` y `agent.turn.end`.
- *Alternativa descartada:* llamada automática de funciones del SDK. No permite esperar la confirmación del navegador ni validar antes de ejecutar.

### D3. Herramientas
| Herramienta | Efecto |
| :--- | :--- |
| `navigate(route)` | `/route` |
| `fly_to_place(place_id)` | `/camera/placeId`, `/search/selectedPlaceId`, cancela recorrido; si la vista no tiene motor, abre `basin` |
| `start_tour(tour_id)` | `/route = orbit`, `/camera/tourId` |
| `set_layers(visible_layer_ids)` | reemplaza `/layers` (con la opacidad por defecto de cada preset) |
| `set_time_speed(speed)` | `/time/speed` |
| `follow_satellite(enabled)` | `/camera/follow` |
| `set_language(lang)` | `/lang` |
| `set_side_panel(visible)` | `/panels/layerPanel` (oculta o muestra el panel lateral de la vista; añadido 2026-11-14) |
| `get_view()` | sin parche: devuelve estado y reportado actuales |

Los ids válidos se pasan como `enum` en las declaraciones (generadas desde la configuración JSON), así el modelo no puede inventar lugares ni capas.

### D4. Prompt y grounding
- Persona: guía de "control de misión" de Dancing with the SARs, cálida y breve (2–4 frases por respuesta), en el idioma activo.
- Reglas: solo afirmar lo que esté en el catálogo, el estado o resultados de herramientas; no inventar cifras ni fechas; si no hay datos, decirlo y ofrecer lo disponible; terminar con una pregunta o sugerencia cuando ayude.
- El catálogo de la UI se carga desde `frontend/src/assets/config/*.json` (ruta configurable `UI_CONFIG_DIR`): misma fuente que el navegador.

### D5. Proveedor LLM
- `LLMProviderPort.generate(system, history, tools) -> LLMTurn(text, function_calls)`.
- Adaptador Gemini con `google-genai` (`client.aio.models.generate_content`, `GenerateContentConfig` con `system_instruction`, `tools` y llamada automática de funciones desactivada).
- `GEMINI_MODEL` configurable (por defecto `gemini-4-hydrogen`) y `GEMINI_FALLBACK_MODEL` (por defecto `gemini-3.8-flash`, estable) usado automáticamente ante 404/5xx. Elección medida el 2026-11-14 con el agente real y el pedido "muéstrame las emergencias de Cochabamba": hydrogen 3,4–4,1 s con las 3 acciones; 3.8-flash 6,1–6,3 s con las 3; 3.5-flash-lite 1,2–2,1 s pero solo 1 de 3.

### D6. Límites
Mensajes de usuario ≤ 500 caracteres; ≤ 10 turnos por minuto por sesión; historial recortado a los últimos 20 mensajes.

## Risks / Trade-offs

- **[Riesgo] Respuestas sin streaming** → la respuesta llega completa por paso. Aceptable para teclado; la fase 4 (voz) requerirá streaming.
- **[Riesgo] El navegador rechaza un parche** → el modelo recibe el motivo y puede corregirse o explicarlo.
- **[Trade-off] Catálogo leído del frontend** → acopla rutas de archivos; se mitiga con `UI_CONFIG_DIR` y los schemas compartidos.
