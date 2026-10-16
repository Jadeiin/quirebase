<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { LocaleProvider } from '@skeletonlabs/skeleton-svelte';
	import { activeLocale } from '#lib/i18n.js';

	import '../app.css';

	let { children } = $props();
	const queryClient = new QueryClient({
		defaultOptions: { queries: { staleTime: 30_000, retry: 1 } }
	});
</script>

<QueryClientProvider client={queryClient}>
	<LocaleProvider locale={$activeLocale}>
		{@render children()}
	</LocaleProvider>
</QueryClientProvider>
