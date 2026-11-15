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


THEMES: dict[str, Theme] = {t.key: t for t in (
    Theme("incendios", "Incendios y áreas quemadas", 90, 2,
          ("vegetation_canopy_pct", "rvi_mean", "HVHV_mean_db", "bare_soil_pct"),
          "Pérdida de biomasa: caída de HV y del RVI entre fechas; vegetación que pasa a suelo desnudo."),
    Theme("inundacion", "Inundaciones y anegamiento", 60, 2,
          ("water_flood_pct", "HHHH_mean_db", "bare_soil_pct"),
          "Agua libre: HH y HV muy bajos (reflexión especular); aumento del % de agua entre fechas."),
    Theme("cuenca_hidrica", "Cuencas, lagunas y recursos hídricos", 365, 3,
          ("water_flood_pct", "bare_soil_pct", "HHHH_mean_db"),
          "Extensión de cuerpos de agua y humedad del suelo (γ0 sube con la humedad) a lo largo del año."),
    Theme("vegetacion", "Vegetación, bosques y deforestación", 365, 2,
          ("vegetation_canopy_pct", "rvi_mean", "HVHV_mean_db"),
          "Dispersión volumétrica: HV y RVI altos en bosque; su caída indica desmonte o estrés."),
    Theme("urbano", "Expansión urbana e infraestructura", 365, 2,
          ("urban_double_bounce_pct", "HHHH_mean_db"),
          "Rebote doble (HH alto con HH−HV ≥ 10 dB) en edificaciones."),
    Theme("general", "Panorama general del territorio", 120, 1,
          ("vegetation_canopy_pct", "bare_soil_pct", "water_flood_pct", "urban_double_bounce_pct"),
          "Composición general de mecanismos de dispersión."),
)}

DEFAULT_THEME = "general"


def get_theme(key: str | None) -> Theme:
    return THEMES.get(key or DEFAULT_THEME, THEMES[DEFAULT_THEME])
