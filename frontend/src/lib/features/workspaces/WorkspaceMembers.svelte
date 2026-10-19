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
	import { domainLabel } from '#lib/domain-labels.js';
	import Button from '#lib/design/Button.svelte';
	import { buttonClass } from '#lib/design/button-classes.js';
	import Panel from '#lib/design/Panel.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import StatusNotice from '#lib/design/StatusNotice.svelte';
	import Pagination from '#lib/design/Pagination.svelte';
	import ConfirmDialog from '#lib/design/ConfirmDialog.svelte';
	import { msg, t } from '#lib/i18n.js';
	import { workspaceMembersQuery, type GovernanceMember } from './queries';
	import { workspaceMemberMutationOptions, type MemberCommand } from './mutations';
	import { readWorkspaceListState, workspaceListParameters } from './list-state';

	const workspace = getWorkspaceContext();
	const client = useQueryClient();
	const listing = $derived(readWorkspaceListState(page.url.searchParams));
	const governance = $derived(workspace.can('workspace_membership.read'));
	const members = createQuery(() =>
		workspaceMembersQuery(
			workspace.workspaceId,
			governance,
			listing.page,
			listing.pageSize,
			listing.search
		)
	);
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
	function navigate(search: string, nextPage = 1, size = listing.pageSize, replace = false) {
		const parameters = workspaceListParameters(search, nextPage, size);
		void goto(
			resolve(
				workspaceHref(
					workspace.workspaceId,
					`settings/members${parameters ? `?${parameters}` : ''}`
				)
			),
			{ reset: false, replaceState: replace }
		);
	}
	$effect(() => {
		if (members.isSuccess && !members.isFetching && listing.page > lastPage)
			navigate(listing.search, lastPage, listing.pageSize, true);
	});
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
			{$t('Find the people in this workspace and view their roles.')}
		</p>
	</div>
	<label class="grid max-w-xl grid-cols-1 gap-1"
		>{$t('Search members')}<input
			class="input"
			value={listing.search}
			oninput={(event) => navigate(event.currentTarget.value, 1, listing.pageSize, true)}
		/></label
	>
	<StatusNotice error={confirmOpen ? '' : error} {notice} />
	{#if members.isPending}<p class="text-surface-700-300">{$t('Loading members…')}</p>
	{:else if members.isError}<Notice variant="error"
			>{$t('Unable to load members.')}
			<Button disabled={members.isFetching} onclick={() => void members.refetch()}
				>{$t('Retry')}</Button
			></Notice
		>
	{:else if members.data?.items.length}
		<Panel padding="none">
			<table class="w-full table-fixed text-left text-sm">
				<thead
					><tr
						><th class="p-3">{$t('Username')}</th><th class="p-3">{$t('Role')}</th
						>{#if governance}<th class="w-24 p-3">{$t('Actions')}</th>{/if}</tr
					></thead
				>
				<tbody>
					{#each members.data.items as member (member.user_id)}
						{@const target = member.governance}
						<tr class="border-t border-surface-300-700">
							<td class="p-3"
								><strong class="font-medium break-all">{member.username}</strong>{#if target}<p
										class="text-xs text-surface-700-300"
									>
										{$t(domainLabel(target.state))}
									</p>{/if}</td
							>
							<td class="p-3"
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
							{#if governance}<td class="p-3">
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
					{/each}
				</tbody>
			</table>
		</Panel>
	{:else}<Notice
			>{listing.search ? $t('No matching members.') : $t('No members to display.')}</Notice
		>{/if}
	{#if members.isSuccess}<Pagination
			page={listing.page}
			pageCount={lastPage}
			pageSize={listing.pageSize}
			total={members.data.total}
			onPage={(next) => navigate(listing.search, next)}
			onPageSize={(size) => navigate(listing.search, 1, size)}
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
