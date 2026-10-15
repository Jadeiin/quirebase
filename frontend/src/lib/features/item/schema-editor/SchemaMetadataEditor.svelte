<script lang="ts">
	import type { components } from '#lib/api/schema.js';
	import { isSchemaValueDeepEqual } from '@sjsf/form/core';
	import { tick, untrack } from 'svelte';
	import {
		Content,
		createForm,
		getValueSnapshot,
		setValue,
		setFormContext,
		type Config,
		type Schema,
		type ValidationError,
		getIdByPath,
		updateErrors
	} from '@sjsf/form';
	import { resolver as compatResolver } from '@sjsf/form/resolvers/compat';
	import { createFormMerger } from '@sjsf/form/mergers/modern';
	import { createFormIdBuilder } from '@sjsf/form/id-builders/modern';
	import { createFormValidator } from '@sjsf/cfworker-validator';
	import { theme as skeletonTheme } from '@sjsf/skeleton5-theme';
	import { overrideByRecord, fromFactories } from '@sjsf/form/lib/resolver';
	import { StringEnumValueMapperBuilder } from '@sjsf/form/options.svelte';
	import '@sjsf/form/fields/extra/enum-include';
	import '@sjsf/form/fields/extra/multi-enum-include';
	import '@sjsf/form/fields/extra-widgets/textarea';
	import '@sjsf/skeleton5-theme/extra-widgets/multi-select.svelte';
	import SchemaFormLayout from '#lib/design/SchemaFormLayout.svelte';
	import Button from '#lib/design/Button.svelte';
	import Notice from '#lib/design/Notice.svelte';
	import { t, translate, activeLocale } from '#lib/i18n.js';
	import type { Metadata } from '../metadata-draft.js';
	import PropertyField from './PropertyField.svelte';
	import WorkFields from './WorkFields.svelte';
	import TextWidget from './TextWidget.svelte';
	import MultiSelectWidget from './MultiSelectWidget.svelte';
	import { isRequiredOnlyUnion, workSchemas, workValidator } from './schema.js';
	import { editorTranslation, enumLabels } from './labels.js';

	let {
		metadata,
		schema,
		citationKey,
		busy,
		submitLabel,
		onsubmit,
		ondirty,
		serverErrors = []
	} = $props<{
		metadata: Metadata;
		schema: Record<string, unknown>;
		citationKey: string;
		busy: boolean;
		submitLabel: string;
		onsubmit: (metadata: Metadata, citationKey: string) => void;
		ondirty?: (dirty: boolean) => void;
		serverErrors?: components['schemas']['ErrorField'][];
	}>();
	// svelte-ignore state_referenced_locally
	const schemas = workSchemas(schema);
	const validate = workValidator(schemas.original);
	let errors = $state<readonly ValidationError[]>([]);
	let raw = $state('');
	let rawOpen = $state(false);
	let rawEdited = $state(false);
	let error = $state('');
	let revision = $state(0);
	let element = $state<HTMLFormElement>();
	// svelte-ignore state_referenced_locally
	let key = $state(citationKey);
	// svelte-ignore state_referenced_locally
	const initial = structuredClone($state.snapshot(metadata));
	// svelte-ignore state_referenced_locally
	const initialKey = citationKey;
	const form = createForm<Metadata>({
		schema: schemas.rendering,
		theme: overrideByRecord(skeletonTheme, {
			textWidget: TextWidget,
			checkboxesWidget: MultiSelectWidget,
			objectPropertyField: PropertyField,
			layout: SchemaFormLayout
		}),
		get translation() {
			void $activeLocale;
			return editorTranslation();
		},
		resolver: (ctx) => {
			const resolve = compatResolver(ctx);
			return (config) => (isRequiredOnlyUnion(config.schema) ? 'objectField' : resolve(config));
		},
		merger: (options) =>
			createFormMerger({
				...options,
				arrayMinItems: { populate: 'never' },
				emptyObjectFields: 'skipEmptyDefaults',
				constAsDefaults: 'never'
			}),
		idBuilder: createFormIdBuilder,
		validator: () => {
			const renderer = createFormValidator<Metadata>();
			return {
				...renderer,
				validateFormValue: (_schema: Schema, value: unknown) => {
					const issues = validate(value);
					return issues.length
						? { value: value as Metadata, errors: issues }
						: { value: value as Metadata };
				},
				validateFieldValue: (config: Config, value: unknown) => {
					// Isolated field validators cannot resolve the official local refs.
					if (value === undefined && !config.required) return [];
					return renderer.isValid(config.schema, schemas.rendering, value as never)
						? []
						: [translate('Check this value against the metadata standard.')];
				}
			};
		},
		initialValue: initial,
		get disabled() {
			return busy;
		},
		uiSchema: {
			'ui:components': { objectField: WorkFields },
			date_published: { 'ui:options': { hideTitle: true } },
			container: { 'ui:options': { hideTitle: true } },
			contributors: { 'ui:options': { hideTitle: true } },
			identifiers: { 'ui:options': { hideTitle: true } },
			funding_references: { 'ui:options': { hideTitle: true } },
			subjects: { 'ui:options': { hideTitle: true } }
		},
		extraUiOptions: fromFactories({
			description: () => '',
			enumNames: (config: Config) => {
				void $activeLocale;
				return enumLabels(config.schema);
			},
			enumValueMapperBuilder: () => () => new StringEnumValueMapperBuilder()
		}),
		onSubmit: (value) => {
			if (busy) return;
			if (rawEdited) {
				error = $t('Apply JSON changes before saving.');
				return;
			}
			if (!value.title?.trim()) {
				error = $t('Enter an Item title.');
				return;
			}
			if (!element?.reportValidity()) return;
			errors = [];
			error = '';
			onsubmit(value, key);
		},
		onSubmitError: (result) => {
			errors = result.errors;
			void focusError(result.errors[0]);
		},
		onSubmissionFailure: () => {
			error = $t('Unable to validate metadata.');
		}
	});
	setFormContext(form);
	$effect(() => {
		if (!serverErrors.length || busy) return;
		const mapped = serverErrors.map((issue: components['schemas']['ErrorField']) => {
			const path = [...issue.path];
			if (path[0] === 'body') path.shift();
			if (path[0] === 'metadata') path.shift();
			return { path, message: issue.message };
		});
		untrack(() => {
			errors = mapped;
			updateErrors(form, mapped);
			void focusError(mapped[0]);
		});
	});
	$effect(() => {
		ondirty?.(
			rawEdited || key !== initialKey || !isSchemaValueDeepEqual(getValueSnapshot(form), initial)
		);
	});
	function submit(event: SubmitEvent) {
		event.preventDefault();
		if (busy) return;
		if (rawEdited) {
			error = $t('Apply JSON changes before saving.');
			return;
		}
		error = '';
		form.submit(event);
	}
	async function focusError(issue: ValidationError | undefined) {
		if (!issue || !element) return;
		await tick();
		const id = getIdByPath(form, issue.path);
		const container =
			issue.path[0] === 'citation_key'
				? element.querySelector<HTMLElement>('[name="citation_key"]')
				: element.querySelector<HTMLElement>(`[id="${id}"]`);
		const target = container?.matches('input, select, textarea')
			? container
			: container?.querySelector<HTMLElement>('input, select, textarea');
		if (!target) return;
		let parent = target.parentElement;
		while (parent && parent !== element) {
			if (parent instanceof HTMLDetailsElement) parent.open = true;
			parent = parent.parentElement;
		}
		target.focus();
	}
	function editJson() {
		raw = JSON.stringify(getValueSnapshot(form), null, 2);
		rawOpen = true;
		rawEdited = false;
	}
	function applyJson() {
		try {
			const parsed: unknown = JSON.parse(raw);
			if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error();
			const issues = validate(parsed);
			if (issues.length) {
				errors = issues;
				error = $t('Invalid metadata JSON.');
				return;
			}
			setValue(form, parsed as Metadata);
			revision += 1;
			updateErrors(form, []);
			errors = [];
			error = '';
			rawOpen = false;
			rawEdited = false;
		} catch {
			error = $t('Invalid metadata JSON.');
		}
	}
