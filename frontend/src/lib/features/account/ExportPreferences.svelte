<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { onMount } from 'svelte';
	import Panel from '$lib/design/Panel.svelte';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
	import {
		citationKeyPreviewQuery,
		exportCitationStylesQuery
	} from '$lib/features/account/queries';
	import {
		defaultExportPreferences,
		readExportPreferences,
		writeExportPreferences,
		type ExportPreferences
	} from '$lib/export-preferences';
	import { t } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';

	let { userId } = $props<{ userId: string }>();
	let preferences = $state<ExportPreferences>(structuredClone(defaultExportPreferences));
	let citationKeyFormula = $state(defaultExportPreferences.citation.citationKeyFormula);
	let citationKeyForceAscii = $state(defaultExportPreferences.citation.citationKeyForceAscii);
	let styleQuery = $state('');
	let ready = $state(false);
	let saved = $state(false);
	let savedTimer: number | undefined;
	const styles = createQuery(() =>
		exportCitationStylesQuery(styleQuery, preferences.citation.style)
	);
	const citationPreview = createQuery(() =>
		citationKeyPreviewQuery(citationKeyFormula, citationKeyForceAscii, ready)
	);

	onMount(() => {
		preferences = readExportPreferences(userId);
		citationKeyFormula = preferences.citation.citationKeyFormula;
		citationKeyForceAscii = preferences.citation.citationKeyForceAscii;
		ready = true;
	});

	$effect(() => {
		if (!ready) return;
		if (!writeExportPreferences(userId, $state.snapshot(preferences))) return;
		saved = true;
		if (savedTimer) window.clearTimeout(savedTimer);
		savedTimer = window.setTimeout(() => (saved = false), 1200);
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
		preferences = structuredClone(defaultExportPreferences);
		citationKeyFormula = defaultExportPreferences.citation.citationKeyFormula;
		citationKeyForceAscii = defaultExportPreferences.citation.citationKeyForceAscii;
	}
</script>

<Panel id="export-preferences" class="grid grid-cols-1 gap-3">
	<SectionHeader>
		<div>
			<p class="mb-1 text-sm font-medium text-primary-700-300">{$t('Defaults')}</p>
			<h2>{$t('Export preferences')}</h2>
		</div>
		{#snippet actions()}
			<Button onclick={reset}>{$t('Reset to defaults')}</Button>
		{/snippet}
	</SectionHeader>
	<p class="text-surface-600-400">
		{$t('Configure defaults used by Library and Item export actions on this browser.')}
	</p>
	<div class="grid grid-cols-1 gap-4 xl:grid-cols-2">
		<section class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3">
			<h3>{$t('General citation options')}</h3>
			<label
				>{$t('Default citation format')}<select
					class="select"
					bind:value={preferences.citation.format}
					><option value="csl">CSL citation</option><option value="bibtex">BibTeX</option><option
						value="biblatex">BibLaTeX</option
					><option value="ris">RIS</option><option value="endnote">EndNote</option></select
				></label
			>
			<label class="flex gap-2"
				><input type="checkbox" bind:checked={preferences.citation.includeAbstract} />
				{$t('Include abstract')}</label
			>
			{#if preferences.citation.format === 'csl'}<label
					>{$t('Search Citation Styles')}<input class="input" bind:value={styleQuery} /></label
				><label
					>{$t('Default CSL style')}<select class="select" bind:value={preferences.citation.style}
						>{#each styles.data?.styles ?? [] as style (style.key)}<option value={style.key}
								>{style.name}</option
							>{/each}</select
					></label
				>{/if}
		</section>
		<section class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3">
			<h3>{$t('Bibliography file options')}</h3>
			<label
				>{$t('Journal title')}<select class="select" bind:value={preferences.citation.journalMode}
					><option value="full">{$t('Full title')}</option><option value="prefer_abbreviated"
						>{$t('Prefer abbreviation')}</option
					><option value="abbreviated">{$t('Abbreviation only')}</option></select
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
					><option value="omit_when_doi">{$t('Omit when DOI exists')}</option></select
				></label
			>
			<label
				>{$t('Excluded fields')}<input
					class="input"
					bind:value={preferences.citation.excludedFields}
					placeholder="abstract, keywords"
				/></label
			>
			<label
				>{$t('Output sorting')}<select class="select" bind:value={preferences.citation.sortBy}
					><option value="input">{$t('Library order')}</option><option value="citation_key"
						>{$t('Citation key')}</option
					><option value="author">{$t('Author')}</option><option value="year">{$t('Year')}</option
					><option value="title">{$t('Title')}</option></select
				></label
			>
		</section>
		<section class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3">
			<h3>{$t('BibTeX and BibLaTeX options')}</h3>
			<label
				>{$t('Encoding')}<select class="select" bind:value={preferences.citation.encoding}
					><option value="unicode">Unicode</option><option value="latex">LaTeX</option></select
				></label
			>
			<label class="flex gap-2"
				><input type="checkbox" bind:checked={preferences.citation.preserveCase} />
				{$t('Preserve bibitem case')}</label
			>
			<label class="flex gap-2"
				><input type="checkbox" bind:checked={preferences.citation.includeIdentifiers} />
				{$t('Include additional identifiers')}</label
			>
			<label class="flex gap-2"
				><input type="checkbox" bind:checked={preferences.citation.includeCustomFields} />
				{$t('Include custom fields')}</label
			>
		</section>
		<section class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3">
			<h3>{$t('Citation Key options')}</h3>
			<label
				>{$t('Citation Key formula')}<input class="input" bind:value={citationKeyFormula} /></label
			>
			<label class="flex gap-2"
				><input type="checkbox" bind:checked={citationKeyForceAscii} />
				{$t('Use ASCII characters only')}</label
			>
			<label
				>{$t('Preview Citation Key')}<output class="input block"
					>{citationPreview.data?.key ?? '—'}</output
				></label
			>
			{#if citationPreview.isError}<p class="text-error-700-300">
					{$t('Invalid Citation Key formula')}
				</p>{/if}
		</section>
		<section
			class="grid grid-cols-1 gap-3 rounded-lg border border-surface-300-700 p-3 xl:col-span-2"
		>
			<h3>{$t('Document download options')}</h3>
			<label class="flex gap-2"
				><input type="checkbox" bind:checked={preferences.document.includeAnnotations} />
				{$t('Include annotations in PDF downloads')}</label
			>
			<label class="flex gap-2"
				><input type="checkbox" bind:checked={preferences.document.includeSupplements} />
				{$t('Include supplements in PDF downloads')}</label
			>
		</section>
	</div>
	<p class="mb-0 text-sm text-surface-600-400">
		{$t('Preferences are automatically saved to your browser.')}
		{#if saved}<span class="text-success-700-300">{$t('Saved')}</span>{/if}
	</p>
</Panel>
