<script lang="ts">
	import { resolve } from '$app/paths';
	import { t } from 'lingui-for-svelte/macro';
	import Button from '#lib/design/Button.svelte';
	import ExternalLink from '#lib/design/ExternalLink.svelte';
	import Icon from '#lib/design/Icon.svelte';
	import { activeLocale } from '#lib/locale.js';
	import MetadataLinks from '../MetadataLinks.svelte';
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
		<div>
			<dt class="text-xs font-semibold text-surface-600-400">{$t`Affiliations on this work`}</dt>
			<dd class="m-0 mt-2">
				{#if author.affiliations.length}
					<ul class="m-0 list-none space-y-3 p-0">
						{#each author.affiliations as affiliation, index (index)}<li
								class="min-w-0 leading-relaxed wrap-anywhere"
							>
								{#if affiliation.name}<p class="m-0">{affiliation.name}</p>{/if}
								{#if affiliation.identifier.label}<div class="mt-1 text-xs">
										<MetadataLinks links={[affiliation.identifier]} />
									</div>{/if}
							</li>{/each}
					</ul>
				{:else}<p class="m-0 text-surface-700-300">
						{author.organization
							? $t`No affiliation information is provided for this organizational credit.`
							: $t`No affiliation information is provided for this author.`}
					</p>{/if}
			</dd>
		</div>
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
	</dl>
	<div class="border-t border-surface-300-700 pt-4">
		<Button as="a" size="sm" variant="primary" href={resolve(author.href)}
			><Icon name="search" size={15} />{$t`Filter Library by this name`}</Button
		>
	</div>
</div>
