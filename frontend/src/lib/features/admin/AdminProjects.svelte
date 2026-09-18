<script lang="ts">
	import { domainLabel } from '$lib/domain-labels';
	import { t } from '$lib/i18n';
	import type { components } from '$lib/api/schema';

	let { projects } = $props<{ projects: components['schemas']['AdminProjectItemView'][] }>();
</script>

<section class="list-panel card border border-surface-300-700 bg-surface-50-950 p-5 shadow-sm">
	<h2>{$t('Projects')}</h2>
	{#each projects as project (project.id)}
		<div class="item-row">
			<strong>{project.name}</strong><span>{project.description}</span><span
				class="text-surface-600-400"
				>{$t(domainLabel(project.visibility))} · {$t(domainLabel(project.state))} · {project.member_count}
				{$t('members')} · {project.item_count}
				{$t('Items')} · {project.creator.username}</span
			>
		</div>
	{:else}
		<p class="text-surface-600-400">{$t('No projects.')}</p>
	{/each}
</section>
