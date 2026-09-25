<script lang="ts">
	import { createMutation, createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiErrorMessage } from '$lib/api/errors';
	import Notice from '$lib/design/Notice.svelte';
	import {
		discussionCreateMutationOptions,
		discussionDeleteMutationOptions
	} from '$lib/features/item/discussion/mutations';
	import ItemDiscussionSection from '$lib/features/item/discussion/ItemDiscussionSection.svelte';
	import ItemSectionState from '$lib/features/item/ItemSectionState.svelte';
	import { itemDiscussionQuery } from '$lib/features/item/queries';
	import { t } from '$lib/i18n';
	import { getSession } from '$lib/session';
	import { getWorkspaceContext } from '$lib/workspaces/context.svelte';
	import type { PageProps } from './$types';

	let { params }: PageProps = $props();
	let mutationError = $state('');
	const queryClient = useQueryClient();
	const { query: session } = getSession();
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
			!workspace.can('discussion.write') ||
			!discussion.data?.some(
				(message) => message.id === messageId && message.author_id === session.data?.user?.id
			)
		)
			return;
		track(discussionDelete.mutateAsync({ messageId }));
	}
</script>

{#if mutationError}<Notice variant="error">{mutationError}</Notice>{/if}
<ItemSectionState loading={discussion.isPending} failed={discussion.isError}>
	<ItemDiscussionSection
		messages={discussion.data!}
		userId={session.data?.user?.id}
		canWrite={workspace.can('discussion.write')}
		busy={discussionCreate.isPending || discussionDelete.isPending}
		onAdd={addDiscussion}
		onDelete={deleteDiscussion}
	/>
</ItemSectionState>
