## 1. Contratos

- [x] 1.1 `backend/shared/schemas/agent-message.schema.json` (cliente → servidor y servidor → cliente)

## 2. Backend `compute-py`

- [x] 2.1 `pyproject.toml`, `.venv` local, `src/main.py` (FastAPI) y `src/config/settings.py` (pydantic-settings desde `.env`)
- [x] 2.2 `modules/llm_advisor`: `LLMProviderPort` + adaptador Gemini (sin llamada automática de funciones)
- [x] 2.3 `modules/ui_agent/domain`: catálogo de UI desde JSON, herramientas → `ScenePatch`, validación con schema
- [x] 2.4 `modules/ui_agent/application`: sesión, prompt, bucle de herramientas con espera de `scene.patch.result`, límites
- [x] 2.5 `modules/ui_agent/adapters`: WebSocket `/api/agent/session`

## 3. Frontend

- [x] 3.1 `core/agent/agent-client.ts` (WebSocket del protocolo)
- [x] 3.2 `core/services/agent.service.ts` (transcripción, parches de origen `agent`, resultados)
- [x] 3.3 `layout/agent-dock` (3 archivos) + botón en la barra superior + i18n
- [x] 3.4 `proxy.conf.mjs`: `/api/agent` → `ws://localhost:8000`

## 4. Verificación

- [x] 4.1 Sin key: `llm_not_configured` visible en el panel, app intacta
- [x] 4.2 Con key: saludo, navegación por pedido, capas GAMC, recorrido, pregunta sin datos (incendios)
- [x] 4.3 `ng build` sin warnings; la key de Gemini no aparece en `dist/`
