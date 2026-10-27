<script lang="ts">
	import { resolve } from '$app/paths';
	import Button from '#lib/design/Button.svelte';
	import { t } from 'lingui-for-svelte/macro';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import ImportBatchList from './ImportBatchList.svelte';

	const workspace = getWorkspaceContext();
</script>

<div class="mb-6 flex flex-wrap items-end justify-between gap-4">
	<div>
		<h1 class="mb-2">{$t`Import history`}</h1>
		<p class="mb-0 max-w-2xl text-surface-600-400">
			{$t`View recent imports. Old previews and records are removed automatically; Items and files are kept.`}
		</p>
	</div>
	{#if workspace.can('item.create')}
		<Button as="a" variant="filled" href={resolve(workspaceHref(workspace.workspaceId, 'import'))}>
			{$t`New import`}
		</Button>
	{/if}
</div>
<ImportBatchList />
