<script lang="ts">
	import type { components } from '$lib/api/schema';
	import SectionHeader from '$lib/design/SectionHeader.svelte';
	import { msg, t, type MessageKey } from '$lib/i18n';
	import Button from '$lib/design/Button.svelte';

	type Metadata = components['schemas']['ItemMetadata-Input'];
	type ContributorRow = {
		key: number;
		first_name: string;
		last_name: string;
		is_corresponding: boolean;
	};
	type IdentifierRow = { key: number; provider: string; value: string };
	type CustomFieldRow = { key: number; name: string; value: string };
	type Draft = Omit<
		Metadata,
		'keywords' | 'urls' | 'authors' | 'editors' | 'identifiers' | 'custom_fields'
	> & {
		keywords_text: string;
		urls_text: string;
		authors: ContributorRow[];
		editors: ContributorRow[];
		identifiers: IdentifierRow[];
		custom_fields: CustomFieldRow[];
	};

	let {
		metadata,
		busy = false,
		submitLabel,
		onsubmit
	} = $props<{
		metadata: Metadata;
		busy?: boolean;
		submitLabel: string;
		onsubmit: (metadata: Metadata) => void;
	}>();
	let nextKey = 1;
	// The parent keys this component by Item identity; edits intentionally start from this snapshot.
	// svelte-ignore state_referenced_locally
	let draft = $state<Draft>(createDraft(metadata));
	const contributorGroups = $derived([
		{ label: msg('Authors'), rows: draft.authors },
		{ label: msg('Editors'), rows: draft.editors }
	] satisfies Array<{ label: MessageKey; rows: ContributorRow[] }>);

	function rowKey() {
		return nextKey++;
	}

	function createDraft(value: Metadata): Draft {
		return {
			title: value.title,
			abstract: value.abstract ?? '',
			publication_date: value.publication_date ?? '',
			publication_title: value.publication_title ?? '',
			reference_type: value.reference_type ?? '',
			volume: value.volume ?? '',
			issue: value.issue ?? '',
			pages: value.pages ?? '',
			affiliation: value.affiliation ?? '',
			publisher: value.publisher ?? '',
			place_published: value.place_published ?? '',
			journal_abbreviation: value.journal_abbreviation ?? '',
			bibtex_key: value.bibtex_key ?? '',
			bibtex_type: value.bibtex_type ?? '',
			doi: value.doi ?? '',
			keywords_text: value.keywords.join('; '),
			urls_text: value.urls.join('\n'),
			authors: value.authors.map((row) => ({
				key: rowKey(),
				first_name: row.first_name ?? '',
				last_name: row.last_name,
				is_corresponding: row.is_corresponding ?? false
			})),
			editors: value.editors.map((row) => ({
				key: rowKey(),
				first_name: row.first_name ?? '',
				last_name: row.last_name,
				is_corresponding: row.is_corresponding ?? false
			})),
			identifiers: value.identifiers.map((row) => ({
				key: rowKey(),
				provider: row.provider,
				value: row.value
			})),
			custom_fields: value.custom_fields.map((row) => ({
				key: rowKey(),
				name: row.name,
				value: typeof row.value === 'string' ? row.value : JSON.stringify(row.value)
			}))
		};
	}

	function nullable(value: string) {
		return value.trim() || null;
	}

	function customValue(value: string): unknown {
		const trimmed = value.trim();
		try {
			return JSON.parse(trimmed);
		} catch {
			return trimmed;
		}
	}

	function submit(event: SubmitEvent) {
		event.preventDefault();
		onsubmit({
			title: draft.title.trim(),
			abstract: nullable(draft.abstract ?? ''),
			keywords: draft.keywords_text
				.split(';')
				.map((value) => value.trim())
				.filter(Boolean),
			publication_date: nullable(draft.publication_date ?? ''),
			publication_title: nullable(draft.publication_title ?? ''),
			reference_type: nullable(draft.reference_type ?? ''),
			volume: nullable(draft.volume ?? ''),
			issue: nullable(draft.issue ?? ''),
			pages: nullable(draft.pages ?? ''),
			affiliation: nullable(draft.affiliation ?? ''),
			publisher: nullable(draft.publisher ?? ''),
			place_published: nullable(draft.place_published ?? ''),
			journal_abbreviation: nullable(draft.journal_abbreviation ?? ''),
			bibtex_key: nullable(draft.bibtex_key ?? ''),
			bibtex_type: nullable(draft.bibtex_type ?? ''),
			doi: nullable(draft.doi ?? ''),
			urls: draft.urls_text
				.split('\n')
				.map((value) => value.trim())
				.filter(Boolean),
			authors: draft.authors
				.filter((row) => row.last_name.trim())
				.map(({ first_name, last_name, is_corresponding }) => ({
					first_name: nullable(first_name),
					last_name: last_name.trim(),
					is_corresponding
				})),
			editors: draft.editors
				.filter((row) => row.last_name.trim())
				.map(({ first_name, last_name, is_corresponding }) => ({
					first_name: nullable(first_name),
					last_name: last_name.trim(),
					is_corresponding
				})),
			identifiers: draft.identifiers
				.filter((row) => row.provider.trim() && row.value.trim())
				.map(({ provider, value }) => ({ provider: provider.trim(), value: value.trim() })),
			custom_fields: draft.custom_fields
				.filter((row) => row.name.trim())
				.map(({ name, value }) => ({ name: name.trim(), value: customValue(value) }))
		});
	}
</script>

