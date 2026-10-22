<script lang="ts">
	import { resolve } from '$app/paths';
	import { page } from '$app/state';
	import { goto } from '$app/navigation';
	import { createQuery, createMutation, useQueryClient } from '@tanstack/svelte-query';
	import { Menu, Portal } from '@skeletonlabs/skeleton-svelte';
	import { can } from '#lib/authorization/can.js';
	import { getWorkspaceContext } from '#lib/workspaces/context.svelte.js';
	import { workspaceHref } from '#lib/workspaces/href.js';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import { isUnavailableReadError } from '#lib/api/query-state.js';
	import { createUrlDraft } from '#lib/navigation/url-draft.svelte.js';
	import { domainLabel } from '#lib/domain-labels.js';
	import { dateFormat } from '#lib/format.js';
	import Button from '#lib/design/Button.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import DataTable from '#lib/design/DataTable.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import { buttonClass } from '#lib/design/button-classes.js';
	import Panel from '#lib/design/Panel.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import StatusNotice from '#lib/design/StatusNotice.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import { msg, t } from '#lib/i18n.js';
	import { workspaceMembersQuery, type GovernanceMember } from './queries';
	import { workspaceMemberMutationOptions, type MemberCommand } from './mutations';
	import {
		readWorkspaceMembersState,
		workspaceMemberParameters,
		workspaceRoles,
		type WorkspaceMembersState
	} from './list-state';

	const workspace = getWorkspaceContext();
	const client = useQueryClient();
	const governance = $derived(workspace.can('workspace_membership.read'));
	const listing = $derived(readWorkspaceMembersState(page.url.searchParams, governance));
	const members = createQuery(() =>
		workspaceMembersQuery(workspace.workspaceId, governance, listing)
	);
	const available = $derived(members.data != null && !isUnavailableReadError(members.error));
	const search = createUrlDraft({
		read: (url) => url.searchParams.get('q') ?? '',
		href: (value) => href({ ...listing, search: value, page: 1 })
	});
	const mutation = createMutation(() =>
		workspaceMemberMutationOptions(workspace.workspaceId, client)
	);
	const lastPage = $derived(Math.max(1, Math.ceil((members.data?.total ?? 0) / listing.pageSize)));
	let error = $state('');
	let notice = $state('');
	let confirmOpen = $state(false);
	let confirmation = $state<{ member: GovernanceMember; action: 'transfer' | 'terminate' } | null>(
		null
	);
	const messages = {
		role: msg('Member role updated'),
		suspend: msg('Member suspended'),
		reactivate: msg('Member reactivated'),
		terminate: msg('Member removed'),
		transfer: msg('Ownership transferred')
	};
	function href(state: WorkspaceMembersState) {
		const parameters = workspaceMemberParameters(state);
		return resolve(
			workspaceHref(workspace.workspaceId, `settings/members${parameters ? `?${parameters}` : ''}`)
		);
	}
	function navigate(state: WorkspaceMembersState, replace = false) {
		void goto(href(state), { reset: false, replace });
	}
	$effect(() => {
		if (members.isSuccess && available && !members.isFetching && listing.page > lastPage)
			navigate({ ...listing, page: lastPage }, true);
	});
	$effect(() => {
		if (!governance || members.data === null || isUnavailableReadError(members.error)) {
			confirmOpen = false;
			confirmation = null;
		}
	});
	const nextDirection = $derived(listing.direction === 'asc' ? 'desc' : 'asc');
	function orderLabel(direction: WorkspaceMembersState['direction']) {
		return listing.sort === 'username'
			? direction === 'asc'
				? $t('A–Z')
				: $t('Z–A')
			: direction === 'asc'
				? $t('Oldest first')
				: $t('Newest first');
	}
	const directionHint = $derived(
		$t('Sort order: {current}. Switch to {next}.', {
			current: orderLabel(listing.direction),
			next: orderLabel(nextDirection)
		})
	);
	async function run(command: MemberCommand) {
		if (mutation.isPending) return;
		error = '';
		notice = '';
		try {
			await mutation.mutateAsync(command);
			confirmOpen = false;
			notice = $t(messages[command.action]);
		} catch (reason) {
			error = apiErrorMessage(reason, 'Workspace action failed');
		}
	}
	function ask(member: GovernanceMember, action: 'transfer' | 'terminate') {
		error = '';
		confirmation = { member, action };
		confirmOpen = true;
	}
