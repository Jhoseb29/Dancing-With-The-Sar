import type { BBox } from './runtime-config.model';

/** Tipos de assets/config/*.json — schema en backend/shared/schemas/ui-config.schema.json. */

export interface I18nText {
  es: string;
  en: string;
}

export type EngineKind = 'globe' | 'map' | 'none';

export interface RouteConfig {
  id: string;
  path: string;
  titleKey: string;
  engine: EngineKind;
  status?: 'ready' | 'pending-backend';
}

export interface PlaceConfig {
  id: string;
  name: I18nText;
  aliases?: string[];
  kind: 'country' | 'department' | 'city' | 'basin' | 'zone';
  bbox: BBox;
  approximate?: boolean;
  source: string;
}

interface LayerBase {
  id: string;
  name: I18nText;
  description?: I18nText;
  engines: ('globe' | 'map')[];
  group?: 'basemap' | 'gamc' | 'event';
  attribution?: string;
  source: string;
}

export interface GibsXyzLayer extends LayerBase {
  kind: 'gibs-xyz';
  url: string;
  maxZoom: number;
}

export interface GamcWmsLayer extends LayerBase {
  kind: 'gamc-wms';
  serviceId: string;
  representation: 'simple' | 'categorized';
  bbox: BBox;
  defaultOpacity: number;
  legend: boolean;
  featureInfo: boolean;
  /** Lista blanca de atributos visibles. Sin ella se ocultan igual los datos personales. */
  featureInfoFields?: string[];
}

export interface GibsWmtsLayer extends LayerBase {
  kind: 'gibs-wmts';
  gibsLayer: string;
  /** Plantilla con {Time}, {z}, {y}, {x}. */
  url: string;
  tileMatrixSet: string;
  format: 'png' | 'jpg';
  maxZoom: number;
  temporal: 'daily' | 'composite';
  legendUrl?: string;
  coverageFrom?: string;
  coverageTo?: string;
}

export type LayerConfig = GibsXyzLayer | GibsWmtsLayer | GamcWmsLayer;

export interface EventConfig {
  id: string;
  name: I18nText;
  keywords: { es: string[]; en: string[] };
  available: boolean;
  layers: string[];
  points?: 'firms';
  stats?: 'firms';
  howToRead: I18nText;
  defaultPlaceId: string;
  verifiedDates?: { placeId: string; date: string; note?: string }[];
  unavailableReason?: I18nText;
}

export interface TourStep {
  placeId?: string;
  lon?: number;
  lat?: number;
  altKm?: number;
  durationMs: number;
  pauseMs?: number;
}

export interface CameraTourConfig {
  id: string;
  name: I18nText;
  engine: 'globe' | 'map';
  steps: TourStep[];
}

export interface UiConfig {
  routes: RouteConfig[];
  places: PlaceConfig[];
  layers: LayerConfig[];
  tours: CameraTourConfig[];
  events: EventConfig[];
}
