<script lang="ts">
	import SectionHeader from '#lib/design/SectionHeader.svelte';
	import { msg, t, type MessageKey } from '#lib/i18n.js';
	import Button from '#lib/design/Button.svelte';
	import PublicationDateField from './PublicationDateField.svelte';
	import { referenceTypeLabels } from './reference-types.js';

	import IdentifierRows from './IdentifierRows.svelte';
	import {
		createMetadataDraft,
		metadataFromDraft,
		newContributor,
		type Metadata,
		type ContributorRow
	} from './metadata-draft.js';
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
	let draft = $state(createMetadataDraft(metadata, rowKey));
	let formError = $state('');
	const contributorGroups = $derived([
		{ label: msg('Authors'), rows: draft.authors },
		{ label: msg('Editors'), rows: draft.editors }
	] satisfies Array<{ label: MessageKey; rows: ContributorRow[] }>);

	function rowKey() {
		return nextKey++;
	}

	function submit(event: SubmitEvent) {
		event.preventDefault();
		formError = '';
		let value: Metadata;
		try {
			value = metadataFromDraft(draft);
		} catch {
			formError = $t('Custom field JSON is invalid.');
			return;
		}
		onsubmit(value);
	}
</script>

<form class="grid grid-cols-1 gap-3" onsubmit={submit}>
	<div class="grid grid-cols-1 gap-3 lg:grid-cols-2">
		<label class="lg:col-span-2"
			>{$t('Title')}<input class="input" bind:value={draft.title} required /></label
		>
		<label
			>{$t('Reference type')}<select class="select" bind:value={draft.reference_type}>
				{#each Object.entries(referenceTypeLabels) as [value, label] (value)}
					<option {value}>{$t(label)}</option>
				{/each}
			</select></label
		>
		<PublicationDateField bind:value={draft.publication_date} />
		<label class="lg:col-span-2"
			>{$t('Publication title')}<input class="input" bind:value={draft.publication_title} /></label
		>
		<label
			>{$t('Journal abbreviation')}<input
				class="input"
				bind:value={draft.journal_abbreviation}
			/></label
		>
		<label>{$t('Volume')}<input class="input" bind:value={draft.volume} /></label>
		<label>{$t('Issue')}<input class="input" bind:value={draft.issue} /></label>
		<label>{$t('Pages')}<input class="input" bind:value={draft.pages} /></label>
		<label>{$t('Publisher')}<input class="input" bind:value={draft.publisher} /></label>
		<label>{$t('Place published')}<input class="input" bind:value={draft.place_published} /></label>
		<label
			>{$t('Citation key')}<input
				class="input"
				maxlength="128"
				bind:value={draft.citation_key}
			/></label
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
					<Button type="button" onclick={() => group.rows.push(newContributor(rowKey()))}
						>{$t('Add contributor')}</Button
					>
				{/snippet}
			</SectionHeader>
			{#each group.rows as row (row.key)}
				<div class="grid grid-cols-1 gap-3 border-t border-surface-300-700 py-3 first:border-0">
					<div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
						<label>{$t('Display name')}<input class="input" bind:value={row.display_name} /></label>
						<label
							>{$t('Contributor type')}<select class="select" bind:value={row.kind}>
								<option value="unknown">{$t('Unknown')}</option><option value="person"
									>{$t('Person')}</option
								><option value="organization">{$t('Organization')}</option>
							</select></label
						>
						<label>{$t('First name')}<input class="input" bind:value={row.given_name} /></label>
						<label
							>{$t('Last name or organization')}<input
								class="input"
								bind:value={row.family_name}
							/></label
						>
						<label>{$t('Name suffix')}<input class="input" bind:value={row.suffix} /></label>
						{#if group.label === msg('Authors')}
							<label
								>{$t('Corresponding')}<select
									class="select"
									aria-label={$t('Corresponding')}
									bind:value={row.is_corresponding}
									><option value={null}>{$t('Unknown')}</option><option value={true}
										>{$t('Yes')}</option
									><option value={false}>{$t('No')}</option></select
								></label
							>
						{/if}
					</div>
					<details>
						<summary>{$t('Contributor identifiers')}</summary>
						<IdentifierRows bind:rows={row.identifiers} {rowKey} />
					</details>
					<details>
						<summary>{$t('Affiliations')}</summary>
						<div class="grid grid-cols-1 gap-3 py-2">
							{#each row.affiliations ?? [] as affiliation (affiliation.key)}
								<div class="grid grid-cols-1 gap-2 rounded-lg border border-surface-300-700 p-3">
									<label
										>{$t('Affiliation')}<input class="input" bind:value={affiliation.name} /></label
									>
									<label
										>{$t('Country code')}<input
											class="input"
											bind:value={affiliation.country_code}
										/></label
									>
									<label
										>{$t('Original affiliation name')}<input
											class="input"
											bind:value={affiliation.raw_name}
										/></label
									>
									<IdentifierRows bind:rows={affiliation.identifiers} {rowKey} />
									<Button
										type="button"
										onclick={() =>
											row.affiliations?.splice(row.affiliations.indexOf(affiliation), 1)}
										>{$t('Remove')}</Button
									>
								</div>
							{/each}
							<div>
								<Button
									type="button"
									onclick={() =>
										(row.affiliations ??= []).push({ key: rowKey(), name: '', identifiers: [] })}
									>{$t('Add affiliation')}</Button
								>
							</div>
						</div>
					</details>
					<div>
						<Button type="button" onclick={() => group.rows.splice(group.rows.indexOf(row), 1)}
							>{$t('Remove')}</Button
						>
					</div>
				</div>
			{:else}<p class="text-surface-600-400">{$t('No contributors.')}</p>{/each}
		</section>
	{/each}

	<section class="rounded-lg border border-surface-300-700 p-3">
		<SectionHeader spacing="compact">
			<h3>{$t('Upstream identifiers')}</h3>
		</SectionHeader>
		<IdentifierRows bind:rows={draft.identifiers} {rowKey} />
	</section>

	<section class="rounded-lg border border-surface-300-700 p-3">
		<SectionHeader spacing="compact">
			<h3>{$t('Custom fields')}</h3>
			{#snippet actions()}
				<Button
					type="button"
					onclick={() =>
						draft.custom_fields.push({ key: rowKey(), name: '', value: '', type: 'text' })}
					>{$t('Add custom field')}</Button
				>
			{/snippet}
		</SectionHeader>
		{#each draft.custom_fields as row (row.key)}<div
				class="grid grid-cols-1 gap-2 border-t border-surface-300-700 py-3 first:border-0 sm:grid-cols-[1fr_auto_2fr_auto] sm:items-end"
			>
				<label>{$t('Field name')}<input class="input" bind:value={row.name} /></label><label
					>{$t('Value type')}<select class="select" bind:value={row.type}
						><option value="text">{$t('Text')}</option><option value="json">{$t('JSON')}</option
						></select
					></label
				><label>{$t('Value')}<input class="input" bind:value={row.value} /></label><Button
					type="button"
					onclick={() => draft.custom_fields.splice(draft.custom_fields.indexOf(row), 1)}
					>{$t('Remove')}</Button
				>
			</div>{:else}<p class="text-surface-600-400">{$t('No custom fields.')}</p>{/each}
	</section>

	<section class="rounded-lg border border-surface-300-700 p-3">
		<SectionHeader spacing="compact"
			><h3>{$t('Keywords')}</h3>
			{#snippet actions()}<Button
					type="button"
					onclick={() => draft.keywords.push({ key: rowKey(), value: '' })}
					>{$t('Add keyword')}</Button
				>{/snippet}</SectionHeader
		>
		{#each draft.keywords as row (row.key)}<div class="flex items-center gap-2 py-2">
				<input class="input" aria-label={$t('Keyword')} bind:value={row.value} /><Button
					type="button"
					onclick={() => draft.keywords.splice(draft.keywords.indexOf(row), 1)}
					>{$t('Remove')}</Button
				>
			</div>{/each}
	</section>
	<section class="rounded-lg border border-surface-300-700 p-3">
		<SectionHeader spacing="compact"
			><h3>{$t('URLs')}</h3>
			{#snippet actions()}<Button
					type="button"
					onclick={() =>
						draft.urls.push({ key: rowKey(), url: '', kind: 'other', is_open_access: null })}
					>{$t('Add URL')}</Button
				>{/snippet}</SectionHeader
		>
		{#each draft.urls as row (row.key)}
			<div class="grid grid-cols-1 gap-2 border-t border-surface-300-700 py-3 sm:grid-cols-2">
				<label class="sm:col-span-2"
					>{$t('URL')}<input class="input" type="url" bind:value={row.url} /></label
				>
				<label
					>{$t('Link type')}<select class="select" bind:value={row.kind}
						><option value="other">{$t('Other')}</option><option value="landing_page"
							>{$t('Landing page')}</option
						><option value="full_text">{$t('Full text')}</option></select
					></label
				>
				<label>{$t('Media type')}<input class="input" bind:value={row.media_type} /></label>
				<label>{$t('Version')}<input class="input" bind:value={row.version} /></label>
				<label>{$t('License')}<input class="input" bind:value={row.license} /></label>
				<label
					>{$t('Open access')}<select class="select" bind:value={row.is_open_access}
						><option value={null}>{$t('Unknown')}</option><option value={true}>{$t('Yes')}</option
						><option value={false}>{$t('No')}</option></select
					></label
				>
				<label
					>{$t('Intended application')}<input
						class="input"
						bind:value={row.intended_application}
					/></label
				>
				<div>
					<Button type="button" onclick={() => draft.urls.splice(draft.urls.indexOf(row), 1)}
						>{$t('Remove')}</Button
					>
				</div>
			</div>
		{/each}
	</section>
	{#if formError}<p role="alert" class="text-error-700-300">{formError}</p>{/if}

	<Button variant="filled" disabled={busy}>{submitLabel}</Button>
</form>
