<script lang="ts">
	import type { components } from '$lib/api/schema';
	import ItemAnnotationsSection from '$lib/features/item/annotations/ItemAnnotationsSection.svelte';
	import ItemDiscussionSection from '$lib/features/item/discussion/ItemDiscussionSection.svelte';
	import ItemFilesSection from '$lib/features/item/files/ItemFilesSection.svelte';
	import ItemMetadataSection from '$lib/features/item/metadata/ItemMetadataSection.svelte';
	import ItemOrganizeSection from '$lib/features/item/organize/ItemOrganizeSection.svelte';
	import ItemOverviewSection from '$lib/features/item/overview/ItemOverviewSection.svelte';
	import { t } from '$lib/i18n';
	import type { ItemSection } from './queries';
	import type { FileRow, FilesView, ItemDetail, OrganizeView, DiscussionMessage } from './types';

	let {
		itemId,
		section,
		workspace,
		details,
		files,
		organize,
		discussion,
		loading,
		failed,
		canEdit,
		metadataBusy,
		filesBusy,
		organizeBusy,
		discussionBusy,
		onMetadata,
		onUpload,
		onUploadFromUrl,
		onDownload,
		onDelete,
		onToggleProject,
		onAddTag,
		onToggleTag,
		onAddSuggestedTag,
		onRefresh,
		onAddDiscussion,
		onDeleteDiscussion,
		userId,
		isAdministrator
	} = $props<{
		itemId: string;
		section: ItemSection;
		workspace?: components['schemas']['ItemWorkspaceView'];
		details?: ItemDetail;
		files?: FilesView;
		organize?: OrganizeView;
		discussion?: DiscussionMessage[];
		loading: boolean;
		failed: boolean;
		canEdit: boolean;
		metadataBusy: boolean;
		filesBusy: boolean;
		organizeBusy: boolean;
		discussionBusy: boolean;
		onMetadata: (item: ItemDetail, metadata: components['schemas']['ItemMetadata-Input']) => void;
		onUpload: (event: SubmitEvent, kind: 'revision' | 'attachment') => void;
		onUploadFromUrl: (event: SubmitEvent, kind: 'revision' | 'attachment') => void;
		onDownload: (file: FileRow) => void;
		onDelete: (file: FileRow) => void;
		onToggleProject: (project: OrganizeView['projects'][number]) => void;
		onAddTag: (event: SubmitEvent) => void;
		onToggleTag: (tagId: string, assigned: boolean) => void;
		onAddSuggestedTag: (name: string) => void;
		onRefresh: () => void;
		onAddDiscussion: (event: SubmitEvent) => void;
		onDeleteDiscussion: (messageId: string) => void;
		userId?: string;
		isAdministrator: boolean;
	}>();
</script>

{#if loading}
	<div class="grid min-h-52 grid-cols-1 place-items-center text-surface-600-400">
		{$t('Loading')}…
	</div>
{:else if failed}
	<div class="grid min-h-52 grid-cols-1 place-items-center text-error-700-300">
		{$t('Unable to open this Item section.')}
	</div>
{:else if section === 'overview'}
	<ItemOverviewSection {itemId} data={workspace!} {details} />
{:else if section === 'metadata'}
	<ItemMetadataSection item={details!} {canEdit} busy={metadataBusy} onSubmit={onMetadata} />
{:else if section === 'files'}
	<ItemFilesSection
		{itemId}
		data={files!}
		{details}
		{canEdit}
		busy={filesBusy}
		{onUpload}
		{onUploadFromUrl}
		{onDownload}
		{onDelete}
	/>
{:else if section === 'organize'}
	<ItemOrganizeSection
		data={organize!}
		busy={organizeBusy}
		{onToggleProject}
		{onAddTag}
		{onToggleTag}
		{onAddSuggestedTag}
		{onRefresh}
	/>
{:else if section === 'annotations'}
	<ItemAnnotationsSection {itemId} />
{:else}
	<ItemDiscussionSection
		messages={discussion!}
		{userId}
		{isAdministrator}
		busy={discussionBusy}
		onAdd={onAddDiscussion}
		onDelete={onDeleteDiscussion}
	/>
{/if}
