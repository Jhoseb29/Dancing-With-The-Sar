import { AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, output, viewChild } from '@angular/core';

/** Contenedor del canvas del motor 2.5D. Dumb: solo entrega el elemento host. */
@Component({
  selector: 'app-map-canvas',
  templateUrl: './map-canvas.component.html',
  styleUrl: './map-canvas.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class MapCanvasComponent implements AfterViewInit {
  readonly ready = output<HTMLElement>();
  private readonly host = viewChild.required<ElementRef<HTMLElement>>('host');

  ngAfterViewInit(): void {
    this.ready.emit(this.host().nativeElement);
  }
}
