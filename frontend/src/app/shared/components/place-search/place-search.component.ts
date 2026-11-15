import { ChangeDetectionStrategy, Component, computed, input, output, signal } from '@angular/core';
import { TranslocoPipe } from '@jsverse/transloco';
import { PlaceConfig } from '../../../core/config/ui-config.model';
import { AppLang } from '../../../core/scene/scene.model';

/** Buscador de lugares sobre places.json. Dumb: recibe lugares y emite la elección. */
@Component({
  selector: 'app-place-search',
  imports: [TranslocoPipe],
  templateUrl: './place-search.component.html',
  styleUrl: './place-search.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PlaceSearchComponent {
  readonly places = input.required<PlaceConfig[]>();
  readonly lang = input<AppLang>('es');
  readonly query = input<string>('');

  readonly queryChange = output<string>();
  readonly selected = output<string>();

  protected readonly open = signal(false);
  protected readonly activeIndex = signal(0);

  protected readonly results = computed(() => {
    const q = normalize(this.query());
    if (!q) {
      return [];
    }
    return this.places()
      .filter((place) =>
        [place.name.es, place.name.en, ...(place.aliases ?? [])].some((text) => normalize(text).includes(q)),
      )
      .slice(0, 6);
  });

  protected onInput(value: string): void {
    this.open.set(true);
    this.activeIndex.set(0);
    this.queryChange.emit(value);
  }

  protected onKeydown(event: KeyboardEvent): void {
    const results = this.results();
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      this.activeIndex.update((i) => Math.min(i + 1, results.length - 1));
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      this.activeIndex.update((i) => Math.max(i - 1, 0));
    } else if (event.key === 'Enter' && results[this.activeIndex()]) {
      event.preventDefault();
      this.choose(results[this.activeIndex()]);
    } else if (event.key === 'Escape') {
      this.open.set(false);
    }
  }

  protected choose(place: PlaceConfig): void {
    this.open.set(false);
    this.queryChange.emit(place.name[this.lang()]);
    this.selected.emit(place.id);
  }

  protected close(): void {
    // Deja terminar el clic sobre un resultado antes de cerrar.
    setTimeout(() => this.open.set(false), 150);
  }
}

function normalize(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .trim();
}
