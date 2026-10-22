<script lang="ts">
	import SearchSelect from '#lib/design/SearchSelect.svelte';
	import { createInfiniteQuery, createQuery } from '@tanstack/svelte-query';
	import { onMount, untrack } from 'svelte';
	import { Listbox, Tabs, useListCollection } from '@skeletonlabs/skeleton-svelte';
	import Panel from '#lib/design/Panel.svelte';
	import LoadingState from '#lib/design/LoadingState.svelte';
	import QueryError from '#lib/design/QueryError.svelte';
	import { apiErrorMessage } from '#lib/api/errors.js';
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import {
		citationKeyPreviewQuery,
		exportCitationStyleQuery,
		exportCitationStylesQuery
	} from '#lib/features/account/queries.js';
	import {
		defaultExportPreferences,
		bibliographyFormats,
		readExportPreferences,
		writeExportPreferences,
		type ExportPreferences
	} from '#lib/export-preferences.js';
	import { t } from '#lib/i18n.js';
	import Button from '#lib/design/Button.svelte';
	import { workspaceOptionsQuery } from '#lib/workspaces/queries.js';

	let { userId }: { userId: string } = $props();
	let preferences = $state<ExportPreferences>(structuredClone(defaultExportPreferences));
	let citationKeyFormula = $state(defaultExportPreferences.citation.citationKeyFormula);
	let citationKeyForceAscii = $state(defaultExportPreferences.citation.citationKeyForceAscii);
	let styleQuery = $state('');
	let workspaceId = $state('');
	let loadedWorkspaceId = $state<string | null>(null);
	let ready = $state(false);
	let saved = $state(false);
	let savedTimer: number | undefined;
	type PreferenceSection = 'csl' | 'bibtex' | 'bibliography' | 'documents';
	let section = $state<PreferenceSection>('csl');
	function formatSection(format: string): PreferenceSection {
		return format === 'csl' ? 'csl' : format === 'bibtex' ? 'bibtex' : 'bibliography';
	}
	const workspaces = createInfiniteQuery(() => workspaceOptionsQuery());
	const styles = createInfiniteQuery(() => ({
		...exportCitationStylesQuery(workspaceId, styleQuery),
		enabled: ready && Boolean(workspaceId) && loadedWorkspaceId === workspaceId
	}));
	const selection = createQuery(() => ({
		...exportCitationStyleQuery(workspaceId, preferences.citation.style),
		enabled:
			ready &&
			Boolean(workspaceId && preferences.citation.style) &&
			loadedWorkspaceId === workspaceId
	}));
	const styleOptions = $derived.by(() => {
		if (!workspaceId || loadedWorkspaceId !== workspaceId) return [];
		const catalog = styles.data;
		const selected = selection.data;
		const candidates =
			catalog?.workspaceId === workspaceId && catalog.query === styleQuery ? catalog.items : [];
		const selectedItems =
			selected?.workspaceId === workspaceId && selected.key === preferences.citation.style
				? selected.items
				: [];
		return [
			...new Map([...candidates, ...selectedItems].map((style) => [style.key, style])).values()
		];
	});
	const stylesUnavailable = $derived(
		styles.isError ||
			styles.fetchStatus === 'paused' ||
			selection.isError ||
			selection.fetchStatus === 'paused'
	);
	const styleCollection = $derived(
		useListCollection({
			items: styleOptions,
			itemToValue: (style) => style.key,
			itemToString: (style) => style.name
		})
	);
	const citationPreview = createQuery(() =>
		citationKeyPreviewQuery(citationKeyFormula, citationKeyForceAscii, ready)
	);

	onMount(() => {
		preferences = readExportPreferences(userId);
		citationKeyFormula = preferences.citation.citationKeyFormula;
		citationKeyForceAscii = preferences.citation.citationKeyForceAscii;
		section = formatSection(preferences.citation.format);
		ready = true;
		return () => {
			if (savedTimer) window.clearTimeout(savedTimer);
		};
	});

	$effect(() => {
		if (!ready) return;
		const selectedWorkspaceId = workspaceId;
		const selectedUserId = userId;
		untrack(() => {
			preferences.citation.style = readExportPreferences(
				selectedUserId,
				selectedWorkspaceId
			).citation.style;
		});
		loadedWorkspaceId = selectedWorkspaceId;
	});

	$effect(() => {
		if (!ready || loadedWorkspaceId !== workspaceId) return;
		if (!writeExportPreferences(userId, $state.snapshot(preferences), workspaceId)) return;
		saved = true;
		if (savedTimer) window.clearTimeout(savedTimer);
		savedTimer = window.setTimeout(() => (saved = false), 1200);
	});

	$effect(() => {
		const selected = selection.data;
		if (
			!ready ||
			!workspaceId ||
			loadedWorkspaceId !== workspaceId ||
			!selection.isSuccess ||
			selection.fetchStatus !== 'idle' ||
			!selected ||
			selected.workspaceId !== workspaceId ||
			selected.key !== preferences.citation.style ||
			selected.items.length
		)
			return;
		// Only the exact selected-key read can establish that a saved style disappeared.
		preferences.citation.style = 'apa';
	});

	$effect(() => {
		const preview = citationPreview.data;
		if (
			!ready ||
			!preview ||
			preview.formula !== citationKeyFormula ||
			preview.forceAscii !== citationKeyForceAscii
		)
			return;
		preferences.citation.citationKeyFormula = preview.formula;
		preferences.citation.citationKeyForceAscii = preview.forceAscii;
	});

	function reset() {
		section = 'csl';
		preferences = structuredClone(defaultExportPreferences);
		citationKeyFormula = defaultExportPreferences.citation.citationKeyFormula;
		citationKeyForceAscii = defaultExportPreferences.citation.citationKeyForceAscii;
	}
