<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';

	import '../app.css';

	let { children } = $props();
	const queryClient = new QueryClient({
		defaultOptions: { queries: { staleTime: 30_000, retry: 1 } }
	});
</script>

<svelte:head><meta name="theme-color" content="#111827" /></svelte:head>

<QueryClientProvider client={queryClient}>
	{@render children()}
</QueryClientProvider>
