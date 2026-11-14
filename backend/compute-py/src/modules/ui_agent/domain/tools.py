"""Herramientas del agente de UI (OpenSpec 08, D3). Cada una produce operaciones JSON Patch
sobre el SceneState; nunca toca la UI directamente."""

from __future__ import annotations

from datetime import date
from typing import Any

from modules.llm_advisor.ports.llm_provider import ToolDeclaration
from modules.ui_agent.domain.catalog import UiCatalog

PatchOps = list[dict[str, Any]]


class ToolError(ValueError):
    """Argumentos inválidos para una herramienta (se devuelve al modelo, no se rompe la sesión)."""


VIEW_TOOL = "get_view"
FIRE_STATS_TOOL = "get_fire_stats"
DATA_TOOLS = {VIEW_TOOL, FIRE_STATS_TOOL}

DATE_PATTERN = "^\\d{4}-\\d{2}-\\d{2}$"


def declarations(catalog: UiCatalog) -> list[ToolDeclaration]:
    """Declaraciones con `enum` generados desde la configuración: el modelo no puede inventar ids."""
    return [
        ToolDeclaration(
            name="navigate",
            description="Abre una vista de la web. Usar 'orbit' para el planeta y el satélite NISAR, 'basin' para el mapa de la cuenca con capas municipales.",
            parameters={
                "type": "object",
                "properties": {"route": {"type": "string", "enum": catalog.route_ids}},
                "required": ["route"],
            },
        ),
        ToolDeclaration(
            name="fly_to_place",
            description="Mueve la cámara de la vista actual hasta un lugar del catálogo. Si la vista no tiene mapa, abre la cuenca.",
            parameters={
                "type": "object",
                "properties": {"place_id": {"type": "string", "enum": catalog.place_ids}},
                "required": ["place_id"],
            },
        ),
        ToolDeclaration(
            name="start_tour",
            description="Inicia un recorrido de cámara animado sobre el planeta (abre la vista 'orbit').",
            parameters={
                "type": "object",
                "properties": {"tour_id": {"type": "string", "enum": catalog.tour_ids}},
                "required": ["tour_id"],
            },
        ),
        ToolDeclaration(
            name="set_layers",
            description="Define qué capas municipales del GAMC se muestran en el mapa de la cuenca (reemplaza la selección actual). Lista vacía = ninguna.",
            parameters={
                "type": "object",
                "properties": {
                    "visible_layer_ids": {
                        "type": "array",
                        "items": {"type": "string", "enum": catalog.overlay_layer_ids},
                    }
                },
                "required": ["visible_layer_ids"],
            },
        ),
        ToolDeclaration(
            name="set_time_speed",
            description="Velocidad del reloj de la vista del planeta (1 = tiempo real, 60 = un minuto por segundo).",
            parameters={
                "type": "object",
                "properties": {"speed": {"type": "number", "minimum": 1, "maximum": 3600}},
                "required": ["speed"],
            },
        ),
        ToolDeclaration(
            name="follow_satellite",
            description="Hace que la cámara del planeta siga al satélite NISAR (o deje de seguirlo).",
            parameters={
                "type": "object",
                "properties": {"enabled": {"type": "boolean"}},
                "required": ["enabled"],
            },
        ),
        ToolDeclaration(
            name="set_language",
            description="Cambia el idioma de la interfaz.",
            parameters={
                "type": "object",
                "properties": {"lang": {"type": "string", "enum": ["es", "en"]}},
                "required": ["lang"],
            },
        ),
        ToolDeclaration(
            name="show_event",
            description="Muestra un tipo de evento (incendios, inundaciones, radar NISAR, vegetación) con las imágenes satelitales adecuadas para un lugar y rango de fechas. Abre la vista 'events'. Las fechas no pueden ser futuras.",
            parameters={
                "type": "object",
                "properties": {
                    "event_type": {"type": "string", "enum": [e["id"] for e in catalog.events if e.get("available")]},
                    "place_id": {"type": "string", "enum": catalog.place_ids},
                    "start_date": {"type": "string", "pattern": DATE_PATTERN, "description": "YYYY-MM-DD"},
                    "end_date": {"type": "string", "pattern": DATE_PATTERN, "description": "YYYY-MM-DD"},
                    "date": {"type": "string", "pattern": DATE_PATTERN, "description": "Día a mostrar dentro del rango (opcional; por defecto el último día o una fecha con cobertura verificada)."},
                },
                "required": ["event_type", "place_id", "start_date", "end_date"],
            },
        ),
        ToolDeclaration(
            name="set_event_date",
            description="Cambia el día mostrado en la vista de eventos (debe estar dentro del rango del evento activo).",
            parameters={
                "type": "object",
                "properties": {"date": {"type": "string", "pattern": DATE_PATTERN}},
                "required": ["date"],
            },
        ),
        ToolDeclaration(
            name=FIRE_STATS_TOOL,
            description="Cifras reales de focos de calor de NASA FIRMS (VIIRS) para un lugar y rango (máx. 2 años): total, serie mensual y día pico. Filtra por el límite real de Bolivia. Puede tardar si el rango es largo.",
            parameters={
                "type": "object",
                "properties": {
                    "place_id": {"type": "string", "enum": catalog.place_ids},
                    "start_date": {"type": "string", "pattern": DATE_PATTERN},
                    "end_date": {"type": "string", "pattern": DATE_PATTERN},
                },
                "required": ["place_id", "start_date", "end_date"],
            },
        ),
        ToolDeclaration(
            name=VIEW_TOOL,
            description="Devuelve lo que el usuario está viendo ahora (vista, cámara real, capas y su estado). No cambia nada.",
            parameters={"type": "object", "properties": {}},
        ),
    ]


