<script lang="ts">
	import { resolve } from '$app/paths';
	import { createQuery, useQueryClient } from '@tanstack/svelte-query';
	import { SvelteURLSearchParams } from 'svelte/reactivity';
	import {
		apiDownloadGet,
		apiRequest,
		type ItemSummary,
		type SessionView,
		type WorkspaceView
	} from '$lib/api/client';
	import type { components } from '$lib/api/schema';
	import RichText from '$lib/design/RichText.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import ItemActions from '$lib/ItemActions.svelte';
	import ItemMetadataForm from '$lib/ItemMetadataForm.svelte';
	import { msg, t, type MessageKey } from '$lib/i18n';
	import type { CanonicalAnnotation } from '$lib/pdf/annotation-adapter';

	type ItemDetail = ItemSummary & {
		metadata: components['schemas']['ItemMetadata-Input'];
		abstract_html: string | null;
	};
	type FileRow = {
		id: string;
		kind: 'revision' | 'attachment';
		original_name: string;
		mime_type: string;
		size: number;
		created_at: string;
		page_count?: number | null;
		processing_state?: string | null;
	};
	type FilesView = { item_id: string; files: FileRow[] };
	type OrganizeView = {
		item: ItemSummary;
		permissions: { edit: boolean };
		tags: Array<{ id: string; name: string }>;
		projects: Array<{ id: string; name: string; role: string; assigned: boolean }>;
		tag_matrix: {
			groups: Array<{
				letter: string;
				tags: Array<{ id: string; name: string }>;
				names: string[];
			}>;
			assigned_ids: string[];
			recommended_ids: string[];
			suggested_names: string[];
			suggested_single_words: string[];
			suggested_phrases: string[];
			recommendation_state: string;
			recommendation_error: string | null;
		};
	};
	type Message = {
		id: string;
		author_id: string;
		author_username: string;
		body: string;
		created_at: string;
	};
	type AnnotationRow = CanonicalAnnotation & { revision_name: string };
	type ItemSection = 'overview' | 'metadata' | 'files' | 'organize' | 'annotations' | 'discussion';

	let { itemId, section } = $props<{ itemId: string; section: ItemSection }>();
	let mutationError = $state('');
	let busy = $state(false);
	let tagFilter = $state('');
	let annotationRevision = $state('all');
	const queryClient = useQueryClient();

	const endpoint = $derived(
		section === 'overview'
			? `/items/${itemId}/workspace`
			: section === 'metadata'
				? `/items/${itemId}`
				: section === 'files'
					? `/items/${itemId}/documents`
					: section === 'organize'
						? `/items/${itemId}/organize`
						: section === 'discussion'
							? `/items/${itemId}/discussions`
							: `/items/${itemId}/workspace`
	);
	const shell = createQuery(() => ({
		queryKey: ['item-shell', itemId],
		queryFn: () => apiRequest<WorkspaceView>(`/items/${itemId}/workspace`)
	}));
	const session = createQuery(() => ({
		queryKey: ['session'],
		queryFn: () => apiRequest<SessionView>('/session')
	}));
	const details = createQuery(() => ({
		queryKey: ['item-details', itemId],
		enabled: section === 'overview' || section === 'files',
		queryFn: () => apiRequest<ItemDetail>(`/items/${itemId}`)
	}));
	const workspace = createQuery(() => ({
		queryKey: section === 'overview' ? ['item-shell', itemId] : ['item-section', itemId, section],
		queryFn: () => apiRequest<unknown>(endpoint)
	}));
	const annotationDocuments = createQuery(() => ({
		queryKey: ['item-annotation-documents', itemId],
		enabled: section === 'annotations',
		queryFn: () => apiRequest<FilesView>(`/items/${itemId}/documents`)
	}));
	const annotationRevisions = $derived(
		annotationDocuments.data?.files.filter((file) => file.kind === 'revision') ?? []
	);
	const annotationProjects = createQuery(() => ({
		queryKey: ['item-annotation-scopes', itemId],
		enabled: section === 'annotations',
		queryFn: () => apiRequest<OrganizeView>(`/items/${itemId}/organize`)
	}));
	const annotationProjectIds = $derived(
		(annotationProjects.data?.projects ?? [])
			.filter((project) => project.assigned)
			.map((project) => project.id)
			.sort()
	);
	const annotations = createQuery(() => ({
		queryKey: [
			'item-annotations',
			itemId,
			annotationRevisions.map((revision) => revision.id).join(','),
			annotationProjectIds.join(',')
		],
		enabled:
			section === 'annotations' && annotationRevisions.length > 0 && annotationProjects.isSuccess,
		queryFn: async () => {
			if (!annotationProjects.isSuccess) {
				throw (
					annotationProjects.error ??
					new Error('Unable to discover project scopes for annotations.')
				);
			}
			const scopes: Array<string | null> = [null, ...annotationProjectIds];
			const responses = await Promise.all(
				annotationRevisions.flatMap((revision) =>
					scopes.map(async (projectId) => {
						const parameters = new SvelteURLSearchParams({ revision_id: revision.id });
						if (projectId) parameters.set('project_id', projectId);
						return (
							await apiRequest<CanonicalAnnotation[]>(`/items/${itemId}/annotations?${parameters}`)
						).map((annotation) => ({
							...annotation,
							revision_name: revision.original_name
						}));
					})
				)
			);
			const rows: Record<string, AnnotationRow> = {};
			for (const annotation of responses.flat()) rows[annotation.id] = annotation;
			return Object.values(rows);
		}
	}));
	const displayedAnnotations = $derived(
		(annotations.data ?? []).filter(
			(annotation: AnnotationRow) =>
				annotationRevision === 'all' || annotation.revision_id === annotationRevision
		)
	);
	const annotationsLoading = $derived(
		annotationDocuments.isPending ||
			(annotationRevisions.length > 0 &&
				(annotationProjects.isPending || (annotationProjects.isSuccess && annotations.isPending)))
	);
	const annotationsError = $derived(
		annotationDocuments.isError ||
			(annotationRevisions.length > 0 && (annotationProjects.isError || annotations.isError))
	);
	const title = $derived(
		(section === 'metadata' ? (workspace.data as ItemDetail | undefined)?.title_html : undefined) ??
			(section === 'organize'
				? (workspace.data as OrganizeView | undefined)?.item.title_html
				: undefined) ??
			shell.data?.item.title_html
	);
	const labels: Record<ItemSection, MessageKey> = {
		overview: msg('Overview'),
		metadata: msg('Metadata'),
		files: msg('Files'),
		organize: msg('Organize'),
		annotations: msg('Annotations'),
		discussion: msg('Discussion')
	};
	function sectionPath(key: string) {
		return key === 'overview' ? (`/item/${itemId}` as const) : (`/item/${itemId}/${key}` as const);
	}
	const sectionLabel = $derived(labels[section as ItemSection]);

	async function mutate(operation: () => Promise<unknown>, form?: HTMLFormElement) {
		busy = true;
		mutationError = '';
		try {
			await operation();
			await Promise.all([
				workspace.refetch(),
				shell.refetch(),
				queryClient.invalidateQueries({ queryKey: ['item-details', itemId] })
			]);
			form?.reset();
		} catch (error) {
			mutationError = error instanceof Error ? error.message : $t('Unable to save changes');
		} finally {
			busy = false;
		}
	}

	async function waitForWorkflow(workflowId: string) {
		for (;;) {
			const workflow = await apiRequest<{ state: string; error: string | null }>(
				`/workflows/${workflowId}`
			);
			if (workflow.state === 'succeeded') return;
			if (workflow.state === 'failed' || workflow.state === 'cancelled') {
				throw new Error(workflow.error || $t('Document processing failed'));
			}
			await new Promise((resolveDelay) => window.setTimeout(resolveDelay, 500));
		}
	}

	function upload(event: SubmitEvent, endpoint: string) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		void mutate(async () => {
			const workflow = await apiRequest<{ id: string }>(endpoint, {
				method: 'POST',
				body: new FormData(form)
			});
			await waitForWorkflow(workflow.id);
		}, form);
	}

	function uploadFromUrl(event: SubmitEvent, kind: 'revision' | 'attachment') {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		void mutate(async () => {
			const fields = new FormData(form);
			const source = String(fields.get('url'));
			const workflow = await apiRequest<{ id: string }>(
				`/items/${itemId}/${kind === 'revision' ? 'revisions' : 'attachments'}/remote`,
				{
					method: 'POST',
					body: {
						source,
						...(kind === 'attachment'
							? { graphical_abstract: fields.has('graphical_abstract') }
							: {})
					}
				}
			);
			await waitForWorkflow(workflow.id);
		}, form);
	}

	function deleteFile(file: FileRow) {
		if (!window.confirm($t('Delete this file permanently?'))) return;
		const collection = file.kind === 'revision' ? 'revisions' : 'attachments';
		void mutate(() =>
			apiRequest(`/items/${itemId}/${collection}/${file.id}`, { method: 'DELETE' })
		);
	}

	function downloadFile(file: FileRow) {
		const collection = file.kind === 'revision' ? 'revisions' : 'attachments';
		mutationError = '';
		void apiDownloadGet(`/items/${itemId}/${collection}/${file.id}/content`).catch((error) => {
			mutationError = error instanceof Error ? error.message : $t('Unable to save changes');
		});
	}

	function updateMetadata(item: ItemDetail, metadata: components['schemas']['ItemMetadata-Input']) {
		void mutate(() =>
			apiRequest(`/items/${itemId}`, {
				method: 'PUT',
				body: { expected_version: item.version, metadata }
			})
		);
	}

	function toggleProject(project: OrganizeView['projects'][number]) {
		void mutate(() =>
			apiRequest(`/projects/${project.id}/items/${itemId}`, {
				method: project.assigned ? 'DELETE' : 'PUT'
			})
		);
	}

	function addTag(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const name = String(new FormData(form).get('name') ?? '').trim();
		if (name)
			void mutate(
				() => apiRequest(`/items/${itemId}/tags`, { method: 'POST', body: { name } }),
				form
			);
	}

	function toggleTag(tagId: string, assigned: boolean) {
		void mutate(() =>
			apiRequest(`/items/${itemId}/tags`, {
				method: 'PUT',
				body: {
					add_tag_ids: assigned ? [] : [tagId],
					remove_tag_ids: assigned ? [tagId] : [],
					new_names: []
				}
			})
		);
	}

	function addSuggestedTag(name: string) {
		void mutate(() =>
			apiRequest(`/items/${itemId}/tags`, {
				method: 'PUT',
				body: { add_tag_ids: [], remove_tag_ids: [], new_names: [name] }
			})
		);
	}

	function refreshTagRecommendations() {
		void mutate(async () => {
			const workflow = await apiRequest<{ id: string }>(`/items/${itemId}/tag-recommendations`, {
				method: 'POST'
			});
			await waitForWorkflow(workflow.id);
		});
	}

	function addDiscussion(event: SubmitEvent) {
		event.preventDefault();
		const form = event.currentTarget as HTMLFormElement;
		const body = String(new FormData(form).get('body') ?? '').trim();
		if (body)
			void mutate(
				() => apiRequest(`/items/${itemId}/discussions`, { method: 'POST', body: { body } }),
				form
			);
	}

	function deleteDiscussion(messageId: string) {
		void mutate(() =>
			apiRequest(`/items/${itemId}/discussions/${messageId}`, { method: 'DELETE' })
		);
	}
