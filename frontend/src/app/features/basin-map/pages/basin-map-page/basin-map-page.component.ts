import { ChangeDetectionStrategy, Component, DestroyRef, computed, inject } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { RuntimeConfigService } from '../../../../core/config/runtime-config.service';
import { UiConfigService } from '../../../../core/config/ui-config.service';
import { gamcLegendUrl } from '../../../../core/data-access/gamc-wms.client';
import { SceneStore } from '../../../../core/scene/scene.store';
import { GeoEngineService } from '../../../../core/services/geo-engine.service';
import { MapCanvasComponent } from '../../../../shared/components/map-canvas/map-canvas.component';
import { CoordinatePipe } from '../../../../shared/pipes/coordinate.pipe';

/** Vista de la cuenca (motor 2.5D) con capas municipales reales del GAMC. Smart. */
@Component({
  selector: 'app-basin-map-page',
  imports: [MapCanvasComponent, TranslocoPipe, RouterLink, CoordinatePipe],
  templateUrl: './basin-map-page.component.html',
  styleUrl: './basin-map-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BasinMapPageComponent {
  protected readonly map = inject(GeoEngineService);
  protected readonly scene = inject(SceneStore);
  private readonly ui = inject(UiConfigService);
  private readonly apiBaseUrl = inject(RuntimeConfigService).value.apiBaseUrl;

  protected readonly quickPlaces = ['cochabamba-city', 'cochabamba-basin', 'north-zone-2750'];

  /** Catálogo GAMC (layers.json) combinado con lo que pide el shadow y lo que reporta el motor. */
  protected readonly gamcLayers = computed(() => {
    const state = this.scene.layers();
    const reported = this.scene.reported().layers;
    return this.ui.gamcLayers().map((preset) => {
      const entry = state.find((l) => l.presetId === preset.id);
      return {
        preset,
        visible: entry?.visible ?? false,
        status: entry?.visible ? (reported[preset.id] ?? 'loading') : null,
        legendUrl: gamcLegendUrl(this.apiBaseUrl, preset.serviceId),
      };
    });
  });

  constructor() {
    inject(DestroyRef).onDestroy(() => this.map.detach());
  }

  protected onCanvasReady(container: HTMLElement): void {
    void this.map.attach(container);
  }

  protected placeName(placeId: string): string {
    return this.ui.place(placeId)?.name[this.scene.lang()] ?? placeId;
  }

  protected goToPlace(placeId: string): void {
    void this.scene.patch({
      origin: 'user',
      ops: [
        { op: 'replace', path: '/camera/placeId', value: placeId },
        { op: 'replace', path: '/search/selectedPlaceId', value: placeId },
      ],
    });
  }

  protected toggle(presetId: string, visible: boolean): void {
    void this.scene.toggleLayer(presetId, visible);
  }

  protected layerName(presetId: string): string {
    return this.ui.layer(presetId)?.name[this.scene.lang()] ?? presetId;
  }

  protected entries(properties: Record<string, unknown>): { key: string; value: string }[] {
    return Object.entries(properties)
      .filter(([, value]) => value !== null && value !== undefined && value !== '')
      .slice(0, 8)
      .map(([key, value]) => ({ key, value: String(value) }));
  }
}
