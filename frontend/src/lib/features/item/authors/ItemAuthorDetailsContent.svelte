<script lang="ts">
	import { resolve } from '$app/paths';
	import { ph, t } from 'lingui-for-svelte/macro';
	import Button from '#lib/design/Button.svelte';
	import ExternalLink from '#lib/design/ExternalLink.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import { activeLocale } from '#lib/locale.js';
	import MetadataLinks from '../MetadataLinks.svelte';
	import AffiliationName from '../AffiliationName.svelte';
	import { metadataValueLabel } from '../metadata-labels.js';
	import type { ItemAuthorCredit } from '../metadata-links.js';

	let { author }: { author: ItemAuthorCredit } = $props();
	const roles = $derived.by(() => {
		void $activeLocale;
		return author.roles.map(metadataValueLabel).join('; ');
	});
</script>

<div class="flex flex-col gap-5 text-sm">
	<dl class="m-0 grid grid-cols-1 gap-4">
		{#if author.affiliations.length}<div>
				<dt class="text-xs font-semibold text-surface-600-400">{$t`Affiliations on this work`}</dt>
				<dd class="m-0 mt-2">
					<ul class="m-0 list-none space-y-3 p-0">
						{#each author.affiliations as affiliation, index (index)}<li
								class="min-w-0 leading-relaxed wrap-anywhere"
							>
								<p class="m-0"><AffiliationName {affiliation} /></p>
								{#if affiliation.identifier.label}<div class="mt-1 text-xs">
										<MetadataLinks links={[affiliation.identifier]} />
									</div>{/if}
								{#if affiliation.nameRorFilterHref}<Button
										as="a"
										size="sm"
										variant="tonal"
										class="mt-2 max-w-full text-left whitespace-normal"
										href={resolve(affiliation.nameRorFilterHref)}
										aria-label={$t`Filter Library by this name and ROR: ${ph({ institution: affiliation.name || affiliation.identifier.label })}`}
										><Icon
											name="search"
											size={15}
										/>{$t`Filter Library by this name and ROR`}</Button
									>{/if}
							</li>{/each}
					</ul>
				</dd>
			</div>{/if}
		<div>
			<dt class="text-xs font-semibold text-surface-600-400">{$t`Roles`}</dt>
			<dd class="m-0 mt-2">{roles}</dd>
		</div>
		{#if author.orcidHref}<div>
				<dt class="text-xs font-semibold text-surface-600-400">{$t`ORCID`}</dt>
				<dd class="m-0 mt-2">
					<ExternalLink href={author.orcidHref} icon="orcid"
						>{author.orcidHref.replace('https://', '')}</ExternalLink
					>
				</dd>
			</div>{/if}
		{#if author.rorHref}<div>
				<dt class="text-xs font-semibold text-surface-600-400">{$t`ROR`}</dt>
				<dd class="m-0 mt-2">
					<div class="mb-1">
						<AffiliationName
							affiliation={{
								name: author.label,
								identifier: { label: author.rorHref },
								rorFilterHref: author.rorFilterHref
							}}
						/>
					</div>
					<ExternalLink href={author.rorHref} icon="ror"
						>{author.rorHref.replace('https://', '')}</ExternalLink
					>
					{#if author.nameRorFilterHref}<Button
							as="a"
							size="sm"
							class="mt-2 max-w-full text-left whitespace-normal"
							href={resolve(author.nameRorFilterHref)}
							aria-label={$t`Filter Library by this name and ROR: ${ph({ institution: author.label })}`}
							><Icon name="search" size={15} />{$t`Filter Library by this name and ROR`}</Button
						>{/if}
				</dd>
			</div>{/if}
	</dl>
	<div
		role="group"
		aria-label={$t`Library filters`}
		class="flex flex-col items-start gap-2 border-t border-surface-300-700 pt-4"
	>
		{#if author.orcidFilterHref}<Button
				as="a"
				size="sm"
				variant="primary"
				href={resolve(author.orcidFilterHref)}
				><Icon name="search" size={15} />{$t`Filter Library by this ORCID`}</Button
			>{/if}
		<Button
			as="a"
			size="sm"
			variant={author.orcidFilterHref ? 'tonal' : 'primary'}
			href={resolve(author.href)}
			><Icon name="search" size={15} />{$t`Filter Library by this name`}</Button
		>
	</div>
</div>
