import { Routes } from '@angular/router';

export default [
  {
    path: '',
    loadComponent: () =>
      import('./pages/basin-map-page/basin-map-page.component').then((m) => m.BasinMapPageComponent),
  },
] satisfies Routes;
