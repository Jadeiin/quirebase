<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiErrorMessage } from '$lib/api/errors';
	import Notice from '$lib/design/Notice.svelte';
	import PromptDialog from '$lib/design/PromptDialog.svelte';
	import {
		discussionCreateMutationOptions,
		discussionDeleteMutationOptions,
		discussionModerationMutationOptions
	} from '$lib/features/item/discussion/mutations';
	import ItemDiscussionSection from '$lib/features/item/discussion/ItemDiscussionSection.svelte';
	import ItemSectionState from '$lib/features/item/ItemSectionState.svelte';
	import { itemDiscussionQuery } from '$lib/features/item/queries';
	import { t } from '$lib/i18n';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
	let mutationError = $state('');
	let moderationMessageId = $state<string | null>(null);
	let moderationDialogOpen = $state(false);
	const queryClient = useQueryClient();
	const workspace = getWorkspaceContext();
	const discussion = createQuery(() =>
		itemDiscussionQuery(params.workspaceId, params.itemId, true)
	);
	const discussionCreate = createMutation(() =>
		discussionCreateMutationOptions(params.workspaceId, params.itemId, queryClient)
	);
	const discussionDelete = createMutation(() =>
		discussionDeleteMutationOptions(params.workspaceId, params.itemId, queryClient)
	);
	const discussionModerate = createMutation(() =>
		discussionModerationMutationOptions(params.workspaceId, params.itemId, queryClient)
	);

	function track(promise: Promise<unknown>) {
		mutationError = '';
		void promise.catch((error) => {
			mutationError = apiErrorMessage(error, $t('Unable to save changes'));
		});
	}

	function addDiscussion(event: SubmitEvent) {
		event.preventDefault();
		if (!workspace.can('discussion.write')) return;
		const form = event.currentTarget as HTMLFormElement;
		const body = String(new FormData(form).get('body') ?? '').trim();
		if (body) track(discussionCreate.mutateAsync({ form, body }));
	}

	function deleteDiscussion(messageId: string) {
		if (
			!discussion.data?.some(
				(message) => message.id === messageId && message.allowed_actions.includes('delete')
			)
		)
			return;
		track(discussionDelete.mutateAsync({ messageId }));
	}

	function moderateDiscussion(reason: string) {
		const messageId = moderationMessageId;
		if (
			!messageId ||
			!reason.trim() ||
			!discussion.data?.some(
				(message) => message.id === messageId && message.allowed_actions.includes('moderate')
			)
		)
			return;
		moderationDialogOpen = false;
		track(discussionModerate.mutateAsync({ messageId, reason: reason.trim() }));
	}
</script>

{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
<ItemSectionState loading={discussion.isPending} failed={discussion.isError}>
	<ItemDiscussionSection
		messages={discussion.data!}
		canWrite={workspace.can('discussion.write')}
		busy={discussionCreate.isPending || discussionDelete.isPending || discussionModerate.isPending}
		onAdd={addDiscussion}
		onDelete={deleteDiscussion}
		onModerate={(messageId) => {
			moderationMessageId = messageId;
			moderationDialogOpen = true;
		}}
	/>
</ItemSectionState>
<PromptDialog
	bind:open={moderationDialogOpen}
	title={$t('Moderate Discussion message')}
	body={$t('Give a reason for removing this message. The action is recorded in the audit log.')}
	label={$t('Moderation reason')}
	confirmLabel={$t('Remove message')}
	busy={discussionModerate.isPending}
	onConfirm={moderateDiscussion}
/>
