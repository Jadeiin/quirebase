<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest } from '$lib/api/client';
	import { apiErrorMessage } from '$lib/api/errors';
	import PromptDialog from '$lib/design/PromptDialog.svelte';
	import RichText from '$lib/design/RichText.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';

	let { projectId } = $props<{ projectId: string }>();
	let name = $state('');
	let description = $state('');
	let visibility = $state<'private' | 'public'>('private');
	let memberUsername = $state('');
	let memberRole = $state<'editor' | 'viewer'>('viewer');
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	let deleteDialogOpen = $state(false);
	let loadedProjectId = '';
	const queryClient = useQueryClient();
	const project = createQuery(() => ({
		queryKey: ['project', projectId],
		queryFn: () =>
			apiRequest('GET', '/projects/{project_id}', {
				params: { path: { project_id: projectId } }
			})
	}));
	const canEdit = $derived(project.data?.role === 'owner' || project.data?.role === 'editor');
	const isOwner = $derived(project.data?.role === 'owner');
	const isAdministrator = $derived(project.data?.role === 'administrator');
	const canManageLifecycle = $derived(isOwner || isAdministrator);
	const canLeave = $derived(project.data?.role === 'editor' || project.data?.role === 'viewer');

	$effect(() => {
		const value = project.data;
		if (!value || value.id !== projectId || loadedProjectId === projectId) return;
		loadedProjectId = projectId;
		name = value.name;
		description = value.description;
		visibility = value.visibility === 'public' ? 'public' : 'private';
	});

	async function mutate(operation: () => Promise<unknown>, success: string): Promise<boolean> {
		busy = true;
		error = '';
		notice = '';
		try {
			await operation();
			await Promise.all([
				queryClient.invalidateQueries({ queryKey: ['project', projectId] }),
				queryClient.invalidateQueries({ queryKey: ['projects'] })
			]);
			notice = success;
			return true;
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Project action failed'));
			return false;
		} finally {
			busy = false;
		}
	}

	function saveSettings() {
		void mutate(
			() =>
				apiRequest('PATCH', '/projects/{project_id}', {
					params: { path: { project_id: projectId } },
					body: { name, description, visibility }
				}),
			$t('Project settings saved')
		);
	}

	function addMember() {
		void mutate(
			() =>
				apiRequest('PUT', '/projects/{project_id}/members', {
					params: { path: { project_id: projectId } },
					body: { username: memberUsername, role: memberRole }
				}),
			$t('Project member saved')
		).then((saved) => {
			if (saved) memberUsername = '';
		});
	}

	function updateMember(username: string, role: 'editor' | 'viewer') {
		void mutate(
			() =>
				apiRequest('PUT', '/projects/{project_id}/members', {
					params: { path: { project_id: projectId } },
					body: { username, role }
				}),
			$t('Project member saved')
		);
	}

	function removeMember(userId: string) {
		void mutate(
			() =>
				apiRequest('DELETE', '/projects/{project_id}/members/{user_id}', {
					params: { path: { project_id: projectId, user_id: userId } }
				}),
			$t('Project member removed')
		);
	}

	function transferOwnership(userId: string) {
		void mutate(
			() =>
				apiRequest('POST', '/projects/{project_id}/ownership/{user_id}', {
					params: { path: { project_id: projectId, user_id: userId } }
				}),
			$t('Project ownership transferred')
		);
	}

	async function leaveProject() {
		busy = true;
		error = '';
		try {
			await apiRequest('POST', '/projects/{project_id}/leave', {
				params: { path: { project_id: projectId } }
			});
			await goto(resolve('/projects'));
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Project action failed'));
		} finally {
			busy = false;
		}
	}

	function requestDeleteProject() {
		if (!project.data?.name) return;
		deleteDialogOpen = true;
	}

	async function confirmDeleteProject(confirmation: string) {
		deleteDialogOpen = false;
		busy = true;
		error = '';
		try {
			await apiRequest('DELETE', '/projects/{project_id}', {
				params: { path: { project_id: projectId } },
				body: { confirmation }
			});
			await goto(resolve('/projects'));
		} catch (reason) {
			error = apiErrorMessage(reason, $t('Project action failed'));
		} finally {
			busy = false;
		}
	}
</script>

