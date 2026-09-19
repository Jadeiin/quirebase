import { describe, expect, it } from 'vitest';
import {
	svelteExtractor,
	typescriptExtractor,
	type SvelteExtractedMessage
} from '$lib/i18n-extractor';

function extract(source: string): SvelteExtractedMessage[] {
	const messages: SvelteExtractedMessage[] = [];
	svelteExtractor.extract(
		'Example.svelte',
		source,
		(message) => messages.push(message),
		{} as never
	);
	return messages;
}

describe('Svelte gettext extraction', () => {
	it('extracts direct translations and marked dynamic messages', () => {
		const messages = extract(`
			<script lang="ts">
				const label = msg('Library');
				const failure = translate('Workflow failed');
			</script>
			<h1>{$t('Dashboard')}</h1>
			<a>{$t(label)}</a>
		`);

		expect(
			messages
				.map(({ id, message }) => ({ id, message }))
				.toSorted((left, right) => left.id.localeCompare(right.id))
		).toEqual([
			{ id: 'Dashboard', message: 'Dashboard' },
			{ id: 'Library', message: 'Library' },
			{ id: 'Workflow failed', message: 'Workflow failed' }
		]);
	});

	it('extracts translator comments from message descriptors', () => {
		const messages = extract(`
			<script lang="ts">
				const label = msg({ message: 'Owner', comment: 'Project member role.' });
			</script>
		`);

		expect(messages.map(({ id, message, comment }) => ({ id, message, comment }))).toEqual([
			{ id: 'Owner', message: 'Owner', comment: 'Project member role.' }
		]);
	});

	it('fails extraction when msg receives a dynamic value', () => {
		expect(() => extract(`<script>const label = msg(value);</script>`)).toThrow(
			'Example.svelte:1: msg() requires a string literal'
		);
	});

	it('propagates Svelte parse failures', () => {
		expect(() => extract(`<h1>{$t('Broken')}</h1`)).toThrow();
	});
});

describe('TypeScript gettext extraction', () => {
	it('extracts marked domain labels and literal translations', () => {
		const messages: SvelteExtractedMessage[] = [];
		typescriptExtractor.extract(
			'domain-labels.ts',
			`const labels = { ready: msg('Ready'), attachment: msg('Attachment') };
			const failure = translate('Workflow failed');
			const dynamic = translate(job.failureMessage);`,
			(message) => messages.push(message),
			{} as never
		);

		expect(messages.map(({ id }) => id)).toEqual(['Ready', 'Attachment', 'Workflow failed']);
	});

	it('extracts translator comments from TypeScript message descriptors', () => {
		const messages: SvelteExtractedMessage[] = [];
		typescriptExtractor.extract(
			'domain-labels.ts',
			`const labels = { owner: msg({ message: 'Owner', comment: 'Project member role.' }) };`,
			(message) => messages.push(message),
			{} as never
		);

		expect(messages.map(({ id, message, comment }) => ({ id, message, comment }))).toEqual([
			{ id: 'Owner', message: 'Owner', comment: 'Project member role.' }
		]);
	});

	it('fails extraction when a TypeScript msg call receives a dynamic value', () => {
		expect(() =>
			typescriptExtractor.extract(
				'domain-labels.ts',
				`const label = msg(value);`,
				() => undefined,
				{} as never
			)
		).toThrow('domain-labels.ts:1: msg() requires a string literal');
	});
});
