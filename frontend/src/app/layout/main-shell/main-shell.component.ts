import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';
import { UiConfigService } from '../../core/config/ui-config.service';
import { AVAILABLE_LANGS, AppLang, RouteId } from '../../core/scene/scene.model';
import { SceneStore } from '../../core/scene/scene.store';
import { OrbitService } from '../../core/services/orbit.service';
import { PassCountdownComponent } from '../../shared/components/pass-countdown/pass-countdown.component';
import { PlaceSearchComponent } from '../../shared/components/place-search/place-search.component';
import { HarnessDockComponent } from '../harness-dock/harness-dock.component';

@Component({
  selector: 'app-main-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, TranslocoPipe, PassCountdownComponent, PlaceSearchComponent, HarnessDockComponent],
  templateUrl: './main-shell.component.html',
  styleUrl: './main-shell.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MainShellComponent {
  protected readonly scene = inject(SceneStore);
  protected readonly orbit = inject(OrbitService);
  private readonly ui = inject(UiConfigService);

  protected readonly langs = AVAILABLE_LANGS;
  protected readonly menuOpen = signal(false);
  protected readonly nav = this.ui.value.routes.filter((r) => r.inNav !== false);
  protected readonly places = this.ui.value.places;

  constructor() {
    this.orbit.ensureLoaded();
  }

  protected setLang(lang: AppLang): void {
    void this.scene.set('/lang', lang);
  }

  protected toggleMenu(): void {
    this.menuOpen.update((open) => !open);
  }

  protected onQuery(query: string): void {
    void this.scene.set('/search/query', query);
  }

  /** Elegir un lugar: la cámara de la vista activa vuela hasta él (o se abre la cuenca). */
  protected onPlaceSelected(placeId: string): void {
    const current = this.ui.route(this.scene.route());
    const ops = [
      { op: 'replace' as const, path: '/search/selectedPlaceId', value: placeId },
      { op: 'replace' as const, path: '/camera/tourId', value: null },
      { op: 'replace' as const, path: '/camera/placeId', value: placeId },
    ];
    if (!current || current.engine === 'none') {
      ops.unshift({ op: 'replace', path: '/route', value: 'basin' satisfies RouteId });
    }
    void this.scene.patch({ origin: 'user', ops });
    this.menuOpen.set(false);
  }
}