</script>

<div class="mb-6 flex flex-wrap items-end justify-between gap-4">
	<div class="min-w-0">
		<a
			class="mb-2 inline-flex items-center gap-1 text-xs font-bold tracking-[0.1em] text-primary-700 uppercase no-underline hover:text-primary-800"
			href={resolve('/library')}>{$t('Library')}</a
		>
		<h1 class="max-w-4xl text-balance">
			{#if title}<RichText html={title} />{:else}{$t('Item workspace')}{/if}
		</h1>
		{#if shell.data}<p class="mt-2 text-sm text-surface-700">
				{shell.data.item.authors || $t('Unknown authors')}{#if shell.data.item.publication_title}
					· {shell.data.item.publication_title}{/if}{#if shell.data.item.publication_date}
					· {shell.data.item.publication_date}{/if}
			</p>{/if}
	</div>
	{#if shell.data && session.data?.user}{#key itemId}<ItemActions
				{itemId}
				workspace={shell.data}
				userId={session.data.user.id}
				onchanged={() =>
					Promise.all([
						shell.refetch(),
						workspace.refetch(),
						queryClient.invalidateQueries({ queryKey: ['item-details', itemId] })
					])}
			/>{/key}{/if}
</div>
<nav
	class="mb-6 flex gap-1 overflow-x-auto border-b border-surface-300"
	aria-label={$t('Item workspace')}
>
	{#each Object.entries(labels) as [key, label] (key)}<a
			class="border-b-2 border-transparent px-3 py-2.5 text-sm font-semibold whitespace-nowrap text-surface-700 no-underline transition-colors hover:text-primary-700 aria-[current=page]:border-primary-700 aria-[current=page]:text-primary-700"
			aria-current={section === key ? 'page' : undefined}
			href={resolve(sectionPath(key))}>{$t(label)}</a
		>{/each}
</nav>
{#if mutationError}<p
		class="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-error-700"
		role="alert"
	>
		{mutationError}
	</p>{/if}
{#if workspace.isPending}<div class="grid min-h-52 place-items-center text-surface-600">
		{$t('Loading')}
		{$t(sectionLabel).toLowerCase()}…
	</div>
{:else if workspace.isError}<div class="grid min-h-52 place-items-center text-error-700">
		{$t('Unable to open this Item section.')}
	</div>
{:else if workspace.data}
	{#if section === 'overview'}
		{@const data = workspace.data as WorkspaceView}
		<div class="grid items-start gap-5 lg:grid-cols-[minmax(0,1.5fr)_minmax(17rem,0.5fr)]">
			<div class="stack">
				<section
					class="overflow-hidden rounded-xl border border-surface-300 bg-surface-50 shadow-sm"
				>
					<header class="border-b border-surface-300 px-5 py-4">
						<h2 class="m-0 text-lg">{$t('Abstract')}</h2>
					</header>
					<div class="px-5 py-5 leading-7 text-surface-700">
						{#if details.data?.abstract_html}<RichText html={details.data.abstract_html} />{:else}<p
								class="m-0 text-surface-600"
							>
								{$t('No abstract available.')}
							</p>{/if}
					</div>
				</section>
				<section
					class="overflow-hidden rounded-xl border border-surface-300 bg-surface-50 shadow-sm"
				>
					<header class="flex items-center justify-between border-b border-surface-300 px-5 py-4">
						<h2 class="m-0 text-lg">{$t('Publication details')}</h2>
						{#if data.permissions.edit}<a
								class="text-sm font-semibold text-primary-700 no-underline"
								href={resolve('/(app)/item/[itemId]/[section=itemSection]', {
									itemId,
									section: 'metadata'
								})}>{$t('Edit metadata')}</a
							>{/if}
					</header>
					<dl class="grid gap-4 px-5 py-5 text-sm sm:grid-cols-2">
						<div>
							<dt class="text-surface-600">{$t('Publication')}</dt>
							<dd class="m-0 mt-1">{data.item.publication_title ?? '—'}</dd>
						</div>
						<div>
							<dt class="text-surface-600">{$t('Date')}</dt>
							<dd class="m-0 mt-1">{data.item.publication_date ?? '—'}</dd>
						</div>
						<div>
							<dt class="text-surface-600">DOI</dt>
							<dd class="m-0 mt-1 break-all">{data.item.doi ?? '—'}</dd>
						</div>
						<div>
							<dt class="text-surface-600">{$t('Type')}</dt>
							<dd class="m-0 mt-1">{details.data?.metadata.reference_type ?? '—'}</dd>
						</div>
						<div>
							<dt class="text-surface-600">{$t('Volume / Issue')}</dt>
							<dd class="m-0 mt-1">
								{details.data?.metadata.volume ?? '—'} / {details.data?.metadata.issue ?? '—'}
							</dd>
						</div>
						<div>
							<dt class="text-surface-600">{$t('Pages')}</dt>
							<dd class="m-0 mt-1">{details.data?.metadata.pages ?? '—'}</dd>
						</div>
						<div>
							<dt class="text-surface-600">{$t('Journal abbreviation')}</dt>
							<dd class="m-0 mt-1">{details.data?.metadata.journal_abbreviation ?? '—'}</dd>
						</div>
						<div>
							<dt class="text-surface-600">{$t('Publisher')}</dt>
							<dd class="m-0 mt-1">
								{details.data?.metadata.publisher ??
									'—'}{#if details.data?.metadata.place_published}
									· {details.data.metadata.place_published}{/if}
							</dd>
						</div>
						<div class="sm:col-span-2">
							<dt class="text-surface-600">{$t('Affiliation')}</dt>
							<dd class="m-0 mt-1">{details.data?.metadata.affiliation ?? '—'}</dd>
						</div>
					</dl>
					<div class="bg-surface/55 grid grid-cols-4 border-t border-surface-300">
						<div class="grid gap-0.5 border-r border-surface-300 p-4">
							<strong class="text-2xl tabular-nums">{data.counts.revisions}</strong><span
								class="text-xs text-surface-600">{$t('PDF revisions')}</span
							>
						</div>
						<div class="grid gap-0.5 border-r border-surface-300 p-4">
							<strong class="text-2xl tabular-nums">{data.counts.attachments}</strong><span
								class="text-xs text-surface-600">{$t('Supplements')}</span
							>
						</div>
						<div class="grid gap-0.5 border-r border-surface-300 p-4">
							<strong class="text-2xl tabular-nums">{data.counts.annotations}</strong><span
								class="text-xs text-surface-600">{$t('Annotations')}</span
							>
						</div>
						<div class="grid gap-0.5 p-4">
							<strong class="text-2xl tabular-nums">{data.counts.discussion}</strong><span
								class="text-xs text-surface-600">{$t('Messages')}</span
							>
						</div>
					</div>
				</section>
			</div>
			<aside class="grid content-start gap-5">
				<section class="rounded-xl border border-surface-300 bg-surface-50 p-5 shadow-sm">
					<h2 class="m-0 mb-4 text-lg">{$t('Tags')}</h2>
					<div class="flex flex-wrap gap-2">
						{#each data.tags as tag (tag.id)}<span
								class="rounded-full bg-primary-50 px-2.5 py-1 text-xs font-semibold text-primary-800"
								>{tag.name}</span
							>{:else}<span class="text-sm text-surface-600">{$t('No tags')}</span>{/each}
					</div>
				</section>
				<section class="rounded-xl border border-surface-300 bg-surface-50 p-5 shadow-sm">
					<h2 class="m-0 mb-4 text-lg">{$t('Keywords')}</h2>
					<div class="flex flex-wrap gap-2">
						{#each details.data?.metadata.keywords ?? [] as keyword (keyword)}<span
								class="rounded-full border border-surface-300 bg-surface-200 px-2.5 py-1 text-xs font-semibold"
								>{keyword}</span
							>{:else}<span class="text-sm text-surface-600">{$t('No keywords.')}</span>{/each}
					</div>
				</section>
				<section class="rounded-xl border border-surface-300 bg-surface-50 p-5 shadow-sm">
					<h2 class="m-0 mb-4 text-lg">{$t('External links')}</h2>
					<div class="grid gap-2">
						{#each details.data?.metadata.urls ?? [] as url, index (url)}<a
								class="grid min-w-0 gap-0.5 rounded-lg border border-surface-300 px-3 py-2 text-sm no-underline hover:bg-primary-50"
								href={url}
								target="_blank"
								rel="external noreferrer"
								><strong>{$t('External source')} {index + 1}</strong><span
									class="truncate text-xs text-surface-600">{url}</span
								></a
							>{:else}<span class="text-sm text-surface-600">{$t('No external links.')}</span
							>{/each}
					</div>
				</section>
				<section class="rounded-xl border border-surface-300 bg-surface-50 p-5 shadow-sm">
					<h2 class="m-0 mb-4 text-lg">{$t('Record')}</h2>
					<dl class="grid gap-3 text-sm">
						<div>
							<dt class="text-surface-600">{$t('Owner')}</dt>
							<dd class="m-0">{data.owner.username}</dd>
						</div>
						<div>
							<dt class="text-surface-600">{$t('Permissions')}</dt>
							<dd class="m-0">{data.permissions.edit ? $t('Can edit') : $t('Read only')}</dd>
						</div>
						<div>
							<dt class="text-surface-600">{$t('Citation key')}</dt>
							<dd class="m-0"><code>{details.data?.metadata.bibtex_key ?? '—'}</code></dd>
						</div>
					</dl>
				</section>
			</aside>
		</div>
	{:else if section === 'metadata'}
		{@const item = workspace.data as ItemDetail}
		<section class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<h2>{$t('Metadata')}</h2>
			{#if shell.data?.permissions.edit}{#key `${item.id}:${item.version}`}<ItemMetadataForm
						metadata={item.metadata}
						{busy}
						submitLabel={$t('Save metadata')}
						onsubmit={(metadata) => updateMetadata(item, metadata)}
					/>{/key}{:else}<dl class="grid gap-4 text-sm sm:grid-cols-2">
					<div class="sm:col-span-2">
						<dt class="text-surface-600">{$t('Title')}</dt>
						<dd class="m-0 mt-1"><RichText html={item.title_html} /></dd>
					</div>
					<div>
						<dt class="text-surface-600">{$t('Authors')}</dt>
						<dd class="m-0 mt-1">
							{item.metadata.authors
								.map((author) => [author.first_name, author.last_name].filter(Boolean).join(' '))
								.join('; ') || '—'}
						</dd>
					</div>
					<div>
						<dt class="text-surface-600">{$t('Editors')}</dt>
						<dd class="m-0 mt-1">
							{item.metadata.editors
								.map((editor) => [editor.first_name, editor.last_name].filter(Boolean).join(' '))
								.join('; ') || '—'}
						</dd>
					</div>
					{#each [[$t('Publication'), item.metadata.publication_title], [$t('Publication date'), item.metadata.publication_date], [$t('Reference type'), item.metadata.reference_type], ['DOI', item.metadata.doi], [$t('Volume'), item.metadata.volume], [$t('Issue'), item.metadata.issue], [$t('Pages'), item.metadata.pages], [$t('Publisher'), item.metadata.publisher], [$t('Affiliation'), item.metadata.affiliation], [$t('Citation key'), item.metadata.bibtex_key]] as field (field[0])}<div
						>
							<dt class="text-surface-600">{field[0]}</dt>
							<dd class="m-0 mt-1">{field[1] || '—'}</dd>
						</div>{/each}
					<div class="sm:col-span-2">
						<dt class="text-surface-600">{$t('Keywords')}</dt>
						<dd class="m-0 mt-1">{item.metadata.keywords.join('; ') || '—'}</dd>
					</div>
					<div class="sm:col-span-2">
						<dt class="text-surface-600">{$t('Abstract')}</dt>
						<dd class="m-0 mt-1 whitespace-pre-wrap">
							{#if item.abstract_html}<RichText html={item.abstract_html} />{:else}—{/if}
						</dd>
					</div>
				</dl>{/if}
		</section>
	{:else if section === 'files'}
		{@const data = workspace.data as FilesView}
		<div class="item-layout">
			<section class="list-panel card border border-surface-300 bg-surface-50 p-5 shadow-sm">
				<h2>{$t('Files')}</h2>
				{#each data.files as file (file.id)}<div
						class="item-row grid-cols-[minmax(0,1fr)_auto] items-center"
					>
						<div class="grid gap-1">
							<strong>{file.original_name}</strong><span class="text-surface-600"
								>{$t(domainLabel(file.kind))} · {Math.ceil(file.size / 1024)} KB{file.processing_state
									? ` · ${$t(domainLabel(file.processing_state))}`
									: ''}</span
							>
						</div>
						<div class="toolbar">
							{#if file.kind === 'revision' && file.processing_state === 'ready'}<a
									class="btn preset-tonal-surface font-semibold"
									href={resolve('/(app)/item/[itemId]/pdf/[revisionId]', {
										itemId,
										revisionId: file.id
									})}>{$t('Read')}</a
								>{/if}
							<button
								class="btn preset-tonal-surface font-semibold"
								onclick={() => downloadFile(file)}>{$t('Download')}</button
							>
							{#if shell.data?.permissions.edit}<button
									class="btn preset-tonal-error font-semibold"
									disabled={busy}
									onclick={() => deleteFile(file)}>{$t('Delete')}</button
								>{/if}
						</div>
					</div>{:else}<p class="text-surface-600">{$t('No files.')}</p>{/each}
			</section>
			{#if shell.data?.permissions.edit}<aside class="stack">
					<form
						class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm"
						onsubmit={(event) => upload(event, `/items/${itemId}/revisions`)}
					>
						<h2>{$t('Add PDF revision')}</h2>
						<input
							class="input"
							name="pdf"
							type="file"
							accept="application/pdf,.pdf"
							required
						/><button class="btn preset-tonal-surface font-semibold" disabled={busy}
							>{$t('Upload PDF')}</button
						>
					</form>
					<form
						class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm"
						onsubmit={(event) => uploadFromUrl(event, 'revision')}
					>
						<h2>{$t('Add a PDF from URL')}</h2>
						<input
							class="input"
							name="url"
							type="url"
							value={details.data?.metadata.urls.find((url) =>
								url.toLowerCase().includes('.pdf')
							) ?? ''}
							placeholder="https://example.org/article.pdf"
							required
						/><button class="btn preset-tonal-surface font-semibold" disabled={busy}
							>{$t('Download and add PDF')}</button
						>
					</form>
					<form
						class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm"
						onsubmit={(event) => upload(event, `/items/${itemId}/attachments`)}
					>
						<h2>{$t('Add attachment')}</h2>
						<input class="input" name="attachment" type="file" required />
						<label class="flex items-center gap-2"
							><input name="graphical_abstract" type="checkbox" value="true" />
							{$t('Use as Graphical Abstract')}</label
						>
						<button class="btn preset-tonal-surface font-semibold" disabled={busy}
							>{$t('Upload attachment')}</button
						>
					</form>
					<form
						class="stack card border border-surface-300 bg-surface-50 p-5 shadow-sm"
						onsubmit={(event) => uploadFromUrl(event, 'attachment')}
					>
						<h2>{$t('Add attachment from URL')}</h2>
						<input
							class="input"
							name="url"
							type="url"
							placeholder="https://example.org/supplement.zip"
							required
						/>
						<label class="flex items-center gap-2"
							><input name="graphical_abstract" type="checkbox" value="true" />
							{$t('Use as Graphical Abstract')}</label
						>
						<button class="btn preset-tonal-surface font-semibold" disabled={busy}
							>{$t('Download and add attachment')}</button
						>
					</form>
				</aside>{/if}
		</div>
	{:else if section === 'organize'}
		{@const data = workspace.data as OrganizeView}
		{@const canEdit = data.permissions.edit}
		{@const groups = data.tag_matrix.groups
			.map((group) => ({
				letter: group.letter,
				tags: group.tags.filter((tag) =>
					tag.name.toLocaleLowerCase().includes(tagFilter.toLocaleLowerCase())
				)
			}))
			.filter((group) => group.tags.length)}
		<div class="grid items-start gap-4 xl:grid-cols-[minmax(0,1.75fr)_minmax(19rem,1fr)]">
			<div class="grid gap-4">
				<section class="card border border-surface-300 bg-surface-50 p-5 shadow-sm">
					<div class="mb-4 flex flex-wrap items-start justify-between gap-3">
						<div>
							<h2 class="m-0">{$t('Tag matrix')}</h2>
							<p class="m-0 text-sm text-surface-600">
								{$t('Browse the complete accessible taxonomy.')}
							</p>
						</div>
						<input
							class="compact input border border-surface-300 field-sm"
							bind:value={tagFilter}
							placeholder={$t('Filter Tags')}
						/>
					</div>
					<div class="gap-x-6 sm:columns-2 2xl:columns-3">
						{#each groups as group (group.letter)}
							<div class="mb-4 break-inside-avoid last:mb-0">
								<h3 class="mb-2 text-xs font-bold tracking-[0.12em] text-surface-600 uppercase">
									{group.letter}
								</h3>
								<div class="flex flex-wrap gap-1.5">
									{#each group.tags as tag (tag.id)}
										{@const assigned = data.tag_matrix.assigned_ids.includes(tag.id)}
										<button
											class={`badge cursor-pointer border ${assigned ? 'border-primary-700 preset-tonal-primary' : 'border-surface-300 preset-tonal-surface'}`}
											disabled={busy || !canEdit}
											aria-pressed={assigned}
											onclick={() => toggleTag(tag.id, assigned)}
											>{tag.name}{data.tag_matrix.recommended_ids.includes(tag.id)
												? ' ★'
												: ''}</button
										>
									{/each}
								</div>
							</div>
						{/each}
					</div>
					{#if !groups.length}<p class="m-0 text-sm text-surface-600">{$t('No tags')}</p>{/if}
				</section>
				<section class="card border border-surface-300 bg-surface-50 p-5 shadow-sm">
					<h2 class="m-0 mb-2">{$t('Projects')}</h2>
					<div class="divide-y divide-surface-300">
						{#each data.projects as project (project.id)}
							<div class="flex items-center justify-between gap-3 py-2">
								<div class="flex min-w-0 items-center gap-2">
									<strong class="truncate text-sm font-semibold">{project.name}</strong>
									<span class="badge shrink-0 border border-surface-300 preset-tonal-surface"
										>{$t(domainLabel(project.role))}</span
									>
								</div>
								<button
									class={`btn shrink-0 border font-semibold btn-sm ${project.assigned ? 'border-surface-300 preset-tonal-surface' : 'border-primary-700/30 preset-tonal-primary'}`}
									disabled={busy || !canEdit}
									onclick={() => toggleProject(project)}
									>{project.assigned ? $t('Remove') : $t('Add')}</button
								>
							</div>
						{:else}
							<p class="m-0 text-sm text-surface-600">{$t('No available projects.')}</p>
						{/each}
					</div>
				</section>
			</div>
			<div class="grid gap-4">
				<section class="card border border-surface-300 bg-surface-50 p-5 shadow-sm">
					<h2 class="m-0">{$t('Item Tags')}</h2>
					<p class="mt-1 mb-3 text-sm text-surface-600">
						{$t('Tags currently assigned to this Item.')}
					</p>
					<div class="flex flex-wrap gap-1.5">
						{#each data.tags as tag (tag.id)}
							<button
								class="badge cursor-pointer border border-primary-700/20 preset-tonal-primary"
								disabled={busy || !canEdit}
								onclick={() => toggleTag(tag.id, true)}>{tag.name} ×</button
							>
						{:else}
							<span class="text-sm text-surface-600">{$t('No tags')}</span>
						{/each}
					</div>
					<form class="mt-3 flex items-center gap-2" onsubmit={addTag}>
						<input
							class="input min-w-0 flex-1 border border-surface-300 field-sm"
							name="name"
							placeholder={$t('New tag')}
							required
						/><button
							class="btn shrink-0 border border-surface-300 preset-tonal-surface font-semibold btn-sm"
							disabled={busy || !canEdit}>{$t('Add tag')}</button
						>
					</form>
				</section>
				<section class="card border border-surface-300 bg-surface-50 p-5 shadow-sm">
					<div class="flex items-start justify-between gap-3">
						<h2 class="m-0">{$t('Tag Recommendations')}</h2>
						<button
							class="btn shrink-0 border border-surface-300 preset-tonal-surface font-semibold btn-sm"
							disabled={busy || !canEdit}
							onclick={refreshTagRecommendations}>{$t('Refresh')}</button
						>
					</div>
					<p class="mt-1 mb-3 text-sm text-surface-600">
						{$t('Suggestions derived from metadata and the latest ready PDF.')}
					</p>
					{#if data.tag_matrix.recommendation_error}<p class="text-error-700">
							{data.tag_matrix.recommendation_error}
						</p>{/if}
					<div class="flex flex-wrap gap-1.5">
						{#each data.tag_matrix.suggested_names as name (name)}
							<button
								class="badge cursor-pointer border border-warning-700/30 preset-tonal-warning"
								disabled={busy || !canEdit}
								onclick={() => addSuggestedTag(name)}>+ {name}</button
							>
						{:else}
							<span class="text-sm text-surface-600">{$t('No new Tag suggestions.')}</span>
						{/each}
					</div>
					<div
						class="mt-3 flex items-center gap-2 border-t border-surface-300 pt-3 text-xs text-surface-600"
					>
						{$t('State')}
						<span class="badge border border-surface-300 preset-tonal-surface"
							>{$t(domainLabel(data.tag_matrix.recommendation_state))}</span
						>
					</div>
				</section>
			</div>
		</div>
	{:else if section === 'annotations'}
		<section class="list-panel card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<div class="workspace-header">
				<h2>{$t('Annotations')}</h2>
				{#if annotationRevisions.length > 1}<label
						class="flex items-center gap-2 text-sm text-surface-700"
						>{$t('PDF revision')}<select class="compact input" bind:value={annotationRevision}
							><option value="all">{$t('All revisions')}</option
							>{#each annotationRevisions as revision (revision.id)}<option value={revision.id}
									>{revision.original_name}</option
								>{/each}</select
						></label
					>{/if}
			</div>
			{#if annotationsLoading}<p class="text-surface-600">
					{$t('Loading annotations…')}
				</p>{:else if annotationsError}<p class="text-error-700">
					{$t('Unable to load annotations.')}
				</p>{:else if annotationRevisions.length === 0}<p class="text-surface-600">
					{$t('Add a PDF revision to begin annotating.')}
				</p>{:else}{#each displayedAnnotations as annotation (annotation.id)}<div class="item-row">
						<div class="toolbar justify-between">
							<strong
								>{$t(domainLabel(annotation.kind))} · {$t('page')}
								{annotation.page_index + 1}</strong
							><a
								class="text-sm font-semibold text-primary-700 no-underline"
								href={resolve('/(app)/item/[itemId]/pdf/[revisionId]', {
									itemId,
									revisionId: annotation.revision_id
								})}>{$t('Open')}</a
							>
						</div>
						<span>{annotation.body ?? annotation.selected_text ?? $t('No note text')}</span><span
							class="text-surface-600"
							>{annotation.author_display_name} · {annotation.revision_name} · {annotation.replies
								.length}
							{$t('replies')}</span
						>
					</div>{:else}<p class="text-surface-600">{$t('No annotations.')}</p>{/each}<a
					class="btn preset-filled-primary-700-300 font-semibold"
					href={resolve('/(app)/item/[itemId]/pdf/[revisionId]', {
						itemId,
						revisionId: annotationRevisions[0].id
					})}>{$t('Open annotation workspace')}</a
				>{/if}
		</section>
	{:else}
		{@const messages = workspace.data as Message[]}
		<section class="list-panel card border border-surface-300 bg-surface-50 p-5 shadow-sm">
			<h2>{$t('Discussion')}</h2>
			{#each messages as message (message.id)}<div class="item-row">
					<div class="toolbar justify-between">
						<strong>{message.author_username}</strong
						>{#if message.author_id === session.data?.user?.id || session.data?.user?.role === 'administrator'}<button
								class="btn preset-tonal-error font-semibold"
								disabled={busy}
								onclick={() => deleteDiscussion(message.id)}>{$t('Delete')}</button
							>{/if}
					</div>
					<span>{message.body}</span><span class="text-surface-600"
						>{new Date(message.created_at).toLocaleString()}</span
					>
				</div>{:else}<p class="text-surface-600">{$t('No discussion messages.')}</p>{/each}
			<form class="stack" onsubmit={addDiscussion}>
				<label
					>{$t('Add message')}<textarea class="textarea" name="body" rows="4" required
					></textarea></label
				><button class="btn preset-filled-primary-700-300 font-semibold" disabled={busy}
					>{$t('Post message')}</button
				>
			</form>
		</section>
	{/if}
{/if}