def build_ops(name: str, args: dict[str, Any], scene: dict[str, Any], catalog: UiCatalog) -> PatchOps:
    """Traduce una llamada de herramienta a operaciones JSON Patch."""
    if name == "navigate":
        route = _one_of(args, "route", catalog.route_ids)
        return [{"op": "replace", "path": "/route", "value": route}]

    if name == "fly_to_place":
        place = _one_of(args, "place_id", catalog.place_ids)
        ops: PatchOps = []
        current = catalog.route(scene.get("route", ""))
        if not current or current.get("engine") == "none":
            ops.append({"op": "replace", "path": "/route", "value": "basin"})
        ops += [
            {"op": "replace", "path": "/search/selectedPlaceId", "value": place},
            {"op": "replace", "path": "/camera/tourId", "value": None},
            {"op": "replace", "path": "/camera/placeId", "value": place},
        ]
        return ops

    if name == "start_tour":
        tour = _one_of(args, "tour_id", catalog.tour_ids)
        return [
            {"op": "replace", "path": "/route", "value": "orbit"},
            {"op": "replace", "path": "/camera/follow", "value": False},
            {"op": "replace", "path": "/camera/tourId", "value": tour},
        ]

    if name == "set_layers":
        ids = args.get("visible_layer_ids")
        if not isinstance(ids, list) or any(i not in catalog.overlay_layer_ids for i in ids):
            raise ToolError(f"visible_layer_ids debe contener solo: {', '.join(catalog.overlay_layer_ids)}")
        layers = []
        for layer_id in dict.fromkeys(ids):
            preset = catalog.layer(layer_id) or {}
            layers.append({"presetId": layer_id, "visible": True, "opacity": preset.get("defaultOpacity", 1)})
        return [{"op": "replace", "path": "/layers", "value": layers}]

    if name == "set_time_speed":
        speed = args.get("speed")
        if not isinstance(speed, (int, float)) or not 1 <= speed <= 3600:
            raise ToolError("speed debe estar entre 1 y 3600")
        return [{"op": "replace", "path": "/time/speed", "value": speed}]

    if name == "follow_satellite":
        enabled = args.get("enabled")
        if not isinstance(enabled, bool):
            raise ToolError("enabled debe ser booleano")
        ops = [{"op": "replace", "path": "/camera/follow", "value": enabled}]
        if enabled and scene.get("route") != "orbit":
            ops.insert(0, {"op": "replace", "path": "/route", "value": "orbit"})
        return ops

    if name == "show_event":
        event = catalog.event(str(args.get("event_type")))
        if not event or not event.get("available"):
            raise ToolError("event_type no disponible: usa uno de " + ", ".join(e["id"] for e in catalog.events if e.get("available")))
        place = _one_of(args, "place_id", catalog.place_ids)
        start, end = _date(args, "start_date"), _date(args, "end_date")
        today = date.today().isoformat()
        if start > end:
            raise ToolError("start_date debe ser anterior o igual a end_date")
        if end > today:
            end = today
        verified = next((v["date"] for v in event.get("verifiedDates", []) if v["placeId"] == place and start <= v["date"] <= end), None)
        # Sin fecha pedida: la pasada verificada o ayer (la imagen diaria de hoy suele estar incompleta).
        yesterday = date.fromordinal(date.today().toordinal() - 1).isoformat()
        day = args.get("date") or verified or (min(end, yesterday) if start <= yesterday else end)
        if not (start <= day <= end):
            raise ToolError("date debe estar dentro del rango")
        # Las capas del evento no van a /layers (son de la cuenca): el mapa las toma de events.json.
        return [
            {"op": "replace", "path": "/route", "value": "events"},
            {"op": "replace", "path": "/event", "value": {"type": event["id"], "placeId": place, "start": start, "end": end}},
            {"op": "replace", "path": "/time/mode", "value": "range"},
            {"op": "replace", "path": "/time/start", "value": start},
            {"op": "replace", "path": "/time/end", "value": end},
            {"op": "replace", "path": "/time/date", "value": day},
            {"op": "replace", "path": "/camera/tourId", "value": None},
            {"op": "replace", "path": "/camera/placeId", "value": place},
            {"op": "replace", "path": "/search/selectedPlaceId", "value": place},
        ]

    if name == "set_event_date":
        day = _date(args, "date")
        event = scene.get("event")
        if not event:
            raise ToolError("No hay un evento activo: usa show_event primero")
        if not (event["start"] <= day <= event["end"]):
            raise ToolError(f"La fecha debe estar entre {event['start']} y {event['end']}")
        return [{"op": "replace", "path": "/time/date", "value": day}]

    if name == "set_language":
        lang = _one_of(args, "lang", ["es", "en"])
        return [{"op": "replace", "path": "/lang", "value": lang}]

    raise ToolError(f"Herramienta desconocida: {name}")


def _date(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    try:
        return date.fromisoformat(str(value)).isoformat()
    except ValueError as err:
        raise ToolError(f"{key} debe ser una fecha YYYY-MM-DD") from err


def _one_of(args: dict[str, Any], key: str, allowed: list[str]) -> str:
    value = args.get(key)
    if value not in allowed:
        raise ToolError(f"{key} debe ser uno de: {', '.join(allowed)}")
    return value
