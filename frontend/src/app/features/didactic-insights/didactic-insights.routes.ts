import { Routes } from '@angular/router';

export default [
  {
    path: '',
    loadComponent: () =>
      import('./pages/insights-page/insights-page.component').then((m) => m.InsightsPageComponent),
  },
] satisfies Routes;
