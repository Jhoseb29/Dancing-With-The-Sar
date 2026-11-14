import { Routes } from '@angular/router';

export default [
  {
    path: '',
    loadComponent: () =>
      import('./pages/event-explorer-page/event-explorer-page.component').then((m) => m.EventExplorerPageComponent),
  },
] satisfies Routes;
