"""Analysis themes: deterministic rules that turn "what the user cares about" into pipeline parameters.

The intent parser only picks a theme key; everything else (time window, how many dates,
which metrics matter) is decided here, so the behaviour is predictable and testable.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Theme:
    key: str
    label: str
    default_days: int  # look-back window when the user gives no dates ("últimos", "recientes")
    granules: int  # dates to analyse; >= 2 enables change detection
    focus_metrics: tuple[str, ...]
    radar_signal: str  # what to look for, in physical terms (goes to the interpreter)
    keywords: tuple[str, ...] = ()  # lowercase substrings, used only by the offline intent fallback


THEMES: dict[str, Theme] = {t.key: t for t in (
    Theme("incendios", "Incendios y áreas quemadas", 90, 2,
          ("vegetation_canopy_pct", "rvi_mean", "cross_mean_db", "bare_soil_pct"),
          "Pérdida de biomasa: caída de la polarización cruzada (HV/VH) y del RVI entre fechas; vegetación que pasa a suelo desnudo.",
          ("incendio", "fuego", "quema", "chaqueo", "humo", "fire", "burn")),
    Theme("inundacion", "Inundaciones y anegamiento", 60, 2,
          ("water_flood_pct", "co_mean_db", "bare_soil_pct"),
          "Agua libre: co-polar (HH/VV) y cruzada muy bajas (reflexión especular); aumento del % de agua entre fechas.",
          ("inund", "desborde", "riada", "crecida", "anega", "mazamorra", "flood")),
    Theme("cuenca_hidrica", "Cuencas, lagunas y recursos hídricos", 365, 3,
          ("water_flood_pct", "bare_soil_pct", "co_mean_db"),
          "Extensión de cuerpos de agua y humedad del suelo (γ0 sube con la humedad) a lo largo del año.",
          ("cuenca", "laguna", "lago", "río", "embalse", "agua", "sequía", "sequia", "basin", "lake", "river")),
    Theme("vegetacion", "Vegetación, bosques y deforestación", 365, 2,
          ("vegetation_canopy_pct", "rvi_mean", "cross_mean_db"),
          "Dispersión volumétrica: cruzada (HV/VH) y RVI altos en bosque; su caída indica desmonte o estrés.",
          ("bosque", "deforest", "vegetaci", "cultivo", "desmonte", "forest", "crop")),
    Theme("urbano", "Expansión urbana e infraestructura", 365, 2,
          ("urban_double_bounce_pct", "co_mean_db"),
          "Rebote doble (co-polar alta con co − cruzada ≥ 10 dB) en edificaciones.",
          ("urban", "ciudad", "construcc", "expansi", "city", "building")),
    Theme("general", "Panorama general del territorio", 120, 1,
          ("vegetation_canopy_pct", "bare_soil_pct", "water_flood_pct", "urban_double_bounce_pct"),
          "Composición general de mecanismos de dispersión."),
)}

DEFAULT_THEME = "general"


def get_theme(key: str | None) -> Theme:
    return THEMES.get(key or DEFAULT_THEME, THEMES[DEFAULT_THEME])


def theme_from_text(text: str) -> str:
    """Offline fallback: first theme whose keywords appear in the text."""
    low = text.lower()
    return next((t.key for t in THEMES.values() if any(k in low for k in t.keywords)), DEFAULT_THEME)
