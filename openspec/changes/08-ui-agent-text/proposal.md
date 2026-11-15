## Why

Fase 2 de la hoja de ruta del agente (ver `07-scene-shadow-and-local-layers`). Con el shadow listo, el agente ya puede manejar la página: falta el agente en sí. En esta fase conversa **por teclado**, de forma natural (saluda, se presenta, explica lo que se ve, pregunta qué le interesa al usuario) y opera la UI aplicando parches al `SceneState`. La voz llega en la fase 4 y los eventos (incendios, inundaciones) en la fase 3.

## What Changes

- **Backend `compute-py`** (FastAPI, primer código del runtime Python):
  - `modules/llm_advisor`: puerto `LLMProviderPort` + adaptador **Gemini** (`google-genai`), con `GEMINI_API_KEY` y `GEMINI_MODEL` desde `.env`.
  - `modules/ui_agent` (Hexagonal): sesión de conversación, prompt de sistema, herramientas que se traducen en `ScenePatch`, validación contra `scene-patch.schema.json` y contra la configuración de UI, y espera del resultado que confirma el navegador.
  - WebSocket `GET /api/agent/session` con los mensajes de `agent-message.schema.json`.
- **Frontend**:
  - `core/agent/agent-client.ts` (TS puro): cliente WebSocket del protocolo.
  - `core/services/agent.service.ts`: transcripción como Signals; aplica los parches del agente en el `SceneStore` (origen `agent`) y devuelve el resultado y el estado reportado.
  - `layout/agent-dock` (3 archivos): panel conversacional siempre disponible; abierto o cerrado según `/panels/agentDock` del shadow.
- **Desarrollo:** el proxy de `ng serve` enruta `/api/agent` (WebSocket) a `compute-py` en `localhost:8000`. En producción lo enruta `gateway-ts` (`agent-gateway`).
- **Contrato nuevo:** `backend/shared/schemas/agent-message.schema.json`.

## Capabilities

### New Capabilities
- `ui-agent`: agente conversacional con Gemini que opera la UI por parches validados y no inventa datos.
- `agent-dock`: interfaz de conversación por teclado en el frontend.

### Modified Capabilities
- `scene-shadow` (07): el origen `agent` ya llega por WebSocket; el navegador responde cada parche con `scene.patch.result`.

## Impact

- **Backend:** primer código de `backend/compute-py` (`pyproject.toml`, `src/main.py`, `src/config/settings.py`, `src/modules/llm_advisor`, `src/modules/ui_agent`). Los módulos se nombran con guion bajo porque Python no puede importar carpetas con guion (`llm-advisor`, `harness-analyst`…); se recomienda renombrar las demás.
- **Frontend:** `core/agent/`, `core/services/agent.service.ts`, `layout/agent-dock/`, `proxy.conf.mjs`, i18n.
- **Secretos:** `GEMINI_API_KEY` solo en `.env` del backend; nunca en el navegador.
- **Cero mocks:** el agente solo afirma lo que sale de la configuración (`routes`, `places`, `layers`, `camera-tours`), del estado reportado y de herramientas con datos reales. Si le piden datos que aún no existen (p. ej. incendios en Bolivia), lo dice y explica que llegan en la fase 3.
- **Costo y abuso:** límite de turnos por minuto por sesión y de longitud de mensaje.
