import { defineRouteMiddleware } from '@astrojs/starlight/route-data';

export const onRequest = defineRouteMiddleware((context) => {
  if (context.url.pathname.startsWith('/reference/api/')) {
    context.locals.starlightRoute.entry.data.banner = {
      content:
        '<strong>Development API reference.</strong> This reference is generated from the source ' +
        'checkout used to build this site and may differ from your deployment. For a deployed ' +
        'instance, use its <code>/openapi.json</code> or <code>/docs</code> as the source of truth.',
    };
  }

  // Keep task guides discoverable; the API overview remains a searchable entry point.
  if (context.url.pathname.startsWith('/reference/api/operations/')) {
    context.locals.starlightRoute.entry.data.pagefind = false;
  }
});
