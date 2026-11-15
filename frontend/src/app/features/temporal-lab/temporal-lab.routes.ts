import { Routes } from '@angular/router';

// Vista pendiente hasta que el backend publique datos reales (sin mocks).
export default [
  {
    path: '',
    loadComponent: () =>
      import('../../shared/components/pending-feature/pending-feature.component').then((m) => m.PendingFeatureComponent),
    data: {
      titleKey: 'nav.temporal',
      descriptionKey: 'pending.temporal',
      needs: ['GET /api/catalog/timeline', 'GET /api/catalog/files/{cog}', 'GET /api/series (GCOV + GPM IMERG)'],
    },
  },
] satisfies Routes;
