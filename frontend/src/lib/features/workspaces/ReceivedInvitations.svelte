<script lang="ts">
	import { resolve } from '$app/paths';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import {
		createMutation,
		createQuery,
		keepPreviousData,
		useQueryClient
	} from '@tanstack/svelte-query';
	import type { components } from '#lib/api/schema.js';
	import { ApiError } from '#lib/api/client.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { getSession } from '#lib/session.js';
	import { ph, t } from 'lingui-for-svelte/macro';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateTimeFormat } from '#lib/format.js';
	import Button from '#lib/design/Button.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { setDefaultWorkspacePreference } from '#lib/workspaces/preference.js';
	import { invalidateWorkspaces } from '#lib/query/invalidation.js';
	import { readWorkspaceListState } from './list-state';
	import {
		acceptReceivedInvitationMutation,
		receivedInvitationKeys,
		receivedInvitationQuery,
		receivedInvitationsQuery
	} from './received-invitations';

	type Invitation = components['schemas']['ReceivedWorkspaceInvitationView'];
	const session = getSession().query;
	const userId = $derived(session.data?.user?.id ?? '');
	const client = useQueryClient();
	const listing = $derived(
		readWorkspaceListState({ get: (key) => page.url.searchParams.get(`invitation_${key}`) })
	);
	const inbox = createQuery(() => ({
		...receivedInvitationsQuery(userId, (listing.page - 1) * listing.pageSize, listing.pageSize),
		placeholderData: keepPreviousData
	}));
	const lastPage = $derived(Math.max(1, Math.ceil((inbox.data?.total ?? 0) / listing.pageSize)));
	const mutation = createMutation(() => acceptReceivedInvitationMutation(userId));
	// The target is a submitted operation snapshot. Server state stays in Query.
	let target = $state<Invitation | null>(null);
	let uncertain = $state(false);
	let checking = $state(false);
	let error = $state('');
	const detail = createQuery(() => ({
		...receivedInvitationQuery(userId, target?.id ?? ''),
		enabled: false
	}));
	const busy = $derived(mutation.isPending || checking);

	function navigate(nextPage: number, size = listing.pageSize, replace = false) {
		const parameters = new SvelteURLSearchParams(page.url.search);
		parameters.delete('invitation_page');
		parameters.delete('invitation_page_size');
		if (nextPage > 1) parameters.set('invitation_page', String(nextPage));
		if (size !== 25) parameters.set('invitation_page_size', String(size));
		void goto(
			resolve(parameters.size ? `workspace?${parameters}#invitations` : 'workspace#invitations'),
			{
				reset: false,
				replaceState: replace
			}
		);
	}
	$effect(() => {
		if (inbox.isSuccess && !inbox.isFetching && !inbox.isPlaceholderData && listing.page > lastPage)
			navigate(lastPage, listing.pageSize, true);
	});

	async function checkStatus(invitation: Invitation, failure = '') {
		checking = true;
		try {
			const state = await client.fetchQuery(receivedInvitationQuery(userId, invitation.id));
			uncertain = false;
			error = state.state === 'pending' ? failure : '';
		} catch (reason) {
			uncertain = !(reason instanceof ApiError && reason.status === 404);
			error = uncertain
				? $t`Unable to confirm whether you joined. Check status before trying again.`
				: $t`This invitation is no longer available. Ask the inviter for a new invitation.`;
		} finally {
			await Promise.all([
				client.invalidateQueries({ queryKey: receivedInvitationKeys.all(userId) }),
				invalidateWorkspaces(client)
			]);
			checking = false;
		}
	}

	async function accept(invitation: Invitation) {
		if (busy || uncertain || !invitation.can_accept) return;
		target = invitation;
		error = '';
		let failure = '';
		try {
			await mutation.mutateAsync(invitation.id);
		} catch (reason) {
			failure = apiErrorMessage(reason, $t`Unable to accept invitation`);
		}
		await checkStatus(invitation, failure);
	}
</script>

