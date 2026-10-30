import { defineRouteMiddleware } from '@astrojs/starlight/route-data';

export const onRequest = defineRouteMiddleware((context) => {
  // Keep task guides discoverable; the API overview remains a searchable entry point.
  if (context.url.pathname.startsWith('/reference/api/operations/')) {
    context.locals.starlightRoute.entry.data.pagefind = false;
  }
});
