<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { createQuery } from '@tanstack/svelte-query';
	import { onMount } from 'svelte';
	import { ApiError } from '#lib/api/client.js';
	import { workspaceListQuery, workspaceQuery } from '#lib/workspaces/queries.js';
	import {
		clearDefaultWorkspacePreference,
		defaultWorkspacePreference
	} from '#lib/workspaces/preference.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { t } from '#lib/i18n.js';

	const workspaces = createQuery(() => workspaceListQuery());
	let preferredId = $state<string | null>(null);
	let ready = $state(false);
	const preferred = createQuery(() => workspaceQuery(preferredId ?? ''));
	onMount(() => {
		preferredId = defaultWorkspacePreference();
		ready = true;
	});

	$effect(() => {
		if (!ready || !workspaces.data) return;
		if (preferredId && preferred.isPending) return;
		if (preferredId && preferred.isError) {
			if (
				!(preferred.error instanceof ApiError) ||
				preferred.error.code !== 'workspace_unavailable'
			)
				return;
			clearDefaultWorkspacePreference();
		}
		const active = workspaces.data.items.filter((workspace) => workspace.state === 'active');
		const destination = preferred.data ?? active[0];
		if (destination) {
			void goto(resolve(workspaceHref(destination.id)), { replace: true });
			return;
		}
		void goto(resolve('workspace'), { replace: true });
	});
</script>

<main class="mx-auto max-w-3xl p-8" aria-live="polite">
	{#if workspaces.isPending}<p>{$t('Loading workspaces…')}</p>
	{:else if workspaces.isError || (preferredId && preferred.isError && (!(preferred.error instanceof ApiError) || preferred.error.code !== 'workspace_unavailable'))}
		<div class="grid grid-cols-1 justify-items-start gap-3">
			<Notice variant="error">{$t('Unable to load workspaces.')}</Notice>
			<Button
				onclick={() => {
					void workspaces.refetch();
					if (preferredId) void preferred.refetch();
				}}
				disabled={workspaces.isFetching || preferred.isFetching}
				>{workspaces.isFetching ? $t('Loading workspaces…') : $t('Retry')}</Button
			>
		</div>
	{:else}<p>{$t('Opening your workspace…')}</p>{/if}
</main>
