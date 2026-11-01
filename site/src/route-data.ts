import { defineRouteMiddleware } from '@astrojs/starlight/route-data';

export const onRequest = defineRouteMiddleware((context) => {
  const { id, entry } = context.locals.starlightRoute;
  // Rendered hero actions come from the content collection, not Markdown metadata.
  for (const action of entry.data.hero?.actions || []) {
    if (
      action.link.startsWith('/') &&
      !action.link.startsWith('//') &&
      !action.link.startsWith(import.meta.env.BASE_URL)
    ) {
      action.link = import.meta.env.BASE_URL.slice(0, -1) + action.link;
    }
  }

  if (id === 'reference/api' || id.startsWith('reference/api/')) {
    context.locals.starlightRoute.entry.data.banner = {
      content:
        '<strong>Development API reference.</strong> This reference is generated from the source ' +
        'checkout used to build this site and may differ from your deployment. For a deployed ' +
        'instance, use its <code>/openapi.json</code> or <code>/docs</code> as the source of truth.',
    };
  }

  // Keep task guides discoverable; the API overview remains a searchable entry point.
  if (id.startsWith('reference/api/operations/')) {
    context.locals.starlightRoute.entry.data.pagefind = false;
  }
});
