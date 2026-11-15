import { SidePanelComponent } from '../../../../shared/components/side-panel/side-panel.component';
import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { RuntimeConfigService } from '../../../../core/config/runtime-config.service';
import { UiConfigService } from '../../../../core/config/ui-config.service';
import { SceneStore } from '../../../../core/scene/scene.store';
import { GlobeEngineService } from '../../../../core/services/globe-engine.service';
import { OrbitService } from '../../../../core/services/orbit.service';
import { GlobeCanvasComponent } from '../../../../shared/components/globe-canvas/globe-canvas.component';
import { CoordinatePipe } from '../../../../shared/pipes/coordinate.pipe';

const SPEEDS = [1, 60, 600] as const;

/** Vista de planeta: NISAR en órbita en tiempo real (posición calculada). Smart. */
@Component({
  selector: 'app-orbit-view-page',
  imports: [GlobeCanvasComponent, SidePanelComponent, TranslocoPipe, CoordinatePipe],
  templateUrl: './orbit-view-page.component.html',
  styleUrl: './orbit-view-page.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class OrbitViewPageComponent {
  protected readonly orbit = inject(OrbitService);
  protected readonly globe = inject(GlobeEngineService);
  protected readonly scene = inject(SceneStore);
  private readonly config = inject(RuntimeConfigService);
  private readonly ui = inject(UiConfigService);

  protected readonly speeds = SPEEDS;
  protected readonly tours = this.ui.value.tours.filter((t) => t.engine === 'globe');
  protected readonly staleDays = this.config.value.orbit.staleTleDays;
  protected readonly swathKm = this.config.value.orbit.illustrativeSwathKm;

  private readonly locale = computed(() => (this.scene.lang() === 'es' ? 'es-BO' : 'en-US'));

  protected readonly upcoming = computed(() =>
    this.orbit.passes().slice(0, 4).map((pass) => ({ ...pass, label: this.formatDate(pass.timeMs) })),
  );

  protected readonly tleEpochLabel = computed(() => {
    const elements = this.orbit.elements();
    return elements ? this.formatDate(Date.parse(elements.epoch)) : '—';
  });

  protected readonly simTimeLabel = computed(() => {
    const readout = this.globe.readout();
    return readout ? this.formatDate(readout.timeMs, true) : '—';
  });

  constructor() {
    this.orbit.ensureLoaded();

    // Cuando el motor y el TLE estén listos, cargar la órbita en el globo.
    effect(() => {
      const elements = this.orbit.elements();
      if (elements && this.globe.ready()) {
        void this.globe.setOrbitElements(elements);
      }
    });

    inject(DestroyRef).onDestroy(() => this.globe.detach());
  }

  protected onCanvasReady(container: HTMLElement): void {
    void this.globe.attach(container, { satellite: 'NISAR', area: 'COCHABAMBA' });
  }

  protected setSpeed(value: number): void {
    void this.scene.set('/time/speed', value);
  }

  protected resetToNow(): void {
    void this.scene.set('/time/speed', 1);
    this.globe.resetToNow();
  }

  protected toggleFollow(): void {
    void this.scene.patch({
      origin: 'user',
      ops: [
        { op: 'replace', path: '/camera/tourId', value: null },
        { op: 'replace', path: '/camera/follow', value: !this.scene.camera().follow },
      ],
    });
  }

  protected startTour(tourId: string): void {
    void this.scene.patch({
      origin: 'user',
      ops: [
        { op: 'replace', path: '/camera/follow', value: false },
        { op: 'replace', path: '/camera/tourId', value: tourId },
      ],
    });
  }

  protected flyHome(): void {
    void this.scene.patch({
      origin: 'user',
      ops: [
        { op: 'replace', path: '/camera/follow', value: false },
        { op: 'replace', path: '/camera/tourId', value: null },
      ],
    });
    this.globe.flyHome();
  }

  protected goToBasin(): void {
    void this.scene.set('/camera/follow', false);
    this.globe.flyToArea(() => {
      void this.scene.patch({
        origin: 'user',
        ops: [
          { op: 'replace', path: '/camera/placeId', value: 'cochabamba-city' },
          { op: 'replace', path: '/route', value: 'basin' },
        ],
      });
    });
  }

  private formatDate(ms: number, withSeconds = false): string {
    return new Intl.DateTimeFormat(this.locale(), {
      dateStyle: 'medium',
      timeStyle: withSeconds ? 'medium' : 'short',
    }).format(new Date(ms));
  }

  /** Ocultar o mostrar el panel (flag /panels/layerPanel del shadow). */
  protected setPanelOpen(open: boolean): void {
    void this.scene.set('/panels/layerPanel', open);
  }
}
