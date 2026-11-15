import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { RouterLink } from '@angular/router';
import { TranslocoPipe } from '@jsverse/transloco';

/**
 * Vista de una feature cuyo backend aún no publica datos. No muestra datos
 * inventados (regla cero mocks). Recibe sus textos por datos de la ruta.
 */
@Component({
  selector: 'app-pending-feature',
  imports: [RouterLink, TranslocoPipe],
  templateUrl: './pending-feature.component.html',
  styleUrl: './pending-feature.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PendingFeatureComponent {
  /** Clave i18n del título (nav.*). */
  readonly titleKey = input.required<string>();
  /** Clave i18n de la descripción (pending.*). */
  readonly descriptionKey = input.required<string>();
  /** Endpoints o productos del backend que la vista necesita. */
  readonly needs = input<string[]>([]);
}
