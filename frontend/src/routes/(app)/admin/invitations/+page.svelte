<script lang="ts">
	import { createMutation, createQuery } from '@tanstack/svelte-query';
	import type { components } from '#lib/api/schema.js';
	import { apiRequest } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import Pagination from '#lib/design/Pagination.svelte';
	import AdminInvitations from '#lib/features/admin/AdminInvitations.svelte';
	import AdminNotices from '#lib/features/admin/AdminNotices.svelte';
	import AdminSectionState from '#lib/features/admin/AdminSectionState.svelte';
	import { adminMutationOptions } from '#lib/features/admin/mutations.js';
	import { adminInvitationsQuery, type InvitationState } from '#lib/features/admin/queries.js';
	import { msg, t, type MessageKey } from '#lib/i18n.js';

	type InvitationCreated = components['schemas']['AdminInvitationCreatedView'];

	let error = $state('');
	let notice = $state<MessageKey | null>(null);
	let invitationUrl = $state('');
	let invitationState = $state<InvitationState | ''>('');
	let invitationPage = $state(1);
	let invitationPageSize = $state(20);
	const invitations = createQuery(() =>
		adminInvitationsQuery(invitationPage, invitationPageSize, invitationState)
	);
	const adminMutation = createMutation(() =>
		adminMutationOptions('invitations', () => invitations.refetch())
	);
	const busy = $derived(adminMutation.isPending);
	$effect(() => {
		if (invitations.isFetching || !invitations.data) return;
		const lastPage = Math.max(1, Math.ceil(invitations.data.total / invitationPageSize));
		if (invitationPage > lastPage) invitationPage = lastPage;
	});

	function mutate(
		operation: () => Promise<unknown>,
		success: MessageKey,
		form?: HTMLFormElement,
		onSuccess?: (result: unknown) => void
	) {
		error = '';
		notice = null;
		void adminMutation
			.mutateAsync({ run: operation, form })
			.then((result) => {
				onSuccess?.(result);
				notice = success;
			})
			.catch((reason) => {
				error = apiErrorMessage(reason, $t('Administration action failed'));
			});
	}

	function createInvitation(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const values = new FormData(form);
		invitationUrl = '';
		void mutate(
			() =>
				apiRequest('POST', '/admin/invitations', {
					body: {
						username: String(values.get('username') ?? ''),
						role: values.get('role') === 'administrator' ? 'administrator' : 'member'
					}
				}),
			msg('Invitation created'),
			form,
			(result) => {
				const invitation = result as InvitationCreated;
				invitationUrl = new URL(invitation.accept_path, window.location.origin).href;
			}
		);
	}

	function revokeInvitation(invitationId: string) {
		invitationUrl = '';
		void mutate(
			() =>
				apiRequest('DELETE', '/admin/invitations/{invitation_id}', {
					params: { path: { invitation_id: invitationId } }
				}),
			msg('Invitation revoked')
		);
	}

	function reissueInvitation(invitationId: string) {
		invitationUrl = '';
		void mutate(
			() =>
				apiRequest('POST', '/admin/invitations/{invitation_id}/reissue', {
					params: { path: { invitation_id: invitationId } }
				}),
			msg('Invitation link reissued'),
			undefined,
			(result) => {
				const invitation = result as InvitationCreated;
				invitationUrl = new URL(invitation.accept_path, window.location.origin).href;
			}
		);
	}
</script>

<AdminNotices {error} {notice} />
<AdminSectionState
	loading={invitations.isPending}
	failed={invitations.isError}
	label={msg('Invitations')}
>
	<AdminInvitations
		invitations={invitations.data!}
		{busy}
		{invitationUrl}
		{invitationState}
		onInvitationState={(state) => {
			invitationState = state;
			invitationPage = 1;
		}}
		onCreateInvitation={createInvitation}
		onRevokeInvitation={revokeInvitation}
		onReissueInvitation={reissueInvitation}
	>
		{#snippet pagination()}
			<Pagination
				page={invitationPage}
				pageSize={invitationPageSize}
				pageCount={Math.max(1, Math.ceil((invitations.data?.total ?? 0) / invitationPageSize))}
				total={invitations.data?.total ?? 0}
				busy={invitations.isFetching || busy}
				label={$t('Invitation pages')}
				onPage={(page) => {
					invitationPage = page;
				}}
				onPageSize={(size) => {
					invitationPageSize = size;
					invitationPage = 1;
				}}
			/>
		{/snippet}
	</AdminInvitations>
</AdminSectionState>