</script>

<form
	class="grid min-w-0 grid-cols-1 gap-4 [&_select:not([multiple])]:h-8"
	bind:this={element}
	onsubmit={submit}
	novalidate
>
	<fieldset
		class="m-0 grid min-w-0 grid-cols-1 gap-4 border-0 p-0 [&>button]:justify-self-start"
		disabled={busy}
	>
		{#key revision}<Content />{/key}
		<label class="max-w-md"
			>{$t('Citation key')}<input
				class="input"
				name="citation_key"
				maxlength="128"
				bind:value={key}
			/></label
		>
		<Button type="button" onclick={editJson}>{$t('Edit standard metadata JSON')}</Button>
		{#if rawOpen}
			<label
				>{$t('Metadata')}<textarea
					class="textarea min-h-80 font-mono"
					bind:value={raw}
					oninput={() => (rawEdited = true)}></textarea></label
			>
			<Button type="button" onclick={applyJson}>{$t('Apply JSON')}</Button>
		{/if}
		{#if error}<Notice variant="error">{error}</Notice>{/if}
		{#if errors.length}<Notice as="div" variant="error"
				><p>{$t('Please check the metadata fields.')}</p>
				<ul class="m-0 list-none p-0">
					{#each errors as issue, index (index)}<li>
							<button class="text-left underline" type="button" onclick={() => focusError(issue)}
								>{issue.path.map(String).join(' › ')}: {issue.message}</button
							>
						</li>{/each}
				</ul></Notice
			>{/if}
		<Button type="submit" variant="filled" disabled={busy}>{submitLabel}</Button>
	</fieldset>
</form>
