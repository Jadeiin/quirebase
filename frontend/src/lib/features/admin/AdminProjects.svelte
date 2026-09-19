<script lang="ts">
	import Panel from '$lib/design/Panel.svelte';
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';
	import ItemRow from '$lib/design/ItemRow.svelte';

	let { projects } = $props<{ projects: components['schemas']['AdminProjectItemView'][] }>();
</script>

<Panel class="mt-4">
	<h2>{$t('Projects')}</h2>
	{#each projects as project (project.id)}
		<ItemRow>
			<strong>{project.name}</strong><span>{project.description}</span><span
				class="text-surface-600-400"
				>{$t(domainLabel(project.visibility))} · {$t(domainLabel(project.state))} ·
				{$t('{count, plural, one {# member} other {# members}}', {
					count: project.member_count
				})} · {$t('{count, plural, one {# Item} other {# Items}}', {
					count: project.item_count
				})} · {project.creator.username}</span
			>
		</ItemRow>
	{:else}
		<p class="text-surface-600-400">{$t('No projects.')}</p>
	{/each}
</Panel>
