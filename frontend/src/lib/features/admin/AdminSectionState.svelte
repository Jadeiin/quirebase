<script lang="ts">
	import LoadingState from '#lib/design/LoadingState.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import type { Snippet } from 'svelte';
	import { ph, t } from 'lingui-for-svelte/macro';
	import type { MessageDescriptor } from '@lingui/core';
	import { adminReadState } from './read-state';

	let {
		loading,
		failed,
		available,
		error,
		label,
		busy = false,
		onRetry,
		children
	}: {
		loading: boolean;
		failed: boolean;
		available?: boolean;
		error?: unknown;
		label: MessageDescriptor;
		busy?: boolean;
		onRetry: () => void;
		children: Snippet;
	} = $props();
	const state = $derived(adminReadState({ loading, failed, available, error }));
</script>

{#if state === 'loading'}
	<LoadingState label={$t`Loading ${ph({ section: $t(label) })}…`} />
{:else if state === 'unavailable'}
	<QueryError message={$t`Unable to load administration.`} {busy} {onRetry} />
{:else}
	{#if state === 'stale'}
		<QueryError message={$t`Unable to load administration.`} {busy} {onRetry} />
	{/if}
	{@render children()}
{/if}
