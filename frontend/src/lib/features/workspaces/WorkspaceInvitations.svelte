<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import type { components } from '#lib/api/schema.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { isUnavailableReadError } from '#lib/api/query-state.js';
	import { createUrlDraft } from '#lib/navigation/url-draft.svelte.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateFormat } from '#lib/format.js';
	import Button from '#lib/design/Button.svelte';
	import DataTable from '#lib/design/DataTable.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import Panel from '#lib/design/Panel.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import StatusNotice from '#lib/design/StatusNotice.svelte';
	import { ph, t } from 'lingui-for-svelte/macro';
	import { workspaceInvitationsQuery } from './queries';
	import {
		readWorkspaceInvitationsState,
		workspaceInvitationParameters,
		workspaceInvitationRoles,
		defaultInvitationDirection,
		type WorkspaceInvitationsState
	} from './list-state';
	import {
		workspaceInvitationMutationOptions,
		workspaceInvitationRevokeMutationOptions
	} from './mutations';

	const workspace = getWorkspaceContext();
	const client = useQueryClient();
	const listing = $derived(readWorkspaceInvitationsState(page.url.searchParams));
	const invitations = createQuery(() => ({
		...workspaceInvitationsQuery(workspace.workspaceId, listing),
		enabled: workspace.can('workspace_invitation.read')
	}));
	const available = $derived(
		invitations.data != null && !isUnavailableReadError(invitations.error)
	);
	const lastPage = $derived(
		Math.max(1, Math.ceil((invitations.data?.total ?? 0) / listing.pageSize))
	);
	const search = createUrlDraft({
		read: (url) => url.searchParams.get('q') ?? '',
		href: (value) => href({ ...listing, search: value, page: 1 })
	});
	const create = createMutation(() =>
		workspaceInvitationMutationOptions(workspace.workspaceId, client)
	);
	const revoke = createMutation(() =>
		workspaceInvitationRevokeMutationOptions(workspace.workspaceId, client)
	);
	const busy = $derived(create.isPending || revoke.isPending);
	const roles = $derived(workspace.view?.allowed_invitation_roles ?? []);
	let username = $state('');
	let role = $state<components['schemas']['WorkspaceInvitationRole']>('viewer');
	let days = $state(7);
	let oneTimeInvitation = $state<components['schemas']['WorkspaceInvitationCreatedView'] | null>(
		null
	);
	let error = $state('');
	let notice = $state('');
	$effect(() => {
		if (!roles.includes(role) && roles[0]) role = roles[0];
	});
	$effect(() => {
		if (
			!workspace.can('workspace_invitation.read') ||
			invitations.data === null ||
			isUnavailableReadError(invitations.error)
		)
			oneTimeInvitation = null;
	});
	$effect(() => {
		if (available && invitations.isSuccess && !invitations.isFetching && listing.page > lastPage)
			navigate({ ...listing, page: lastPage }, true);
	});
	function href(state: WorkspaceInvitationsState) {
		const parameters = workspaceInvitationParameters(state);
		return resolve(
			workspaceHref(
				workspace.workspaceId,
				`settings/invitations${parameters ? `?${parameters}` : ''}`
			)
		);
	}
	function navigate(state: WorkspaceInvitationsState, replace = false) {
		void goto(href(state), { reset: false, replace });
	}
	const nextDirection = $derived(listing.direction === 'asc' ? 'desc' : 'asc');
	function orderLabel(direction: WorkspaceInvitationsState['direction']) {
		if (listing.sort === 'username') return direction === 'asc' ? $t`A–Z` : $t`Z–A`;
		if (listing.sort === 'expires')
			return direction === 'asc' ? $t`Earliest first` : $t`Latest first`;
		return direction === 'asc' ? $t`Oldest first` : $t`Newest first`;
	}
	const directionHint = $derived(
		$t`Sort order: ${ph({ current: orderLabel(listing.direction) })}. Switch to ${ph({ next: orderLabel(nextDirection) })}.`
	);
	async function invite() {
		if (busy || !roles.includes(role) || !username.trim()) return;
		error = '';
		notice = '';
		try {
			const created = await create.mutateAsync({
				username: username.trim(),
				role,
				expires_at: new Date(Date.now() + days * 86_400_000).toISOString()
			});
			if (
				workspace.can('workspace_invitation.read') &&
				invitations.data !== null &&
				!isUnavailableReadError(invitations.error)
			)
				oneTimeInvitation = created;
			username = '';
			notice = $t`Invitation created. Copy this token now; it will not be shown again.`;
		} catch (reason) {
			error = apiErrorMessage(reason, $t`Unable to create invitation`);
		}
	}
	async function revokeInvitation(id: string) {
		if (busy) return;
		error = '';
		notice = '';
		try {
			await revoke.mutateAsync(id);
			if (oneTimeInvitation?.id === id) oneTimeInvitation = null;
			notice = $t`Invitation revoked`;
		} catch (reason) {
			error = apiErrorMessage(reason, $t`Workspace action failed`);
		}
	}
	async function copyLink() {
		if (!oneTimeInvitation) return;
		error = '';
		notice = '';
		try {
			await navigator.clipboard.writeText(`${location.origin}/invite/${oneTimeInvitation.token}`);
			notice = $t`Invitation link copied`;
		} catch {
			error = $t`Unable to copy the invitation link. Select and copy it manually.`;
		}
	}