</script>

{#snippet bibliographyOptions()}
	<section
		class="grid grid-cols-1 content-start gap-3 rounded-lg border border-surface-300-700 p-3"
	>
		<h3>{$t('Bibliography file options')}</h3>
		<label
			>{$t('Output sorting')}<select class="select" bind:value={preferences.citation.sortBy}
				><option value="input">{$t('Library order')}</option><option value="citation_key"
					>{$t('Citation key')}</option
				><option value="year">{$t('Year')}</option><option value="title">{$t('Title')}</option
				><option value="author">{$t('Author')}</option></select
			></label
		>
		<label
			>{$t('DOI policy')}<select class="select" bind:value={preferences.citation.doiPolicy}
				><option value="include">{$t('Include')}</option><option value="omit">{$t('Omit')}</option
				></select
			></label
		>
		<label
			>{$t('URL policy')}<select class="select" bind:value={preferences.citation.urlPolicy}
				><option value="include">{$t('Include')}</option><option value="omit">{$t('Omit')}</option
				><option value="omit_when_doi">{$t('Omit when a DOI exists')}</option></select
			></label
		>
		<p class="text-sm text-surface-600-400">
			{$t('DOI and URL preferences apply to BibTeX, RIS and CSL exports.')}
		</p>
		{#if section === 'bibtex' || preferences.citation.format === 'csl-json'}
			<label
				>{$t('Excluded fields')}<input
					class="input"
					bind:value={preferences.citation.excludedFields}
					maxlength="8192"
				/></label
			>
			<p class="text-sm text-surface-600-400">
				{$t(
					'Use comma-separated native field names. Field exclusions apply only to BibTeX and CSL-JSON; identity and type fields are required.'
				)}
			</p>
		{/if}
	</section>
{/snippet}

<Panel id="export-preferences" class="grid grid-cols-1 gap-3">
	<SectionHeader>
		<div>
			<p class="mb-1 text-sm font-medium text-primary-700-300">{$t('Defaults')}</p>
			<h2>{$t('Export preferences')}</h2>
		</div>
		{#snippet actions()}<Button onclick={reset}>{$t('Reset to defaults')}</Button>{/snippet}
	</SectionHeader>
	<p class="text-surface-600-400">
		{$t('Default export settings for this browser.')}
	</p>
	<div class="flex flex-wrap items-end gap-4">
		<label class="grid min-w-56 grid-cols-1 gap-1"
			>{$t('Default citation format')}<select
				class="select"
				bind:value={preferences.citation.format}
				onchange={(event) => (section = formatSection(event.currentTarget.value))}
			>
				{#each bibliographyFormats as choice (choice.value)}
					<option value={choice.value}>{$t(choice.label)}</option>
				{/each}
			</select></label
		>
		<label class="flex items-center gap-2 pb-2"
			><input
				type="checkbox"
				bind:checked={preferences.citation.includeAbstract}
				disabled={preferences.citation.format === 'commonmeta'}
			/>{$t('Include abstract')}</label
		>
	</div>
	{#if preferences.citation.format === 'commonmeta'}<p class="text-surface-600-400">
			{$t('Commonmeta exports include all metadata, including abstracts and identifiers.')}
		</p>{/if}
	<Tabs
		value={section}
		onValueChange={(details) => (section = (details.value ?? 'csl') as PreferenceSection)}
	>
		<Tabs.List class="max-w-full overflow-x-auto" aria-label={$t('Export preference sections')}>
			<Tabs.Indicator class="bg-primary-700-300" />
			{#each [['csl', 'CSL'], ['bibtex', 'BibTeX'], ['bibliography', $t('Bibliography file options')], ['documents', $t('Document downloads')]] as [value, label] (value)}
				<Tabs.Trigger {value} class="whitespace-nowrap data-selected:text-primary-800-200"
					>{label}</Tabs.Trigger
				>
			{/each}
		</Tabs.List>
		<Tabs.Content value="csl">
			{#if workspaces.isError}<QueryError
					message={apiErrorMessage(workspaces.error, $t('Unable to load workspaces.'))}
					busy={workspaces.isFetching}
					onRetry={() => void workspaces.refetch()}
				/>{/if}
			{#if workspaceId && stylesUnavailable}<QueryError
					message={apiErrorMessage(
						styles.error ?? selection.error,
						$t('Unable to load Citation Styles.')
					)}
					busy={styles.isFetching || selection.isFetching}
					onRetry={() => void Promise.all([styles.refetch(), selection.refetch()])}
				/>{/if}
			{#if workspaceId && !stylesUnavailable && (styles.isPending || selection.isPending)}<LoadingState
					label={$t('Loading Citation Styles…')}
				/>{/if}
			<div class="grid grid-cols-1 items-start gap-3 md:grid-cols-2">
				<SearchSelect
					label={$t('Workspace for citation style')}
					bind:value={workspaceId}
					loading={workspaces.isPending}
					emptyLabel={$t('Choose a Workspace')}
					options={(workspaces.data ?? []).map((workspace) => ({
						value: workspace.id,
						label: workspace.name
					}))}
				/>
				<label
					>{$t('Search Citation Styles')}<input
						class="input"
						bind:value={styleQuery}
						disabled={!workspaceId}
					/></label
				>
				<Listbox
					class="md:col-span-2"
					collection={styleCollection}
					value={[preferences.citation.style]}
					disabled={!workspaceId || loadedWorkspaceId !== workspaceId}
					onValueChange={(details) => {
						if (details.value[0]) preferences.citation.style = details.value[0];
					}}
				>
					<Listbox.Label>{$t('Default CSL style')}</Listbox.Label>
					<Listbox.Content class="max-h-52 overflow-y-auto">
						{#each styleOptions as style (style.key)}
							<Listbox.Item item={style}>
								<Listbox.ItemText>{style.name}</Listbox.ItemText>
								<Listbox.ItemIndicator aria-hidden="true">✓</Listbox.ItemIndicator>
							</Listbox.Item>
						{/each}
					</Listbox.Content>
				</Listbox>
			</div>
			{#if workspaceId && styles.isSuccess && styles.fetchStatus === 'idle' && styles.data.items.length === 0}
				<p>{$t('No Citation Styles match this search.')}</p>
			{/if}
			{#if workspaceId && styles.hasNextPage}<Button
					disabled={styles.fetchStatus !== 'idle'}
					onclick={() => void styles.fetchNextPage()}>{$t('Load more Citation Styles')}</Button
				>{/if}
			{#if workspaces.hasNextPage}<Button
					disabled={workspaces.isFetchingNextPage}
					onclick={() => void workspaces.fetchNextPage()}>{$t('Load more workspaces')}</Button
				>{/if}
		</Tabs.Content>
		<Tabs.Content value="bibtex">
			<div class="grid grid-cols-1 items-start gap-4 xl:grid-cols-2">
				<div class="grid grid-cols-1 content-start gap-4">
					<label
						>{$t('BibTeX character representation')}<select
							class="select"
							bind:value={preferences.citation.encoding}
							><option value="unicode">{$t('Unicode text')}</option><option value="latex"
								>{$t('LaTeX character commands')}</option
							></select
						></label
					>
					<label class="flex items-center gap-2"
						><input type="checkbox" bind:checked={preferences.citation.preserveCase} />{$t(
							'Preserve BibTeX title case'
						)}</label
					>
					{@render bibliographyOptions()}
				</div>
				<section
					class="grid grid-cols-1 content-start gap-3 rounded-lg border border-surface-300-700 p-3"
				>
					<h3>{$t('Citation Key options')}</h3>
					<label
						>{$t('Citation Key formula')}<input
							class="input"
							bind:value={citationKeyFormula}
						/></label
					>
					<label class="flex gap-2"
						><input type="checkbox" bind:checked={citationKeyForceAscii} />
						{$t('Use ASCII characters only')}</label
					>
					<label
						>{$t('Preview Citation Key')}<output class="input block"
							>{citationPreview.data?.formula === citationKeyFormula &&
							citationPreview.data?.forceAscii === citationKeyForceAscii
								? citationPreview.data.key
								: citationPreview.isError
									? '—'
									: '…'}</output
						></label
					>
					{#if citationPreview.isError}<p class="text-error-700-300">
							{$t('Invalid Citation Key formula')}
						</p>{/if}
				</section>
			</div>
		</Tabs.Content>
		<Tabs.Content value="bibliography">{@render bibliographyOptions()}</Tabs.Content>
		<Tabs.Content value="documents"
			><section class="grid grid-cols-1 content-start gap-3">
				<h3>{$t('Document download options')}</h3>
				<label class="flex gap-2"
					><input type="checkbox" bind:checked={preferences.document.includeAnnotations} />
					{$t('Include annotations in PDF downloads')}</label
				>
				<label class="flex gap-2"
					><input type="checkbox" bind:checked={preferences.document.includeSupplements} />
					{$t('Include supplements in PDF downloads')}</label
				>
			</section></Tabs.Content
		>
	</Tabs>
	<p class="mb-0 text-sm text-surface-600-400">
		{$t('Settings are saved automatically in this browser.')}{#if saved}<span
				class="text-success-700-300">{$t('Saved')}</span
			>{/if}
	</p>
</Panel>
