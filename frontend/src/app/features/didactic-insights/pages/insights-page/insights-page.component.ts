import {
  ChangeDetectionStrategy,
  Component,
  DestroyRef,
  computed,
  effect,
  inject,
  signal,
} from '@angular/core';
import { ActivatedRoute, Router } from '@angular/router';
import { TranslocoPipe, TranslocoService } from '@jsverse/transloco';
import { CLASS_LEGEND, DB_RANGE, rampCss } from '../../../../core/harness/globe-grid';
import { GlobeLayerId } from '../../../../core/harness/harness.model';
import { SceneStore } from '../../../../core/scene/scene.store';
import { GeoEngineService } from '../../../../core/services/geo-engine.service';
import { HarnessGlobeService } from '../../../../core/services/harness-globe.service';
import { HarnessService } from '../../../../core/services/harness.service';
import { MapCanvasComponent } from '../../../../shared/components/map-canvas/map-canvas.component';
import { SidePanelComponent } from '../../../../shared/components/side-panel/side-panel.component';
import { MarkdownPipe } from '../../../../shared/pipes/markdown.pipe';

const CLASS_KEYS = [
  'water_flood_pct',
  'bare_soil_pct',
  'vegetation_canopy_pct',
  'urban_double_bounce_pct',
];
const EXAMPLES = [
  'harness.examples.fires',
  'harness.examples.basin',
  'harness.examples.flood',
] as const;

/** Análisis NISAR en el globo: tomas, capas coloreadas desde datos y puntos de cambio. Smart. */
@Component({
  selector: 'app-insights-page',
  imports: [MapCanvasComponent, SidePanelComponent, TranslocoPipe, MarkdownPipe],
  templateUrl: './insights-page.component.html',
  styleUrl: './insights-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class InsightsPageComponent {
  protected readonly map = inject(GeoEngineService);
  protected readonly scene = inject(SceneStore);
  protected readonly analysis = inject(HarnessGlobeService);
  protected readonly harness = inject(HarnessService);
  private readonly i18n = inject(TranslocoService);

  protected readonly classLegend = CLASS_LEGEND;
  protected readonly classKeys = CLASS_KEYS;
  protected readonly examples = EXAMPLES;
  protected readonly ramp = rampCss();
  protected readonly lessonOpen = signal(false);

  protected readonly running = computed(
    () => this.harness.turns().find((t) => t.state === 'running') ?? null,
  );
  protected readonly chat = computed(() => this.analysis.active()?.payload.chat ?? null);
  protected readonly hotspotKinds = computed(() =>
    Object.entries(this.analysis.active()?.globe.hotspots_summary?.kinds ?? {}),
  );
  protected readonly downloads = computed(() => {
    const date = this.analysis.take()?.date;
    return (this.analysis.active()?.payload.media ?? []).filter(
      (m) => m.kind !== 'image' && m.date === date,
    );
  });
  protected readonly dbRange = computed(() => {
    const layer = this.analysis.layer();
    return layer === 'co' || layer === 'cross' ? DB_RANGE[layer] : null;
  });

  constructor() {
    inject(DestroyRef).onDestroy(() => this.map.detach());

    // Enlace compartible: ?run=<id> abre esa corrida; la corrida activa se refleja en la URL.
    const router = inject(Router);
    const runParam = inject(ActivatedRoute).snapshot.queryParamMap.get('run');
    if (runParam) {
      void this.analysis.loadRun(runParam);
    }
    effect(() => {
      const runId = this.analysis.active()?.runId;
      if (runId) {
        void router.navigate([], {
          queryParams: { run: runId },
          queryParamsHandling: 'merge',
          replaceUrl: true,
        });
      }
    });
  }

  protected onCanvasReady(container: HTMLElement): void {
    void this.map.attach(container);
  }

  protected setPanelOpen(open: boolean): void {
    void this.scene.set('/panels/layerPanel', open);
  }

  protected setLayer(layer: GlobeLayerId): void {
    this.analysis.layer.set(layer);
  }

  protected setOpacity(value: string): void {
    this.analysis.opacity.set(Number(value) / 100);
  }

  protected ask(key: string): void {
    void this.harness.ask(this.i18n.translate(key));
  }

  protected focus(): void {
    this.analysis.focusRequest.update((n) => n + 1);
  }

  protected classKey(id: number | null): string {
    return CLASS_LEGEND.find((c) => c.id === id)?.key ?? 'nodata';
  }

  protected rgb([r, g, b]: [number, number, number]): string {
    return `rgb(${r} ${g} ${b})`;
  }
}
