import { Routes } from '@angular/router';

export default [
  {
    path: '',
    loadComponent: () =>
      import('./pages/orbit-view-page/orbit-view-page.component').then((m) => m.OrbitViewPageComponent),
  },
] satisfies Routes;
