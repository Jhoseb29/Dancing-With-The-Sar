import { Injectable } from '@angular/core';
import { RuntimeConfig } from './runtime-config.model';

@Injectable({ providedIn: 'root' })
export class RuntimeConfigService {
  private config: RuntimeConfig | null = null;

  /** Se llama una sola vez en el arranque (provideAppInitializer). */
  async load(): Promise<void> {
    const response = await fetch('assets/runtime-config.json', { cache: 'no-cache' });
    if (!response.ok) {
      throw new Error(`No se pudo cargar runtime-config.json (${response.status})`);
    }
    this.config = (await response.json()) as RuntimeConfig;
  }

  get value(): RuntimeConfig {
    if (!this.config) {
      throw new Error('RuntimeConfig no cargado todavía');
    }
    return this.config;
  }
}
