import { Routes } from '@angular/router';

// Vista pendiente hasta que el backend publique datos reales (sin mocks).
export default [
  {
    path: '',
    loadComponent: () =>
      import('../../shared/components/pending-feature/pending-feature.component').then((m) => m.PendingFeatureComponent),
    data: {
      titleKey: 'nav.provenance',
      descriptionKey: 'pending.provenance',
      needs: ['Manifiestos (data/manifests)', 'Score y juicio del Harness 1'],
    },
  },
] satisfies Routes;
