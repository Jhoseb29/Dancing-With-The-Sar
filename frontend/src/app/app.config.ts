import {
  ApplicationConfig,
  Injector,
  inject,
  isDevMode,
  provideAppInitializer,
  provideBrowserGlobalErrorListeners,
} from '@angular/core';
import { provideHttpClient, withFetch } from '@angular/common/http';
import { provideRouter, withComponentInputBinding } from '@angular/router';
import { provideTransloco } from '@jsverse/transloco';
import { routes } from './app.routes';
import { RuntimeConfigService } from './core/config/runtime-config.service';
import { UiConfigService } from './core/config/ui-config.service';
import { installSceneDevHook } from './core/scene/scene-dev-hook';
import { AVAILABLE_LANGS } from './core/scene/scene.model';
import { SceneStore } from './core/scene/scene.store';
import { SceneSyncService } from './core/scene/scene-sync.service';
import { TranslocoHttpLoader } from './core/services/transloco-http.loader';

// Angular 22 es zoneless por defecto: no hay zone.js en polyfills.
export const appConfig: ApplicationConfig = {
  providers: [
    provideBrowserGlobalErrorListeners(),
    provideHttpClient(withFetch()),
    provideRouter(routes, withComponentInputBinding()),
    provideAppInitializer(async () => {
      const injector = inject(Injector);
      await Promise.all([injector.get(RuntimeConfigService).load(), injector.get(UiConfigService).load()]);
      // Con la configuración cargada, el shadow se sincroniza con router, URL e idioma.
      injector.get(SceneSyncService);
      installSceneDevHook(injector.get(SceneStore));
    }),
    provideTransloco({
      config: {
        availableLangs: [...AVAILABLE_LANGS],
        defaultLang: 'es',
        fallbackLang: 'es',
        reRenderOnLangChange: true,
        prodMode: !isDevMode(),
      },
      loader: TranslocoHttpLoader,
    }),
  ],
};
