"""Radar sensors the harness can read. NISAR is primary; Sentinel-1 (OPERA RTC-S1) is the fallback
when NISAR has no usable takes (e.g. the Jan–Jun 2026 processing gap over Bolivia).

Both end up as the same SarScene (linear gamma0, co-pol + cross-pol), so physics, globe,
objects, hotspots and the interpreter are sensor-agnostic.
"""
from __future__ import annotations

from dataclasses import dataclass

from .settings import DEFAULT_COLLECTIONS


@dataclass(frozen=True)
class Sensor:
    key: str  # "nisar" | "sentinel-1"
    label: str
    band: str  # "L" | "C"
    wavelength_cm: float
    center_frequency_hz: float
    collections: tuple[str, ...]
    co_term: str  # covariance-term name used in SarScene.layers
    cross_term: str
    native_spacing_m: float


NISAR = Sensor("nisar", "NISAR (NASA-ISRO) · banda L", "L", 23.84, 1.2575e9, DEFAULT_COLLECTIONS,
               "HHHH", "HVHV", 20.0)
SENTINEL1 = Sensor("sentinel-1", "Sentinel-1 (ESA) · OPERA RTC · banda C", "C", 5.55, 5.405e9, ("OPERA_L2_RTC-S1_V1",),
                   "VVVV", "VHVH", 30.0)

SENSORS = {s.key: s for s in (NISAR, SENTINEL1)}