</script>

<section class="grid grid-cols-1 gap-6" aria-labelledby="workspace-invitations-heading">
	<div>
		<h2 id="workspace-invitations-heading" class="text-xl font-semibold">{$t`Invitations`}</h2>
		<p class="mt-1 text-sm text-surface-700-300">
			{$t`Invite an existing user to join this workspace.`}
		</p>
	</div>
	{#if workspace.can('workspace_invitation.read')}
		{#if roles.length > 0}
			<Panel>
				<form
					class="grid grid-cols-1 gap-4 sm:grid-cols-2"
					onsubmit={(event) => {
						event.preventDefault();
						void invite();
					}}
				>
					<label class="grid grid-cols-1 gap-1 sm:col-span-2"
						>{$t`Exact username`}<input
							class="input"
							bind:value={username}
							required
							disabled={busy}
						/></label
					>
					<label class="grid grid-cols-1 gap-1"
						>{$t`Role`}<select class="select" bind:value={role} disabled={busy}
							>{#each roles as choice (choice)}<option value={choice}
									>{$t(domainLabel(choice))}</option
								>{/each}</select
						></label
					>
					<label class="grid grid-cols-1 gap-1"
						>{$t`Expires in days`}<input
							class="input"
							type="number"
							min="1"
							max="365"
							required
							bind:value={days}
							disabled={busy}
						/></label
					>
					<div class="sm:col-span-2">
						<Button type="submit" variant="filled" disabled={busy || !username.trim()}
							>{$t`Create invitation`}</Button
						>
					</div>
				</form>
			</Panel>
		{/if}
		<StatusNotice {error} {notice} />
		{#if oneTimeInvitation}
			<Panel class="grid grid-cols-1 justify-items-start gap-3">
				<code class="break-all">{location.origin}/invite/{oneTimeInvitation.token}</code>
				<div class="flex flex-wrap gap-2">
					<Button size="sm" disabled={busy} onclick={() => void copyLink()}
						>{$t`Copy one-time link`}</Button
					>
					<Button
						size="sm"
						disabled={busy}
						onclick={() => {
							oneTimeInvitation = null;
						}}>{$t`Dismiss`}</Button
					>
				</div>
			</Panel>
		{/if}
		<Panel>
			<div class="flex min-w-0 flex-wrap items-end gap-3">
				<label class="grid min-w-0 grow basis-56 grid-cols-1 gap-1 text-sm">
					{$t`Search invitations`}<input
						class="input h-9 field-sm"
						type="search"
						bind:value={search.value}
						oncompositionstart={search.compositionStart}
						oncompositionend={search.compositionEnd}
					/>
				</label>
				<label class="grid min-w-0 grow basis-32 grid-cols-1 gap-1 text-sm">
					{$t`Role`}<select
						class="select h-9 field-sm"
						value={listing.role}
						onchange={(event) =>
							navigate({
								...listing,
								role: event.currentTarget.value as WorkspaceInvitationsState['role'],
								page: 1
							})}
					>
						<option value="">{$t`All roles`}</option>
						{#each workspaceInvitationRoles as choice (choice)}<option value={choice}
								>{$t(domainLabel(choice))}</option
							>{/each}
					</select>
				</label>
				<div class="grid min-w-40 grow basis-40 grid-cols-1 gap-1 text-sm">
					<label for="workspace-invitations-sort">{$t`Sort By`}</label>
					<div
						role="group"
						aria-label={$t`Sort`}
						class="field-group min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-0"
					>
						<select
							id="workspace-invitations-sort"
							class="select h-9 field-sm"
							value={listing.sort}
							onchange={(event) => {
								const sort = event.currentTarget.value as WorkspaceInvitationsState['sort'];
								navigate({
									...listing,
									sort,
									direction: defaultInvitationDirection(sort),
									page: 1
								});
							}}
						>
							<option value="created">{$t`Created`}</option>
							<option value="expires">{$t`Expires`}</option>
							<option value="username">{$t`Username`}</option>
						</select>
						<Button
							type="button"
							variant="icon"
							class="-ml-px size-9"
							aria-label={directionHint}
							title={directionHint}
							onclick={() => navigate({ ...listing, direction: nextDirection, page: 1 })}
						>
							<Icon name={listing.direction === 'asc' ? 'arrow-up' : 'arrow-down'} size={16} />
						</Button>
					</div>
				</div>
			</div>
		</Panel>
		{#if invitations.isError || (!invitations.isPending && !available)}
			<QueryError
				message={$t`Unable to load invitations.`}
				busy={invitations.isFetching}
				onRetry={() => void invitations.refetch()}
			/>
		{/if}
		{#if !available && invitations.isPending}<p class="text-surface-700-300">
				{$t`Loading invitations…`}
			</p>
		{:else if available && invitations.data?.items.length}
			<Panel padding="none">
				<DataTable label={$t`Invitations`}>
					<thead
						><tr
							><th>{$t`Username`}</th><th>{$t`Role`}</th><th>{$t`Created`}</th><th>{$t`Expires`}</th
							>{#if workspace.can('workspace_invitation.revoke')}<th class="w-28">{$t`Actions`}</th
								>{/if}</tr
						></thead
					>
					{#each invitations.data.items as invitation (invitation.id)}
						<tbody
							><tr>
								<th scope="row"
									><strong class="font-medium break-all">{invitation.username}</strong></th
								>
								<td data-label={$t`Role`}>{$t(domainLabel(invitation.role))}</td>
								<td data-label={$t`Created`}
									>{$dateFormat.format(new Date(invitation.created_at))}</td
								>
								<td data-label={$t`Expires`}
									>{$dateFormat.format(new Date(invitation.expires_at))}</td
								>
								{#if workspace.can('workspace_invitation.revoke')}<td data-label={$t`Actions`}
										><Button
											size="sm"
											disabled={busy}
											aria-label={$t`Revoke invitation for ${ph({ username: invitation.username })}`}
											onclick={() => void revokeInvitation(invitation.id)}>{$t`Revoke`}</Button
										></td
									>{/if}
							</tr></tbody
						>
					{/each}
				</DataTable>
			</Panel>
		{:else if available}<Notice
				>{listing.search || listing.role
					? $t`No matching invitations.`
					: $t`No pending invitations.`}</Notice
			>{/if}
		{#if available && invitations.data}<Pagination
				page={listing.page}
				pageCount={lastPage}
				pageSize={listing.pageSize}
				total={invitations.data.total}
				onPage={(next) => navigate({ ...listing, page: next })}
				onPageSize={(size) => navigate({ ...listing, page: 1, pageSize: size })}
				busy={invitations.isFetching}
				label={$t`Invitations pagination`}
			/>{/if}
	{:else}<Notice>{$t`Invitations are not available for this workspace.`}</Notice>{/if}
</section>
