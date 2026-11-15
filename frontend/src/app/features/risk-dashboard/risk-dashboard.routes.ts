import { Routes } from '@angular/router';

export default [
  {
    path: '',
    loadComponent: () => import('./pages/risk-page/risk-page.component').then((m) => m.RiskPageComponent),
  },
] satisfies Routes;
