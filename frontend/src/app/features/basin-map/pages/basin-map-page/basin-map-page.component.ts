import { SidePanelComponent } from '../../../../shared/components/side-panel/side-panel.component';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { RuntimeConfigService } from '../../../../core/config/runtime-config.service';
import { UiConfigService } from '../../../../core/config/ui-config.service';
import { BasinOverview, fetchBasinOverview } from '../../../../core/data-access/basin-risk.client';
import { SceneStore } from '../../../../core/scene/scene.store';
import { GeoEngineService } from '../../../../core/services/geo-engine.service';
import { MapCanvasComponent } from '../../../../shared/components/map-canvas/map-canvas.component';
import { CoordinatePipe } from '../../../../shared/pipes/coordinate.pipe';

export type AnalysisMode = 'integrated' | 'change' | 'water' | 'nisar' | 'rain';

const BASIN_LAYERS = [
  'basin-integrated-alert',
  'basin-sar-change',
  'gibs-opera-dswx-s1',
  'basin-dem-cota-drainage',
  'gibs-nisar-gcov',
  'gibs-imerg-precip',
  'copernicus-dem-slope',
  'basin-susceptibility',
] as const;

const MODE_LAYERS: Record<AnalysisMode, readonly string[]> = {
  integrated: ['basin-integrated-alert'],
  change: ['basin-sar-change'],
  water: ['basin-dem-cota-drainage', 'gibs-opera-dswx-s1'],
  nisar: ['gibs-nisar-gcov'],
  rain: ['gibs-imerg-precip'],
};

/** Vista de cuenca Qucha-SAR (Copernicus DEM 30 m, subcuencas reales y comparación radar). Smart. */
@Component({
  selector: 'app-basin-map-page',
  imports: [MapCanvasComponent, SidePanelComponent, TranslocoPipe, RouterLink, CoordinatePipe],
  templateUrl: './basin-map-page.component.html',
  styleUrl: './basin-map-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class BasinMapPageComponent {
  protected readonly map = inject(GeoEngineService);
  protected readonly scene = inject(SceneStore);
  private readonly ui = inject(UiConfigService);
  private readonly apiBaseUrl = inject(RuntimeConfigService).value.apiBaseUrl;

  protected readonly quickPlaces = ['cochabamba-basin', 'cochabamba-city'];
  protected readonly modes: readonly AnalysisMode[] = ['integrated', 'change', 'water', 'nisar', 'rain'];
  protected readonly activeMode = signal<AnalysisMode>('integrated');
  protected readonly overview = signal<BasinOverview | null>(null);
  protected readonly operaDates = signal<string[]>(['2026-11-13', '2026-11-08']);
  protected readonly imergDateLabel = signal<string>('2026-11-13');

  protected readonly nisarDates = computed(() => {
    const radar = this.ui.event('radar');
    const dates = new Set(
      (radar?.verifiedDates ?? [])
        .filter((v) => v.placeId === 'cochabamba-basin' || v.placeId === 'cochabamba-city')
        .map((v) => v.date),
    );
    return [...dates].sort().reverse();
  });

  protected readonly sarCompareDates = computed(() => {
    const set = new Set([...this.nisarDates(), ...this.operaDates()]);
    return [...set].sort().reverse();
  });

  protected readonly satelliteLayers = computed(() => {
    const state = this.scene.layers();
    const reported = this.scene.reported().layers;
    return BASIN_LAYERS.flatMap((id) => {
      const preset = this.ui.layer(id);
      if (!preset) return [];
      const entry = state.find((l) => l.presetId === id);
      return [
        {
          preset,
          visible: entry?.visible ?? false,
          status: entry?.visible ? (reported[id] ?? 'loading') : null,
        },
      ];
    });
  });

  constructor() {
    inject(DestroyRef).onDestroy(() => this.map.detach());

    effect(() => {
      const ov = this.overview();
      if (ov) {
        this.map.setZoneOverlays(
          ov.zones.map((z) => ({
            id: z.id,
            bbox: z.bbox,
            geometry: z.geometry,
            level: z.level,
            selected: z.id === ov.overall.priority_zone_id,
          })),
        );
      }
    });

    void this.selectMode('integrated');
    void this.syncVerifiedDates();
  }

  private async syncVerifiedDates(): Promise<void> {
    try {
      const overview = await fetchBasinOverview(this.apiBaseUrl, 30);
      this.overview.set(overview);
      const opera = overview.nisar.opera_dswx_dates ?? [];
      if (opera.length > 0) {
        this.operaDates.set(opera);
        this.map.setOperaDate(opera[0]);
      }
      const sc = overview.nisar.sar_change_default;
      if (sc?.before_day && sc?.after_day) {
        this.map.setSarDates(sc.before_day, sc.after_day);
      } else if (this.nisarDates().length >= 2) {
        const nd = this.nisarDates();
        this.map.setSarDates(nd[1], nd[0]);
      }
      const imergLatest = overview.precipitation.gpm_cmr.collections['GPM_3IMERGDL']?.latest_start;
      if (imergLatest) {
        this.imergDateLabel.set(imergLatest);
        this.map.setImergDate(imergLatest);
      }
    } catch {
      // Mantiene fechas por defecto si compute-py no responde aún.
    }
  }

  protected async selectMode(mode: AnalysisMode): Promise<void> {
    this.activeMode.set(mode);
    const keep = new Set(MODE_LAYERS[mode]);
    for (const id of BASIN_LAYERS) {
      const want = keep.has(id);
      const currentlyOn = this.scene.layers().some((l) => l.presetId === id && l.visible);
      if (currentlyOn !== want) {
        await this.scene.toggleLayer(id, want);
      }
    }
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

  protected onNisarDateChange(date: string): void {
    this.map.setNisarDate(date);
    if (!this.scene.layers().some((l) => l.presetId === 'gibs-nisar-gcov' && l.visible)) {
      void this.scene.toggleLayer('gibs-nisar-gcov', true);
    }
  }

  protected onOperaDateChange(date: string): void {
    this.map.setOperaDate(date);
    if (!this.scene.layers().some((l) => l.presetId === 'gibs-opera-dswx-s1' && l.visible)) {
      void this.scene.toggleLayer('gibs-opera-dswx-s1', true);
    }
  }

  protected onSarBeforeChange(date: string): void {
    this.map.setSarDates(date, this.map.sarAfterDate());
  }

  protected onSarAfterChange(date: string): void {
    this.map.setSarDates(this.map.sarBeforeDate(), date);
  }

  protected toggleTerrain3d(enabled: boolean): void {
    this.map.setTerrain3d(enabled);
  }

  protected setPanelOpen(open: boolean): void {
    void this.scene.set('/panels/layerPanel', open);
  }

  protected subbasinLabel(subbasinId: string): string {
    const ov = this.overview();
    const found = ov?.zones.find((z) => z.id === subbasinId);
    return found ? found.name[this.scene.lang()] : subbasinId;
  }
}
