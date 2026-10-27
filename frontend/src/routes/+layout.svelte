<script lang="ts">
	import { QueryClient, QueryClientProvider } from '@tanstack/svelte-query';
	import { LocaleProvider } from '@skeletonlabs/skeleton-svelte';
	import { setLinguiContext } from 'lingui-for-svelte';
	import { onMount } from 'svelte';
	import { i18n, type Messages } from '@lingui/core';
	import {
		activeLocale,
		activateLocale,
		detectInitialLocale,
		syncLocaleAcrossTabs,
		type Locale
	} from '#lib/locale.js';
	import { messages as englishMessages } from '#lib/locales/en-US/messages.js';
	import { messages as chineseMessages } from '#lib/locales/zh-CN/messages.js';

	import '../app.css';

	let { children } = $props();
	i18n.load({ 'en-US': englishMessages, 'zh-CN': chineseMessages } satisfies Record<
		Locale,
		Messages
	>);
	activateLocale(detectInitialLocale());
	setLinguiContext(i18n);
	onMount(syncLocaleAcrossTabs);
	const queryClient = new QueryClient({
		defaultOptions: { queries: { staleTime: 30_000, retry: 1 } }
	});
</script>

<QueryClientProvider client={queryClient}>
	<LocaleProvider locale={$activeLocale}>
		{@render children()}
	</LocaleProvider>
</QueryClientProvider>
