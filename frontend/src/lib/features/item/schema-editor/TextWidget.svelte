<script lang="ts">
	import {
		getFormContext,
		inputAttributes,
		textareaAttributes,
		type ComponentProps
	} from '@sjsf/form';
	import '@sjsf/basic-theme/extra-widgets/textarea.svelte';
	import PublicationDateField from '../PublicationDateField.svelte';
	let { value = $bindable(), config, handlers }: ComponentProps['textWidget'] = $props();
	const ctx = getFormContext();
	const attributes = $derived(inputAttributes(ctx, config, 'text', handlers, {}));
	const textarea = $derived(textareaAttributes(ctx, config, 'textarea', handlers, {}));
	const publication = $derived(config.path.length === 1 && config.path[0] === 'date_published');
	const multiline = $derived(['description', 'content'].includes(String(config.path.at(-1))));
</script>

{#if publication}
	<div id={attributes.id}>
		<PublicationDateField
			inputAttributes={{
				'aria-invalid': attributes['aria-invalid'],
				'aria-describedby': attributes['aria-describedby']
			}}
			bind:value={() => value ?? '', (next) => (value = next || undefined)}
		/>
	</div>
{:else if multiline}
	<textarea class="textarea min-h-36" {...textarea} bind:value></textarea>
{:else}
	<!-- JSON Schema patterns use different semantics from HTML's UnicodeSets regexes. -->
	<input class="input" {...attributes} pattern={undefined} type="text" bind:value />
{/if}
