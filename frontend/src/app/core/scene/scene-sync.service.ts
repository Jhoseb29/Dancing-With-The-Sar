import { Injectable, effect, inject, isDevMode, untracked } from '@angular/core';
import { NavigationEnd, NavigationStart, Router } from '@angular/router';
import { TranslocoService } from '@jsverse/transloco';
import { filter } from 'rxjs';
import { UiConfigService } from '../config/ui-config.service';
import { LayerState, RouteId, isAppLang } from './scene.model';
import { SceneStore } from './scene.store';

const URL_DEBOUNCE_MS = 300;

/**
 * Sincroniza el shadow con el router, la URL (lang, place, layers) y Transloco.
 * - Router → shadow: cada navegación actualiza /route (origen `url`).
 * - Shadow → router: si /route cambia (usuario o URL), se navega.
 * - URL inicial y atrás/adelante → shadow (origen `url`).
 * - Shadow → URL: query params con debounce y replaceUrl.
 */
@Injectable({ providedIn: 'root' })
export class SceneSyncService {
  private readonly router = inject(Router);
  private readonly store = inject(SceneStore);
  private readonly config = inject(UiConfigService);
  private readonly transloco = inject(TranslocoService);

  private parseQueryOnNextNavigation = true;
  private initialUrlApplied = false;
  private urlTimer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    this.warnOnRouteMismatch();

    this.router.events.pipe(filter((e) => e instanceof NavigationStart)).subscribe((event) => {
      if (event.navigationTrigger === 'popstate') {
        this.parseQueryOnNextNavigation = true;
      }
    });

    this.router.events.pipe(filter((e) => e instanceof NavigationEnd)).subscribe(() => this.onNavigationEnd());

    // Idioma en vivo.
    effect(() => {
      const lang = this.store.lang();
      this.transloco.setActiveLang(lang);
      document.documentElement.lang = lang;
    });

    // Shadow → router: solo cuando un parche (usuario o URL) cambia /route.
    // El valor inicial no navega: la URL de entrada manda.
    effect(() => {
      const patch = this.store.lastPatch();
      if (!patch || patch.origin === 'url' || !patch.ops.some((op) => op.path === '/route')) {
        return;
      }
      untracked(() => {
        const target = this.config.route(this.store.route());
        if (target && this.currentPath() !== target.path) {
          void this.router.navigate(['/', target.path], { queryParamsHandling: 'preserve' });
        }
      });
    });

    // Shadow → URL (subconjunto). No se escribe hasta haber leído la URL de entrada.
    effect(() => {
      const state = this.store.state();
      const query = {
        lang: state.lang === 'es' ? null : state.lang,
        place: state.camera.placeId,
        layers: state.layers.filter((l) => l.visible).map((l) => l.presetId).join(',') || null,
      };
      untracked(() => {
        if (this.initialUrlApplied) {
          this.scheduleUrlUpdate(query);
        }
      });
    });
  }

  private onNavigationEnd(): void {
    const path = this.currentPath();
    const route = this.config.routeByPath(path);
    if (route && route.id !== this.store.route()) {
      void this.store.set('/route', route.id as RouteId, 'url');
    }
    this.store.reportRoute((route?.id as RouteId | undefined) ?? null);

    if (this.parseQueryOnNextNavigation) {
      this.parseQueryOnNextNavigation = false;
      void this.applyQueryParams();
    }
  }

  private async applyQueryParams(): Promise<void> {
    const params = this.router.routerState.snapshot.root.queryParamMap;
    const lang = params.get('lang');
    const place = params.get('place');
    const layers = params.get('layers');

    if (isAppLang(lang) && lang !== this.store.lang()) {
      await this.store.set('/lang', lang, 'url');
    }
    if (place && this.config.place(place) && place !== this.store.camera().placeId) {
      await this.store.patch({
        origin: 'url',
        ops: [
          { op: 'replace', path: '/camera/placeId', value: place },
          { op: 'replace', path: '/search/selectedPlaceId', value: place },
        ],
      });
    }
    if (layers !== null) {
      const next: LayerState[] = layers
        .split(',')
        .map((id) => id.trim())
        .filter((id) => this.config.layer(id))
        .map((id) => {
          const preset = this.config.layer(id);
          return { presetId: id, visible: true, opacity: preset?.kind === 'gamc-wms' ? preset.defaultOpacity : 1 };
        });
      await this.store.replaceLayers(next, 'url');
    }
    if (!this.initialUrlApplied) {
      this.initialUrlApplied = true;
      // Escribir la URL con el estado completo (p. ej. capas por defecto).
      const state = this.store.state();
      this.scheduleUrlUpdate({
        lang: state.lang === 'es' ? null : state.lang,
        place: state.camera.placeId,
        layers: state.layers.filter((l) => l.visible).map((l) => l.presetId).join(',') || null,
      });
    }
  }

  private scheduleUrlUpdate(query: Record<string, string | null>): void {
    if (this.urlTimer) {
      clearTimeout(this.urlTimer);
    }
    this.urlTimer = setTimeout(() => {
      const current = this.router.routerState.snapshot.root.queryParamMap;
      const changed = Object.entries(query).some(([k, v]) => (current.get(k) ?? null) !== v);
      if (changed) {
        void this.router.navigate([], { queryParams: query, queryParamsHandling: 'merge', replaceUrl: true });
      }
    }, URL_DEBOUNCE_MS);
  }

  private currentPath(): string {
    const tree = this.router.parseUrl(this.router.url);
    return tree.root.children['primary']?.segments[0]?.path ?? '';
  }

  private warnOnRouteMismatch(): void {
    if (!isDevMode()) {
      return;
    }
    const registered = new Set(this.router.config.map((r) => r.path).filter((p): p is string => !!p && p !== '**'));
    const declared = new Set(this.config.value.routes.map((r) => r.path));
    for (const path of declared) {
      if (!registered.has(path)) console.warn(`[routes.json] "${path}" no tiene loadChildren registrado`);
    }
    for (const path of registered) {
      if (!declared.has(path)) console.warn(`[routes.json] la ruta registrada "${path}" no está declarada`);
    }
  }
}