</script>

<section class="grid grid-cols-1 gap-4" aria-labelledby="workspace-members-heading">
	<div>
		<h2 id="workspace-members-heading" class="text-xl font-semibold">{$t('Members')}</h2>
		<p class="mt-1 text-sm text-surface-700-300">
			{$t('Find members and view their roles.')}
		</p>
	</div>
	<Panel>
		<div class="flex min-w-0 flex-wrap items-end gap-3">
			<label class="grid min-w-0 grow basis-56 grid-cols-1 gap-1 text-sm">
				{$t('Search members')}<input
					class="input h-9 field-sm"
					type="search"
					bind:value={search.value}
					oncompositionstart={search.compositionStart}
					oncompositionend={search.compositionEnd}
				/>
			</label>
			<label class="grid min-w-0 grow basis-32 grid-cols-1 gap-1 text-sm">
				{$t('Role')}<select
					class="select h-9 field-sm"
					value={listing.role}
					onchange={(event) =>
						navigate({
							...listing,
							role: event.currentTarget.value as WorkspaceMembersState['role'],
							page: 1
						})}
				>
					<option value="">{$t('All roles')}</option>
					{#each workspaceRoles as role (role)}<option value={role}>{$t(domainLabel(role))}</option
						>{/each}
				</select>
			</label>
			{#if governance}
				<label class="grid min-w-0 grow basis-32 grid-cols-1 gap-1 text-sm">
					{$t('State')}<select
						class="select h-9 field-sm"
						value={listing.state}
						onchange={(event) =>
							navigate({
								...listing,
								state: event.currentTarget.value as WorkspaceMembersState['state'],
								page: 1
							})}
					>
						<option value="">{$t('Any state')}</option>
						<option value="active">{$t('Active')}</option>
						<option value="suspended">{$t('Suspended')}</option>
					</select>
				</label>
			{/if}
			<div class="grid min-w-40 grow basis-40 grid-cols-1 gap-1 text-sm">
				<label for="workspace-members-sort">{$t('Sort By')}</label>
				<div
					role="group"
					aria-label={$t('Sort')}
					class="field-group min-w-0 grid-cols-[minmax(0,1fr)_auto] gap-0"
				>
					<select
						id="workspace-members-sort"
						class="select h-9 field-sm"
						value={listing.sort}
						onchange={(event) =>
							navigate({
								...listing,
								sort: event.currentTarget.value === 'joined' && governance ? 'joined' : 'username',
								direction: 'asc',
								page: 1
							})}
					>
						<option value="username">{$t('Username')}</option>
						{#if governance}<option value="joined">{$t('Date joined')}</option>{/if}
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
	<StatusNotice error={confirmOpen ? '' : error} {notice} />
	{#if members.isError || (!members.isPending && !available)}
		<QueryError
			message={$t('Unable to load members.')}
			busy={members.isFetching}
			onRetry={() => void members.refetch()}
		/>
	{/if}
	{#if !available && members.isPending}<p class="text-surface-700-300">{$t('Loading members…')}</p>
	{:else if available && members.data?.items.length}
		<Panel padding="none">
			<DataTable label={$t('Members')}>
				<thead
					><tr
						><th class="p-3">{$t('Username')}</th><th class="p-3">{$t('Role')}</th
						>{#if governance}<th>{$t('State')}</th><th>{$t('Date joined')}</th><th class="w-28"
								>{$t('Actions')}</th
							>{/if}</tr
					></thead
				>
				{#each members.data.items as member (member.user_id)}
					{@const target = member.governance}
					<tbody>
						<tr class="border-t border-surface-300-700">
							<th scope="row"><strong class="font-medium break-all">{member.username}</strong></th>
							<td data-label={$t('Role')}
								><span>{$t(domainLabel(member.role))}</span>
								{#if target && target.allowed_roles.length > 0}
									<select
										class="select mt-1 w-full min-w-0"
										aria-label={$t('Role for {username}', { username: member.username })}
										value=""
										disabled={mutation.isPending}
										onchange={(event) => {
											const role = event.currentTarget
												.value as GovernanceMember['allowed_roles'][number];
											event.currentTarget.value = '';
											void run({ action: 'role', membershipId: target.membership_id, role });
										}}
										><option value="" disabled>{$t('Choose a role')}</option
										>{#each target.allowed_roles as role (role)}<option value={role}
												>{$t(domainLabel(role))}</option
											>{/each}</select
									>
								{/if}
							</td>
							{#if governance}<td data-label={$t('State')}
									>{target ? $t(domainLabel(target.state)) : ''}</td
								><td data-label={$t('Date joined')}
									>{target ? $dateFormat.format(new Date(target.joined_at)) : ''}</td
								><td data-label={$t('Actions')}>
									{#if target && (can(target.authorization, 'workspace_member.suspend') || can(target.authorization, 'workspace_member.reactivate') || can(target.authorization, 'workspace_member.transfer_ownership') || can(target.authorization, 'workspace_member.terminate'))}
										<Menu positioning={{ placement: 'bottom-end', gutter: 8 }}>
											<Menu.Trigger
												class={buttonClass('tonal', 'sm')}
												aria-label={$t('Actions for {username}', { username: member.username })}
												disabled={mutation.isPending}>{$t('Actions')}</Menu.Trigger
											>
											<Portal
												><Menu.Positioner class="z-100"
													><Menu.Content class="min-w-48 border-surface-300-700 p-1 shadow-xl">
														{#if can(target.authorization, 'workspace_member.suspend')}<Menu.Item
																value="suspend"
																onclick={() =>
																	void run({
																		action: 'suspend',
																		membershipId: target.membership_id
																	})}>{$t('Suspend')}</Menu.Item
															>{/if}
														{#if can(target.authorization, 'workspace_member.reactivate')}<Menu.Item
																value="reactivate"
																onclick={() =>
																	void run({
																		action: 'reactivate',
																		membershipId: target.membership_id
																	})}>{$t('Reactivate')}</Menu.Item
															>{/if}
														{#if can(target.authorization, 'workspace_member.transfer_ownership')}<Menu.Item
																value="transfer"
																onclick={() => ask(target, 'transfer')}
																>{$t('Transfer ownership')}</Menu.Item
															>{/if}
														{#if can(target.authorization, 'workspace_member.terminate')}<Menu.Item
																value="terminate"
																onclick={() => ask(target, 'terminate')}
																>{$t('Terminate')}</Menu.Item
															>{/if}
													</Menu.Content></Menu.Positioner
												></Portal
											>
										</Menu>
									{/if}
								</td>{/if}
						</tr>
					</tbody>
				{/each}
			</DataTable>
		</Panel>
	{:else if available}<Notice
			>{listing.search || listing.role || listing.state
				? $t('No matching members.')
				: $t('No members to display.')}</Notice
		>{/if}
	{#if available && members.data}<Pagination
			page={listing.page}
			pageCount={lastPage}
			pageSize={listing.pageSize}
			total={members.data.total}
			onPage={(next) => navigate({ ...listing, page: next })}
			onPageSize={(size) => navigate({ ...listing, page: 1, pageSize: size })}
			busy={members.isFetching}
			label={$t('Members pagination')}
		/>{/if}
</section>

<ConfirmDialog
	bind:open={confirmOpen}
	title={confirmation?.action === 'transfer' ? $t('Transfer ownership') : $t('Terminate')}
	body={confirmation?.action === 'transfer'
		? $t(
				'Transfer workspace ownership to {username}? You will become an admin and lose owner-only governance actions.',
				{ username: confirmation.member.username }
			)
		: $t('Remove {username} from this workspace? They will lose access to its content.', {
				username: confirmation?.member.username ?? ''
			})}
	confirmLabel={confirmation?.action === 'transfer' ? $t('Transfer ownership') : $t('Terminate')}
	busy={mutation.isPending}
	{error}
	onConfirm={() => {
		if (confirmation)
			void run({ action: confirmation.action, membershipId: confirmation.member.membership_id });
	}}
/>
