import { AfterViewInit, ChangeDetectionStrategy, Component, ElementRef, output, viewChild } from '@angular/core';

/** Contenedor del canvas del motor 3D. Dumb: solo entrega el elemento host. */
@Component({
  selector: 'app-globe-canvas',
  templateUrl: './globe-canvas.component.html',
  styleUrl: './globe-canvas.component.scss',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class GlobeCanvasComponent implements AfterViewInit {
  readonly ready = output<HTMLElement>();
  private readonly host = viewChild.required<ElementRef<HTMLElement>>('host');

  ngAfterViewInit(): void {
    this.ready.emit(this.host().nativeElement);
  }
}