{#if project.isPending}<p class="text-surface-600-400">{$t('Loading Project…')}</p>
{:else if project.isError}<p class="text-error-700-300">{$t('Unable to open this Project.')}</p>
{:else if project.data}
	<div class="workspace-header">
		<div>
			<a class="eyebrow" href={resolve('/projects')}>{$t('Projects')}</a>
			<h1>{project.data.name}</h1>
			<p class="text-surface-600-400">{project.data.description || $t('No description')}</p>
		</div>
		<div class="toolbar">
			<span class="badge preset-tonal-surface">{$t(domainLabel(project.data.role))}</span>
			<a
				class="btn preset-tonal-surface font-semibold"
				href={resolve(`/library?project=${encodeURIComponent(projectId)}`)}
				>{$t('Open in Library')}</a
			>
		</div>
	</div>
	{#if error}<p class="text-error-700-300" role="alert">{error}</p>{/if}
	{#if notice}<p
			class="rounded-base border border-success-200-800 preset-tonal-success px-4 py-3 text-success-900-100"
			role="status"
		>
			{notice}
		</p>{/if}
	<div class="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(20rem,1fr)]">
		<div class="stack">
			<section class="card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
				<h2>{$t('Items')}</h2>
				{#each project.data.items as item (item.id)}
					<div class="item-row grid-cols-[minmax(0,1fr)_auto] items-center">
						<a
							class="grid gap-1 no-underline"
							href={resolve('/(app)/item/[itemId]', { itemId: item.id })}
							><strong><RichText html={item.title_html} /></strong><span
								class="text-surface-600-400"
								>{item.authors ?? ''}{#if item.publication_date}
									· {item.publication_date}{/if}</span
							></a
						>
						{#if canEdit}<button
								class="btn preset-tonal-surface font-semibold"
								disabled={busy}
								onclick={() =>
									mutate(
										() =>
											apiRequest('DELETE', '/projects/{project_id}/items/{item_id}', {
												params: { path: { project_id: projectId, item_id: item.id } }
											}),
										$t('Item removed from Project')
									)}>{$t('Remove')}</button
							>{/if}
					</div>
				{:else}<p class="text-surface-600-400">{$t('No Items in this Project.')}</p>{/each}
			</section>
			{#if canManageLifecycle}
				<section class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
					<h2>{$t('Project settings')}</h2>
					<label>{$t('Name')}<input class="input" bind:value={name} /></label>
					<label
						>{$t('Description')}<textarea class="textarea min-h-24" bind:value={description}
						></textarea></label
					>
					<label
						>{$t('Visibility')}<select class="select" bind:value={visibility}
							><option value="private">{$t('Private')}</option><option value="public"
								>{$t('Public')}</option
							></select
						></label
					>
					<button
						class="btn preset-filled-primary-700-300 font-semibold"
						disabled={busy}
						onclick={saveSettings}>{$t('Save Project settings')}</button
					>
				</section>
			{/if}
		</div>
		<div class="stack self-start">
			<section class="card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
				<h2>{$t('Members')}</h2>
				{#each project.data.members as member (member.user_id)}
					<div class="item-row">
						<strong>{member.username}</strong>
						{#if isOwner && member.role !== 'owner'}
							<div class="toolbar">
								<select
									class="compact input"
									value={member.role}
									onchange={(event) =>
										updateMember(
											member.username,
											event.currentTarget.value === 'editor' ? 'editor' : 'viewer'
										)}
									><option value="viewer">{$t('Viewer')}</option><option value="editor"
										>{$t('Editor')}</option
									></select
								><button
									class="btn preset-tonal-surface font-semibold"
									disabled={busy}
									onclick={() => transferOwnership(member.user_id)}>{$t('Make owner')}</button
								><button
									class="btn preset-tonal-error font-semibold"
									disabled={busy}
									onclick={() => removeMember(member.user_id)}>{$t('Remove')}</button
								>
							</div>
						{:else}<span class="text-surface-600-400">{$t(domainLabel(member.role))}</span>{/if}
					</div>
				{/each}
				{#if isOwner}
					<form
						class="stack mt-4 border-t border-surface-300-700 pt-4"
						onsubmit={(event) => {
							event.preventDefault();
							addMember();
						}}
					>
						<h3>{$t('Add or update member')}</h3>
						<input
							class="input"
							bind:value={memberUsername}
							placeholder={$t('Username')}
							required
						/>
						<select class="select" bind:value={memberRole}
							><option value="viewer">{$t('Viewer')}</option><option value="editor"
								>{$t('Editor')}</option
							></select
						>
						<button class="btn preset-tonal-surface font-semibold" disabled={busy}
							>{$t('Save member')}</button
						>
					</form>
				{/if}
			</section>
			<section class="stack card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
				<h2>{$t('Project lifecycle')}</h2>
				{#if canManageLifecycle}
					{#if project.data.state === 'archived'}<button
							class="btn preset-tonal-surface font-semibold"
							disabled={busy}
							onclick={() =>
								mutate(
									() =>
										apiRequest('POST', '/projects/{project_id}/restore', {
											params: { path: { project_id: projectId } }
										}),
									$t('Project restored')
								)}>{$t('Restore Project')}</button
						>{:else}<button
							class="btn preset-tonal-surface font-semibold"
							disabled={busy}
							onclick={() =>
								mutate(
									() =>
										apiRequest('POST', '/projects/{project_id}/archive', {
											params: { path: { project_id: projectId } }
										}),
									$t('Project archived')
								)}>{$t('Archive Project')}</button
						>{/if}
					<button
						class="btn preset-tonal-error font-semibold"
						disabled={busy}
						onclick={requestDeleteProject}>{$t('Delete Project')}</button
					>
				{:else if canLeave}<button
						class="btn preset-tonal-error font-semibold"
						disabled={busy}
						onclick={leaveProject}>{$t('Leave Project')}</button
					>{/if}
			</section>
			<PromptDialog
				bind:open={deleteDialogOpen}
				title={$t('Permanently delete this Project?')}
				body={$t('Type the Project name to confirm. This cannot be undone.')}
				label={$t('Project name')}
				placeholder={project.data?.name ?? ''}
				requireMatch={project.data?.name ?? ''}
				confirmLabel={$t('Delete Project')}
				{busy}
				onConfirm={(value) => void confirmDeleteProject(value)}
			/>
		</div>
	</div>
{/if}
