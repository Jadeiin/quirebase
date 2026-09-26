<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { createQuery } from '@tanstack/svelte-query';
	import { workspaceListQuery } from '$lib/workspaces/queries';
	import {
		clearDefaultWorkspacePreference,
		defaultWorkspacePreference
	} from '$lib/workspaces/preference';
	import { workspaceHref } from '$lib/workspaces/href';
	import Button from '$lib/design/Button.svelte';
	import Notice from '$lib/design/Notice.svelte';
	import { t } from '$lib/i18n';

	const workspaces = createQuery(() => workspaceListQuery());

	$effect(() => {
		const list = workspaces.data;
		if (!list) return;
		const active = list.filter((workspace) => workspace.state === 'active');
		const preferredId = defaultWorkspacePreference();
		const preferred = active.find((workspace) => workspace.id === preferredId);
		const destination = preferred ?? active[0];
		if (preferredId && !preferred) clearDefaultWorkspacePreference();
		if (destination) {
			void goto(resolve(workspaceHref(destination.id)), { replaceState: true });
			return;
		}
		void goto(resolve('/workspace'), { replaceState: true });
	});
</script>

<main class="mx-auto max-w-3xl p-8" aria-live="polite">
	{#if workspaces.isPending}<p>{$t('Loading workspaces…')}</p>
	{:else if workspaces.isError}
		<div class="grid grid-cols-1 justify-items-start gap-3">
			<Notice variant="error">{$t('Unable to load workspaces.')}</Notice>
			<Button onclick={() => void workspaces.refetch()} disabled={workspaces.isFetching}
				>{workspaces.isFetching ? $t('Loading workspaces…') : $t('Retry')}</Button
			>
		</div>
	{:else}<p>{$t('Opening your workspace…')}</p>{/if}
</main>