{#if inbox.data?.total || inbox.isError || target}
	<section
		id="invitations"
		aria-labelledby="invitations-heading"
		class="grid min-w-0 scroll-mt-6 grid-cols-1 gap-4 rounded-xl border border-primary-300-700 bg-primary-50-950 p-4 sm:p-5"
	>
		<header class="grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2">
			<div class="flex flex-wrap items-center gap-2.5">
				<Icon name="mail" size={20} />
				<h2 id="invitations-heading" class="text-lg font-semibold">
					{$t`Workspace invitations`}
				</h2>
				{#if inbox.data?.total}<span
						class="rounded-full bg-primary-700-300 px-2.5 py-0.5 text-xs font-bold text-primary-50-950 tabular-nums"
						aria-label={$t`${ph({ count: inbox.data.total })} pending invitations`}
						>{inbox.data.total}</span
					>{/if}
			</div>
			<Button
				variant="icon"
				size="sm"
				aria-label={$t`Refresh`}
				title={$t`Refresh`}
				disabled={busy || inbox.isFetching}
				onclick={() => {
					void client.invalidateQueries({ queryKey: receivedInvitationKeys.all(userId) });
					if (target) void checkStatus(target);
				}}><Icon name="rotate" size={16} /></Button
			>
			<p class="col-span-2 text-sm text-surface-700-300">
				{$t`Accept an invitation to join a Workspace.`}
			</p>
		</header>
		{#if target}
			<Panel aria-label={$t`Invitation status`} class="grid min-w-0 grid-cols-1 gap-3">
				<div class="flex items-start justify-between gap-3">
					<strong class="min-w-0 break-words">{target.workspace_name}</strong>
					{#if !busy && !uncertain}<Button
							variant="icon"
							size="sm"
							class="shrink-0"
							aria-label={$t`Dismiss`}
							onclick={() => {
								target = null;
								error = '';
							}}><Icon name="close" size={16} /></Button
						>{/if}
				</div>
				{#if busy}<p role="status">{$t`Checking invitation…`}</p>
				{:else if !uncertain && !detail.isError && detail.data?.state === 'accepted'}
					<Notice variant="success">{$t`Invitation accepted.`}</Notice>
					{#if detail.data.can_open}
						<Button
							as="a"
							variant="filled"
							class="justify-self-start"
							href={resolve(workspaceHref(detail.data.workspace_id))}
							onclick={() => setDefaultWorkspacePreference(detail.data!.workspace_id)}
							>{$t`Open Workspace`}</Button
						>
					{:else}<Notice
							>{$t`You joined this workspace, but access is no longer available. Contact a workspace administrator.`}</Notice
						>{/if}
				{:else if detail.data?.state === 'revoked' || detail.data?.state === 'expired'}
					<Notice
						>{$t`This invitation is no longer available. Ask the inviter for a new invitation.`}</Notice
					>
				{/if}
				{#if error}<Notice variant="error">{error}</Notice>{/if}
				{#if uncertain}<Button
						class="justify-self-start"
						disabled={busy}
						onclick={() => target && checkStatus(target)}>{$t`Check status`}</Button
					>{/if}
			</Panel>
		{/if}
		{#if inbox.isPending}<p role="status">{$t`Loading invitations…`}</p>
		{:else if inbox.isError}<QueryError
				message={$t`Unable to load workspace invitations.`}
				busy={inbox.isFetching}
				onRetry={() => void inbox.refetch()}
			/>
		{:else if inbox.data?.items.length}
			<div class="grid min-w-0 grid-cols-1 divide-y divide-primary-200-800">
				{#each inbox.data.items as invitation (invitation.id)}
					<article
						aria-label={invitation.workspace_name}
						class="flex min-w-0 flex-col items-start justify-between gap-3 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:gap-6"
					>
						<div class="grid min-w-0 flex-1 grid-cols-1 gap-2">
							<h3 class="font-semibold break-words">{invitation.workspace_name}</h3>
							<p class="text-sm break-words text-surface-700-300">
								{$t`Invited by ${ph({ username: invitation.inviter_username })}`} · {$t(
									domainLabel(invitation.role)
								)}
							</p>
							<p class="text-sm text-surface-700-300">
								{$t`Expires`}
								{$dateTimeFormat.format(new Date(invitation.expires_at))}
							</p>
							{#if invitation.unavailable_reason === 'workspace_read_only'}<p
									class="text-sm text-surface-700-300"
								>
									{$t`This workspace is read only. You can accept when membership changes are available again.`}
								</p>
							{:else if invitation.unavailable_reason === 'current_member'}<p
									class="text-sm text-surface-700-300"
								>
									{$t`You already have a membership. Contact a workspace administrator to restore access.`}
								</p>{/if}
						</div>
						<Button
							variant="filled"
							size="sm"
							class="shrink-0"
							disabled={busy ||
								uncertain ||
								!invitation.can_accept ||
								(target?.id === invitation.id && detail.isError && !uncertain)}
							onclick={() => accept(invitation)}>{$t`Accept invitation`}</Button
						>
					</article>
				{/each}
			</div>
		{/if}
		{#if inbox.isSuccess && inbox.data.total > listing.pageSize}<Pagination
				page={listing.page}
				pageCount={lastPage}
				pageSize={listing.pageSize}
				total={inbox.data.total}
				onPage={(next) => navigate(next)}
				onPageSize={(size) => navigate(1, size)}
				busy={inbox.isFetching}
				label={$t`Workspace invitations`}
			/>{/if}
	</section>
{/if}
