import { Injectable } from '@angular/core';
import {
  CameraTourConfig,
  EventConfig,
  GamcWmsLayer,
  LayerConfig,
  PlaceConfig,
  RouteConfig,
  UiConfig,
} from './ui-config.model';

/** Carga la configuración de UI en JSON (assets/config) una vez al arrancar. */
@Injectable({ providedIn: 'root' })
export class UiConfigService {
  private config: UiConfig | null = null;

  async load(): Promise<void> {
    const [routes, places, layers, tours, events] = await Promise.all([
      getJson<{ routes: RouteConfig[] }>('assets/config/routes.json'),
      getJson<{ places: PlaceConfig[] }>('assets/config/places.json'),
      getJson<{ layers: LayerConfig[] }>('assets/config/layers.json'),
      getJson<{ tours: CameraTourConfig[] }>('assets/config/camera-tours.json'),
      getJson<{ events: EventConfig[] }>('assets/config/events.json'),
    ]);
    this.config = { routes: routes.routes, places: places.places, layers: layers.layers, tours: tours.tours, events: events.events };
  }

  get value(): UiConfig {
    if (!this.config) {
      throw new Error('UiConfig no cargada todavía');
    }
    return this.config;
  }

  route(id: string): RouteConfig | undefined {
    return this.value.routes.find((r) => r.id === id);
  }

  routeByPath(path: string): RouteConfig | undefined {
    return this.value.routes.find((r) => r.path === path);
  }

  place(id: string): PlaceConfig | undefined {
    return this.value.places.find((p) => p.id === id);
  }

  layer(id: string): LayerConfig | undefined {
    return this.value.layers.find((l) => l.id === id);
  }

  gamcLayers(): GamcWmsLayer[] {
    return this.value.layers.filter((l): l is GamcWmsLayer => l.kind === 'gamc-wms');
  }

  basemap(): LayerConfig & { kind: 'gibs-xyz' } {
    const layer = this.value.layers.find((l) => l.kind === 'gibs-xyz' && l.group === 'basemap');
    if (!layer || layer.kind !== 'gibs-xyz') {
      throw new Error('layers.json no define un mapa base gibs-xyz');
    }
    return layer;
  }

  event(id: string): EventConfig | undefined {
    return this.value.events.find((e) => e.id === id);
  }

  tour(id: string): CameraTourConfig | undefined {
    return this.value.tours.find((t) => t.id === id);
  }
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-cache' });
  if (!response.ok) {
    throw new Error(`No se pudo cargar ${path} (${response.status})`);
  }
  return (await response.json()) as T;
}
