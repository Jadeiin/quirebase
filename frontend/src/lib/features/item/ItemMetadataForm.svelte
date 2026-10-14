<script lang="ts">
	import type { components } from '#lib/api/schema.js';
	import { createQuery } from '@tanstack/svelte-query';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { t } from '#lib/i18n.js';
	import type { Metadata } from './metadata-draft.js';
	let {
		metadata,
		citationKey = '',
		busy = false,
		submitLabel,
		onsubmit,
		ondirty,
		serverErrors = []
	} = $props<{
		metadata: Metadata;
		citationKey?: string;
		busy?: boolean;
		submitLabel: string;
		onsubmit: (metadata: Metadata, citationKey: string) => void;
		ondirty?: (dirty: boolean) => void;
		serverErrors?: components['schemas']['ErrorField'][];
	}>();
	const workspace = getWorkspaceContext();
	const schema = createQuery(() => ({
		queryKey: ['commonmeta-schema', workspace.workspaceId],
		staleTime: Infinity,
		queryFn: () => workspace.api.request('GET', '/workspaces/{workspace_id}/metadata/schema')
	}));
	// Load the renderer only when an editable form is mounted.
	const editor = import('./schema-editor/SchemaMetadataEditor.svelte');
</script>

{#if schema.isError}
	<Notice variant="error">{$t('Unable to load metadata editor.')}</Notice>
	<Button onclick={() => schema.refetch()}>{$t('Retry')}</Button>
{:else if schema.data}
	{#await editor}
		<p role="status">{$t('Loading metadata editor…')}</p>
	{:then module}
		<module.default
			{metadata}
			schema={schema.data}
			{citationKey}
			{busy}
			{submitLabel}
			{onsubmit}
			{ondirty}
			{serverErrors}
		/>
	{:catch}
		<Notice variant="error">{$t('Unable to load metadata editor.')}</Notice>
	{/await}
{:else}
	<p role="status">{$t('Loading metadata editor…')}</p>
{/if}
