// @vitest-environment jsdom
import { QueryClient } from '@tanstack/svelte-query';
import { expect, it, vi } from 'vitest';
import { libraryListQuery } from './queries.js';

it('sends explicit empty exact name parts while omitting blank broad filters', async () => {
	let received: Request | undefined;
	vi.stubGlobal('fetch', async (request: Request) => {
		received = request;
		return new Response(JSON.stringify({ items: [], total: 0, limit: 25, offset: 25 }));
	});
	const client = new QueryClient();
	try {
		await client.fetchQuery(
			libraryListQuery(
				'workspace-1',
				{
					author_last_name: '研究 Council & Co.',
					author_first_name: '',
					publication_title: ' Journal & 特刊 ',
					keyword_exact: 'Graph; theory',
					query: '',
					tag: '',
					has_files: false
				},
				2
			)
		);
		const parameters = new URL(received!.url).searchParams;
		expect(parameters.get('author_first_name')).toBe('');
		expect(parameters.get('author_last_name')).toBe('研究 Council & Co.');
		expect(parameters.get('publication_title')).toBe(' Journal & 特刊 ');
		expect(parameters.get('keyword_exact')).toBe('Graph; theory');
		expect(parameters.get('has_files')).toBe('false');
		expect(parameters.get('offset')).toBe('25');
		expect(parameters.has('query')).toBe(false);
		expect(parameters.has('tag')).toBe(false);
	} finally {
		client.clear();
		vi.unstubAllGlobals();
	}
});
