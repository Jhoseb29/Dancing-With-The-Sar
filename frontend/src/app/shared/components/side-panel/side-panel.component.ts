import { ChangeDetectionStrategy, Component, ElementRef, effect, input, output, viewChild } from '@angular/core';

/**
 * Panel lateral sobre el mapa que se puede ocultar (dumb). Abierto: el contenido
 * proyectado con un botón "Ocultar" (o Esc). Cerrado: solo un botón con el título para
 * volver a abrirlo, y el mapa queda libre. El estado vive fuera (shadow /panels/layerPanel).
 */
@Component({
  selector: 'app-side-panel',
  templateUrl: './side-panel.component.html',
  styleUrl: './side-panel.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SidePanelComponent {
  readonly open = input.required<boolean>();
  /** Título del botón cuando el panel está oculto y nombre accesible del panel. */
  readonly label = input.required<string>();
  readonly hideLabel = input.required<string>();
  readonly openChange = output<boolean>();

  private readonly hideButton = viewChild<ElementRef<HTMLButtonElement>>('hide');
  private readonly reopenButton = viewChild<ElementRef<HTMLButtonElement>>('reopen');
  /** Solo se mueve el foco cuando el usuario usó estos botones (no si el agente cambia el estado). */
  private focusPending = false;

  constructor() {
    effect(() => {
      const target = this.open() ? this.hideButton() : this.reopenButton();
      if (this.focusPending && target) {
        this.focusPending = false;
        target.nativeElement.focus();
      }
    });
  }

  protected setOpen(open: boolean): void {
    this.focusPending = true;
    this.openChange.emit(open);
  }

  protected onKeydown(event: KeyboardEvent): void {
    if (event.key === 'Escape') {
      this.setOpen(false);
    }
  }
}