<form class="grid grid-cols-1 gap-3" onsubmit={submit}>
	<div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
		<label class="lg:col-span-2"
			>{$t('Title')}<input class="input" bind:value={draft.title} required /></label
		>
		<label
			>{$t('Reference type')}<input
				class="input"
				bind:value={draft.reference_type}
				placeholder="journalArticle"
			/></label
		>
		<label
			>{$t('Publication date')}<input
				class="input"
				bind:value={draft.publication_date}
				placeholder="2026-09-16"
			/></label
		>
		<label class="lg:col-span-2"
			>{$t('Publication title')}<input class="input" bind:value={draft.publication_title} /></label
		>
		<label
			>{$t('Journal abbreviation')}<input
				class="input"
				bind:value={draft.journal_abbreviation}
			/></label
		>
		<label>{$t('DOI')}<input class="input" bind:value={draft.doi} /></label>
		<label>{$t('Volume')}<input class="input" bind:value={draft.volume} /></label>
		<label>{$t('Issue')}<input class="input" bind:value={draft.issue} /></label>
		<label>{$t('Pages')}<input class="input" bind:value={draft.pages} /></label>
		<label>{$t('Affiliation')}<input class="input" bind:value={draft.affiliation} /></label>
		<label>{$t('Publisher')}<input class="input" bind:value={draft.publisher} /></label>
		<label>{$t('Place published')}<input class="input" bind:value={draft.place_published} /></label>
		<label>{$t('Citation key')}<input class="input" bind:value={draft.bibtex_key} /></label>
		<label>{$t('BibTeX type')}<input class="input" bind:value={draft.bibtex_type} /></label>
		<label class="lg:col-span-2"
			>{$t('Keywords')}<input
				class="input"
				bind:value={draft.keywords_text}
				placeholder={$t('Separate Keywords with semicolons')}
			/></label
		>
		<label class="lg:col-span-2"
			>{$t('URLs')}<textarea class="textarea min-h-24" bind:value={draft.urls_text}
			></textarea></label
		>
		<label class="lg:col-span-2"
			>{$t('Abstract')}<textarea class="textarea min-h-36" bind:value={draft.abstract}
			></textarea></label
		>
	</div>

	{#each contributorGroups as group (group.label)}
		<section class="rounded-lg border border-surface-300-700 p-3">
			<SectionHeader spacing="compact">
				<h3>{$t(group.label)}</h3>
				{#snippet actions()}
					<Button
						type="button"
						onclick={() =>
							group.rows.push({
								key: rowKey(),
								first_name: '',
								last_name: '',
								is_corresponding: false
							})}>{$t('Add contributor')}</Button
					>
				{/snippet}
			</SectionHeader>
			{#each group.rows as row (row.key)}
				<div
					class="grid grid-cols-1 gap-2 border-t border-surface-300-700 py-3 first:border-0 sm:grid-cols-[1fr_1fr_auto_auto] sm:items-end"
				>
					<label>{$t('First name')}<input class="input" bind:value={row.first_name} /></label>
					<label
						>{$t('Last name or organization')}<input
							class="input"
							bind:value={row.last_name}
						/></label
					>
					<label class="flex items-center gap-2 pb-2"
						><input type="checkbox" bind:checked={row.is_corresponding} />
						{$t('Corresponding')}</label
					>
					<Button type="button" onclick={() => group.rows.splice(group.rows.indexOf(row), 1)}
						>{$t('Remove')}</Button
					>
				</div>
			{:else}<p class="text-surface-600-400">{$t('No contributors.')}</p>{/each}
		</section>
	{/each}

	<section class="rounded-lg border border-surface-300-700 p-3">
		<SectionHeader spacing="compact">
			<h3>{$t('Upstream identifiers')}</h3>
			{#snippet actions()}
				<Button
					type="button"
					onclick={() => draft.identifiers.push({ key: rowKey(), provider: '', value: '' })}
					>{$t('Add identifier')}</Button
				>
			{/snippet}
		</SectionHeader>
		{#each draft.identifiers as row (row.key)}<div
				class="grid grid-cols-1 gap-2 border-t border-surface-300-700 py-3 first:border-0 sm:grid-cols-[1fr_2fr_auto] sm:items-end"
			>
				<label>{$t('Provider')}<input class="input" bind:value={row.provider} /></label><label
					>{$t('Identifier')}<input class="input" bind:value={row.value} /></label
				><Button
					type="button"
					onclick={() => draft.identifiers.splice(draft.identifiers.indexOf(row), 1)}
					>{$t('Remove')}</Button
				>
			</div>{:else}<p class="text-surface-600-400">{$t('No upstream identifiers.')}</p>{/each}
	</section>

	<section class="rounded-lg border border-surface-300-700 p-3">
		<SectionHeader spacing="compact">
			<h3>{$t('Custom fields')}</h3>
			{#snippet actions()}
				<Button
					type="button"
					onclick={() => draft.custom_fields.push({ key: rowKey(), name: '', value: '' })}
					>{$t('Add custom field')}</Button
				>
			{/snippet}
		</SectionHeader>
		{#each draft.custom_fields as row (row.key)}<div
				class="grid grid-cols-1 gap-2 border-t border-surface-300-700 py-3 first:border-0 sm:grid-cols-[1fr_2fr_auto] sm:items-end"
			>
				<label>{$t('Field name')}<input class="input" bind:value={row.name} /></label><label
					>{$t('JSON or text value')}<input class="input" bind:value={row.value} /></label
				><Button
					type="button"
					onclick={() => draft.custom_fields.splice(draft.custom_fields.indexOf(row), 1)}
					>{$t('Remove')}</Button
				>
			</div>{:else}<p class="text-surface-600-400">{$t('No custom fields.')}</p>{/each}
	</section>

	<Button variant="filled" disabled={busy}>{submitLabel}</Button>
</form>
