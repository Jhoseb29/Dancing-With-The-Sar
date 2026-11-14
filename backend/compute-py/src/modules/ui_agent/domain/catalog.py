"""Catálogo de la UI: la misma configuración JSON que usa el navegador (OpenSpec 07)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class UiCatalog:
    routes: list[dict[str, Any]]
    places: list[dict[str, Any]]
    layers: list[dict[str, Any]]
    tours: list[dict[str, Any]]
    events: list[dict[str, Any]]

    @classmethod
    def load(cls, config_dir: Path) -> "UiCatalog":
        def read(name: str, key: str) -> list[dict[str, Any]]:
            return json.loads((config_dir / name).read_text(encoding="utf-8"))[key]

        return cls(
            routes=read("routes.json", "routes"),
            places=read("places.json", "places"),
            layers=read("layers.json", "layers"),
            tours=read("camera-tours.json", "tours"),
            events=read("events.json", "events"),
        )

    @property
    def route_ids(self) -> list[str]:
        return [r["id"] for r in self.routes]

    @property
    def place_ids(self) -> list[str]:
        return [p["id"] for p in self.places]

    @property
    def overlay_layer_ids(self) -> list[str]:
        """Capas municipales activables con set_layers (las de eventos las pone show_event)."""
        return [layer["id"] for layer in self.layers if layer.get("group") == "gamc"]

    @property
    def tour_ids(self) -> list[str]:
        return [t["id"] for t in self.tours]

    @property
    def event_ids(self) -> list[str]:
        return [e["id"] for e in self.events]

    def event(self, event_id: str) -> dict[str, Any] | None:
        return next((e for e in self.events if e["id"] == event_id), None)

    def route(self, route_id: str) -> dict[str, Any] | None:
        return next((r for r in self.routes if r["id"] == route_id), None)

    def layer(self, layer_id: str) -> dict[str, Any] | None:
        return next((layer for layer in self.layers if layer["id"] == layer_id), None)

    def describe(self, lang: str) -> str:
        """Resumen compacto para el prompt del agente."""
        lines = ["VISTAS (route):"]
        for r in self.routes:
            status = "" if r.get("status", "ready") == "ready" else " [pendiente de backend: no tiene datos aún]"
            lines.append(f"- {r['id']}: {r['agentDescription'][lang]}{status}")
        lines.append("LUGARES (place_id):")
        for p in self.places:
            approx = " (extensión aproximada)" if p.get("approximate") else ""
            lines.append(f"- {p['id']}: {p['name'][lang]}{approx}")
        lines.append("CAPAS MUNICIPALES (layer_id para set_layers, vista 'basin'):")
        for layer in self.layers:
            if layer.get("group") != "gamc":
                continue
            desc = layer.get("description", {}).get(lang, "")
            lines.append(f"- {layer['id']}: {layer['name'][lang]}. {desc} Fuente: {layer.get('attribution', layer.get('source', ''))}")
        lines.append("TIPOS DE EVENTO (event_type para show_event, vista 'events'):")
        for e in self.events:
            if e.get("available"):
                layer_names = ", ".join((self.layer(l) or {}).get("name", {}).get(lang, l) for l in e["layers"])
                extra = " + focos de calor NASA FIRMS (usar get_fire_stats para cifras)" if e.get("stats") == "firms" else ""
                verified = "; ".join(f"{v['placeId']} el {v['date']}" for v in e.get("verifiedDates", []))
                verified = f" Cobertura verificada: {verified}." if verified else ""
                lines.append(f"- {e['id']}: {e['name'][lang]}. Palabras clave: {', '.join(e['keywords'][lang])}. Imágenes: {layer_names}{extra}. Cómo leerla: {e['howToRead'][lang]}{verified}")
            else:
                lines.append(f"- {e['id']}: {e['name'][lang]} — NO DISPONIBLE: {e.get('unavailableReason', {}).get(lang, '')}")
        lines.append("RECORRIDOS DE CÁMARA (tour_id, vista 'orbit'):")
        for t in self.tours:
            lines.append(f"- {t['id']}: {t['name'][lang]}")
        return "\n".join(lines)
