<script lang="ts">
	import { createQuery } from '@tanstack/svelte-query';
	import { onMount } from 'svelte';
	import { apiRequest } from '$lib/api/client';
	import {
		defaultExportPreferences,
		readExportPreferences,
		writeExportPreferences,
		type ExportPreferences
	} from '$lib/export-preferences';
	import { t } from '$lib/i18n';

	let { userId } = $props<{ userId: string }>();
	let preferences = $state<ExportPreferences>(structuredClone(defaultExportPreferences));
	let citationKeyFormula = $state(defaultExportPreferences.citation.citationKeyFormula);
	let citationKeyForceAscii = $state(defaultExportPreferences.citation.citationKeyForceAscii);
	let styleQuery = $state('');
	let ready = $state(false);
	let saved = $state(false);
	let savedTimer: number | undefined;
	const styles = createQuery(() => ({
		queryKey: ['citation-styles', 'preferences', styleQuery],
		queryFn: () =>
			apiRequest<{ styles: Array<{ key: string; name: string }> }>(
				`/citation-styles?query=${encodeURIComponent(styleQuery)}&limit=30&include=${encodeURIComponent(preferences.citation.style)}`
			)
	}));
	const citationPreview = createQuery(() => ({
		queryKey: ['citation-key-preview', citationKeyFormula, citationKeyForceAscii],
		enabled: ready,
		queryFn: async ({ queryKey }) => {
			const formula = String(queryKey[1]);
			const forceAscii = queryKey[2] === true;
			return {
				...(await apiRequest<{ key: string }>(
					`/citation-key-preview?formula=${encodeURIComponent(formula)}&force_ascii=${forceAscii}`
				)),
				formula,
				forceAscii
			};
		}
	}));

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

<section class="panel stack" id="export-preferences">
	<div class="workspace-header">
		<div>
			<p class="eyebrow">{$t('Defaults')}</p>
			<h2>{$t('Export preferences')}</h2>
		</div>
		<button class="button" onclick={reset}>{$t('Reset to defaults')}</button>
	</div>
	<p class="muted">
		{$t('Configure defaults used by Library and Item export actions on this browser.')}
	</p>
	<div class="grid gap-4 xl:grid-cols-2">
		<section class="stack rounded-lg border border-line p-3">
			<h3>{$t('General citation options')}</h3>
			<label
				>{$t('Default citation format')}<select
					class="field"
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
					>{$t('Search Citation Styles')}<input class="field" bind:value={styleQuery} /></label
				><label
					>{$t('Default CSL style')}<select class="field" bind:value={preferences.citation.style}
						>{#each styles.data?.styles ?? [] as style (style.key)}<option value={style.key}
								>{style.name}</option
							>{/each}</select
					></label
				>{/if}
		</section>
		<section class="stack rounded-lg border border-line p-3">
			<h3>{$t('Bibliography file options')}</h3>
			<label
				>{$t('Journal title')}<select class="field" bind:value={preferences.citation.journalMode}
					><option value="full">{$t('Full title')}</option><option value="prefer_abbreviated"
						>{$t('Prefer abbreviation')}</option
					><option value="abbreviated">{$t('Abbreviation only')}</option></select
				></label
			>
			<label
				>{$t('DOI policy')}<select class="field" bind:value={preferences.citation.doiPolicy}
					><option value="include">{$t('Include')}</option><option value="omit">{$t('Omit')}</option
					></select
				></label
			>
			<label
				>{$t('URL policy')}<select class="field" bind:value={preferences.citation.urlPolicy}
					><option value="include">{$t('Include')}</option><option value="omit">{$t('Omit')}</option
					><option value="omit_when_doi">{$t('Omit when DOI exists')}</option></select
				></label
			>
			<label
				>{$t('Excluded fields')}<input
					class="field"
					bind:value={preferences.citation.excludedFields}
					placeholder="abstract, keywords"
				/></label
			>
			<label
				>{$t('Output sorting')}<select class="field" bind:value={preferences.citation.sortBy}
					><option value="input">{$t('Library order')}</option><option value="citation_key"
						>{$t('Citation key')}</option
					><option value="author">{$t('Author')}</option><option value="year">{$t('Year')}</option
					><option value="title">{$t('Title')}</option></select
				></label
			>
		</section>
		<section class="stack rounded-lg border border-line p-3">
			<h3>{$t('BibTeX and BibLaTeX options')}</h3>
			<label
				>{$t('Encoding')}<select class="field" bind:value={preferences.citation.encoding}
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
		<section class="stack rounded-lg border border-line p-3">
			<h3>{$t('Citation Key options')}</h3>
			<label
				>{$t('Citation Key formula')}<input class="field" bind:value={citationKeyFormula} /></label
			>
			<label class="flex gap-2"
				><input type="checkbox" bind:checked={citationKeyForceAscii} />
				{$t('Use ASCII characters only')}</label
			>
			<label
				>{$t('Preview Citation Key')}<output class="field block"
					>{citationPreview.data?.key ?? '—'}</output
				></label
			>
			{#if citationPreview.isError}<p class="text-danger">
					{$t('Invalid Citation Key formula')}
				</p>{/if}
		</section>
		<section class="stack rounded-lg border border-line p-3 xl:col-span-2">
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
	<p class="muted mb-0 text-sm">
		{$t('Preferences are automatically saved to your browser.')}
		{#if saved}<span class="text-success">{$t('Saved')}</span>{/if}
	</p>
</section>
