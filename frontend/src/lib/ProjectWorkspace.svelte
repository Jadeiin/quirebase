<script lang="ts">
	import { goto } from '$app/navigation';
	import { resolve } from '$app/paths';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { apiRequest, type ItemSummary, type ProjectSummary } from '$lib/api/client';
	import RichText from '$lib/design/RichText.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';

	let { projectId } = $props<{ projectId: string }>();
	type ProjectView = ProjectSummary & {
		members: Array<{ user_id: string; username: string; role: string }>;
		items: ItemSummary[];
	};
	let name = $state('');
	let description = $state('');
	let visibility = $state('private');
	let memberUsername = $state('');
	let memberRole = $state('viewer');
	let busy = $state(false);
	let error = $state('');
	let notice = $state('');
	let loadedProjectId = '';
	const queryClient = useQueryClient();
	const project = createQuery(() => ({
		queryKey: ['project', projectId],
		queryFn: () => apiRequest<ProjectView>(`/projects/${projectId}`)
	}));
	const canEdit = $derived(project.data?.role === 'owner' || project.data?.role === 'editor');
	const isOwner = $derived(project.data?.role === 'owner');

	$effect(() => {
		const value = project.data;
		if (!value || value.id !== projectId || loadedProjectId === projectId) return;
		loadedProjectId = projectId;
		name = value.name;
		description = value.description;
		visibility = value.visibility;
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
			error = reason instanceof Error ? reason.message : $t('Project action failed');
			return false;
		} finally {
			busy = false;
		}
	}

	function saveSettings() {
		void mutate(
			() =>
				apiRequest(`/projects/${projectId}`, {
					method: 'PATCH',
					body: { name, description, visibility }
				}),
			$t('Project settings saved')
		);
	}

	function addMember() {
		void mutate(
			() =>
				apiRequest(`/projects/${projectId}/members`, {
					method: 'PUT',
					body: { username: memberUsername, role: memberRole }
				}),
			$t('Project member saved')
		).then((saved) => {
			if (saved) memberUsername = '';
		});
	}

	function updateMember(username: string, role: string) {
		void mutate(
			() =>
				apiRequest(`/projects/${projectId}/members`, { method: 'PUT', body: { username, role } }),
			$t('Project member saved')
		);
	}

	function removeMember(userId: string) {
		void mutate(
			() => apiRequest(`/projects/${projectId}/members/${userId}`, { method: 'DELETE' }),
			$t('Project member removed')
		);
	}

	function transferOwnership(userId: string) {
		void mutate(
			() => apiRequest(`/projects/${projectId}/ownership/${userId}`, { method: 'POST' }),
			$t('Project ownership transferred')
		);
	}

	async function leaveProject() {
		busy = true;
		error = '';
		try {
			await apiRequest(`/projects/${projectId}/leave`, { method: 'POST' });
			await goto(resolve('/projects'));
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Project action failed');
		} finally {
			busy = false;
		}
	}

	async function deleteProject() {
		const projectName = project.data?.name;
		if (!projectName) return;
		const confirmation = window.prompt(
			`${$t('Permanently delete this Project?')}\n${projectName}`,
			''
		);
		if (confirmation === null) return;
		busy = true;
		error = '';
		try {
			await apiRequest(`/projects/${projectId}`, {
				method: 'DELETE',
				body: { confirmation }
			});
			await goto(resolve('/projects'));
		} catch (reason) {
			error = reason instanceof Error ? reason.message : $t('Project action failed');
		} finally {
			busy = false;
		}
	}
</script>

{#if project.isPending}<p class="text-surface-600">{$t('Loading Project…')}</p>
{:else if project.isError}<p class="text-error-700">{$t('Unable to open this Project.')}</p>
{:else if project.data}
	<div class="workspace-header">
		<div>
			<a class="eyebrow" href={resolve('/projects')}>{$t('Projects')}</a>
			<h1>{project.data.name}</h1>
			<p class="text-surface-600">{project.data.description || $t('No description')}</p>
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
	{#if error}<p class="text-error-700" role="alert">{error}</p>{/if}
	{#if notice}<p
			class="rounded-base border border-success-200 preset-tonal-success px-4 py-3 text-success-900"
			role="status"
		>
			{notice}
		</p>{/if}
	<div class="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(20rem,1fr)]">
		<div class="stack">
			<section class="card border border-surface-300 bg-surface-50 p-5 shadow-sm">
				<h2>{$t('Items')}</h2>
				{#each project.data.items as item (item.id)}
					<div class="item-row grid-cols-[minmax(0,1fr)_auto] items-center">
						<a
							class="grid gap-1 no-underline"
							href={resolve('/(app)/item/[itemId]', { itemId: item.id })}
							><strong><RichText html={item.title_html} /></strong><span class="text-surface-600"
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
											apiRequest(`/projects/${projectId}/items/${item.id}`, { method: 'DELETE' }),
										$t('Item removed from Project')
									)}>{$t('Remove')}</button
							>{/if}
					</div>
				{:else}<p class="text-surface-600">{$t('No Items in this Project.')}</p>{/each}
			</section>
			{#if isOwner}
				<section class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm">
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
			<section class="card border border-surface-300 bg-surface-50 p-5 shadow-sm">
				<h2>{$t('Members')}</h2>
				{#each project.data.members as member (member.user_id)}
					<div class="item-row">
						<strong>{member.username}</strong>
						{#if isOwner && member.role !== 'owner'}
							<div class="toolbar">
								<select
									class="compact input"
									value={member.role}
									onchange={(event) => updateMember(member.username, event.currentTarget.value)}
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
						{:else}<span class="text-surface-600">{$t(domainLabel(member.role))}</span>{/if}
					</div>
				{/each}
				{#if isOwner}
					<form
						class="stack mt-4 border-t border-surface-300 pt-4"
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
			<section class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm">
				<h2>{$t('Project lifecycle')}</h2>
				{#if isOwner}
					{#if project.data.state === 'archived'}<button
							class="btn preset-tonal-surface font-semibold"
							disabled={busy}
							onclick={() =>
								mutate(
									() => apiRequest(`/projects/${projectId}/restore`, { method: 'POST' }),
									$t('Project restored')
								)}>{$t('Restore Project')}</button
						>{:else}<button
							class="btn preset-tonal-surface font-semibold"
							disabled={busy}
							onclick={() =>
								mutate(
									() => apiRequest(`/projects/${projectId}/archive`, { method: 'POST' }),
									$t('Project archived')
								)}>{$t('Archive Project')}</button
						>{/if}
					<button
						class="btn preset-tonal-error font-semibold"
						disabled={busy}
						onclick={deleteProject}>{$t('Delete Project')}</button
					>
				{:else}<button
						class="btn preset-tonal-error font-semibold"
						disabled={busy}
						onclick={leaveProject}>{$t('Leave Project')}</button
					>{/if}
			</section>
		</div>
	</div>
{/if}
