"""Reader for the NISAR L2 GCOV HDF5 product layout (metadata + grids)."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import h5py
import numpy as np
from pyproj import Transformer

IDENT_PATH = "science/LSAR/identification"
GRIDS_PATH = "science/LSAR/GCOV/grids"
SWATHS_PATH = "science/LSAR/GCOV/metadata/sourceData/swaths"
COVARIANCE_TERMS = ("HHHH", "HVHV", "VVVV", "VHVH")
CO_POL_TERMS = ("HHHH", "VVVV")
CROSS_POL_TERMS = ("HVHV", "VHVH")
SPEED_OF_LIGHT = 299_792_458.0


def decode(value: Any) -> Any:
    """Convert h5py/numpy scalars, bytes and arrays into plain Python values."""
    if isinstance(value, h5py.Dataset):
        value = value[()]
    if isinstance(value, (bytes, np.bytes_)):
        return value.decode("utf-8", errors="replace").strip()
    if isinstance(value, np.ndarray):
        return [decode(v) for v in value.tolist()] if value.ndim else decode(value.item())
    if isinstance(value, np.generic):
        return value.item()
    return value


def _get(group: h5py.Group | None, key: str, default: Any = None) -> Any:
    return decode(group[key]) if group is not None and key in group else default


# ---------------------------------------------------------------- metadata
@dataclass
class Identification:
    granule_id: str
    mission: str | None
    radar_band: str
    orbit_direction: str | None
    look_direction: str | None
    start_time: str | None
    end_time: str | None
    track: int | None
    frame: int | None
    product_version: str | None
    footprint: list[list[float]] = field(default_factory=list)  # [[lon, lat], ...]


def read_identification(h5: h5py.File, fallback_id: str) -> Identification:
    ident = h5.get(IDENT_PATH)
    return Identification(
        granule_id=_get(ident, "granuleId", fallback_id),
        mission=_get(ident, "missionId"),
        radar_band=_get(ident, "radarBand", "L"),
        orbit_direction=_get(ident, "orbitPassDirection"),
        look_direction=_get(ident, "lookDirection"),
        start_time=_get(ident, "zeroDopplerStartTime"),
        end_time=_get(ident, "zeroDopplerEndTime"),
        track=_get(ident, "trackNumber"),
        frame=_get(ident, "frameNumber"),
        product_version=_get(ident, "productVersion"),
        footprint=_parse_wkt_polygon(_get(ident, "boundingPolygon", "")),
    )


def _parse_wkt_polygon(wkt: str) -> list[list[float]]:
    match = re.search(r"\(\((.+?)\)\)", wkt or "")
    if not match:
        return []
    return [[float(p.split()[0]), float(p.split()[1])] for p in match.group(1).split(",")]


@dataclass
class RadarParameters:
    frequency: str
    center_frequency_hz: float | None
    wavelength_cm: float | None
    near_incidence_deg: float | None
    far_incidence_deg: float | None
    mean_incidence_deg: float | None
    range_resolution_m: float | None
    azimuth_resolution_m: float | None
    range_bandwidth_mhz: float | None


def read_radar_parameters(h5: h5py.File, frequency: str) -> RadarParameters:
    sw = h5.get(f"{SWATHS_PATH}/{frequency}")
    fc = _get(sw, "centerFrequency")
    near, far = _get(sw, "nearRangeIncidenceAngle"), _get(sw, "farRangeIncidenceAngle")
    bw = _get(sw, "processedRangeBandwidth")
    r = lambda v, n=2: round(float(v), n) if v is not None else None
    return RadarParameters(
        frequency=frequency,
        center_frequency_hz=fc,
        wavelength_cm=r(SPEED_OF_LIGHT / fc * 100) if fc else None,
        near_incidence_deg=r(near),
        far_incidence_deg=r(far),
        mean_incidence_deg=r((near + far) / 2) if near is not None and far is not None else None,
        range_resolution_m=r(_get(sw, "rangeResolution")),
        azimuth_resolution_m=r(_get(sw, "sceneCenterAlongTrackResolution")),
        range_bandwidth_mhz=r(bw / 1e6) if bw else None,
    )


# ---------------------------------------------------------------- grids
@dataclass
class Grid:
    frequency: str
    epsg: int
    dx: float
    dy: float  # negative (north-up)
    x: np.ndarray  # pixel-centre coordinates
    y: np.ndarray
    terms: list[str]

    @property
    def shape(self) -> tuple[int, int]:
        return len(self.y), len(self.x)

    @property
    def co_pol(self) -> str | None:
        return next((t for t in CO_POL_TERMS if t in self.terms), None)

    @property
    def cross_pol(self) -> str | None:
        return next((t for t in CROSS_POL_TERMS if t in self.terms), None)


def list_grids(h5: h5py.File) -> list[Grid]:
    """All frequency grids that contain at least one covariance term, finest first."""
    root = h5.get(GRIDS_PATH)
    grids = []
    for freq in (root.keys() if root is not None else []):
        g = root[freq]
        terms = [t for t in COVARIANCE_TERMS if t in g]
        if not terms or "xCoordinates" not in g:
            continue
        grids.append(Grid(
            frequency=freq,
            epsg=int(_get(g, "projection")),
            dx=float(_get(g, "xCoordinateSpacing")),
            dy=float(_get(g, "yCoordinateSpacing")),
            x=g["xCoordinates"][:],
            y=g["yCoordinates"][:],
            terms=terms,
        ))
    return sorted(grids, key=lambda gr: abs(gr.dx))


# ---------------------------------------------------------------- windows
@dataclass
class PixelWindow:
    row0: int
    row1: int
    col0: int
    col1: int

    @property
    def shape(self) -> tuple[int, int]:
        return self.row1 - self.row0, self.col1 - self.col0

    @property
    def pixels(self) -> int:
        return self.shape[0] * self.shape[1]


def full_window(grid: Grid) -> PixelWindow:
    return PixelWindow(0, grid.shape[0], 0, grid.shape[1])


def window_for_bbox(grid: Grid, bbox: tuple[float, float, float, float]) -> PixelWindow | None:
    """Pixel window of `grid` covering a lon/lat bbox, or None if they don't intersect."""
    to_grid = Transformer.from_crs("EPSG:4326", f"EPSG:{grid.epsg}", always_xy=True)
    lon0, lat0, lon1, lat1 = bbox
    lons = np.linspace(lon0, lon1, 21)
    lats = np.linspace(lat0, lat1, 21)
    edge_lon = np.concatenate([lons, lons, np.full(21, lon0), np.full(21, lon1)])
    edge_lat = np.concatenate([np.full(21, lat0), np.full(21, lat1), lats, lats])
    xs, ys = to_grid.transform(edge_lon, edge_lat)
    xmin, xmax, ymin, ymax = np.min(xs), np.max(xs), np.min(ys), np.max(ys)

    cols = np.nonzero((grid.x >= xmin) & (grid.x <= xmax))[0]
    rows = np.nonzero((grid.y >= ymin) & (grid.y <= ymax))[0]
    if cols.size == 0 or rows.size == 0:
        return None
    return PixelWindow(int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1)
