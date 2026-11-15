import { Routes } from '@angular/router';

// Vista pendiente hasta que el backend publique datos reales (sin mocks).
export default [
  {
    path: '',
    loadComponent: () =>
      import('../../shared/components/pending-feature/pending-feature.component').then((m) => m.PendingFeatureComponent),
    data: {
      titleKey: 'nav.insights',
      descriptionKey: 'pending.insights',
      needs: ['Dataset del Harness 2 (es/en)', 'llm-advisor'],
    },
  },
] satisfies Routes;
