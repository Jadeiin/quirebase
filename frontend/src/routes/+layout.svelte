<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { Tooltip } from 'bits-ui';

	import '../app.css';

	let { children } = $props();
	const queryClient = new QueryClient({
		defaultOptions: { queries: { staleTime: 30_000, retry: 1 } }
	});
</script>

<svelte:head><meta name="theme-color" content="#111827" /></svelte:head>

<QueryClientProvider client={queryClient}>
	<Tooltip.Provider delayDuration={450} skipDelayDuration={150}>
		{@render children()}
	</Tooltip.Provider>
</QueryClientProvider>
