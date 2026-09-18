import { describe, expect, it } from 'vitest';

import { ApiError, apiDownloadGet, apiRequest, apiText, downloadFilename } from './client';

describe('apiRequest', () => {
	it('uses the shared API and browser credentials without a CSRF token', async () => {
		let receivedInput: RequestInfo | URL | undefined;
		let receivedInit: RequestInit | undefined;
		const fetcher: typeof fetch = async (input, init) => {
			receivedInput = input;
			receivedInit = init;
			return new Response(JSON.stringify({ ok: true }));
		};

		await apiRequest(
			'POST',
			'/items',
			{
				body: {
					title: 'Item',
					keywords: [],
					urls: [],
					authors: [],
					editors: [],
					identifiers: [],
					custom_fields: []
				}
			},
			fetcher
		);

		expect(receivedInput).toBe('/api/v1/items');
		const headers = new Headers(receivedInit?.headers);
		expect(receivedInit?.credentials).toBe('same-origin');
		expect(headers.get('Content-Type')).toBe('application/json');
		expect(headers.has('X-CSRF-Token')).toBe(false);
	});

	it('expands typed path and query parameters', async () => {
		let receivedInput: RequestInfo | URL | undefined;
		const fetcher: typeof fetch = async (input) => {
			receivedInput = input;
			return new Response(JSON.stringify([]));
		};

		await apiRequest(
			'GET',
			'/items/{item_id}/annotations',
			{
				params: {
					path: { item_id: 'item/with slash' },
					query: { revision_id: 'revision-1', project_id: 'project-1' }
				}
			},
			fetcher
		);

		expect(receivedInput).toBe(
			'/api/v1/items/item%2Fwith%20slash/annotations?revision_id=revision-1&project_id=project-1'
		);
	});

	it('keeps method, path, parameters, body, and response tied to OpenAPI at compile time', () => {
		function openApiCompileChecks() {
			// @ts-expect-error Unknown paths are rejected.
			void apiRequest('GET', '/unknown');
			// @ts-expect-error Existing paths reject unsupported methods.
			void apiRequest('PATCH', '/session');
			// @ts-expect-error Path parameters are required and use their OpenAPI names.
			void apiRequest('GET', '/projects/{project_id}', { params: { path: { id: 'wrong' } } });
			// @ts-expect-error Request bodies are checked against the selected operation.
			void apiRequest('POST', '/session', { body: { username: 'reader' } });
		}
		void openApiCompileChecks;
		expect(true).toBe(true);
	});
});

describe('downloadFilename', () => {
	it('decodes an RFC 5987 UTF-8 filename before the fallback', () => {
		expect(
			downloadFilename(
				`attachment; filename="fallback.bib"; filename*=utf-8''%E6%96%87%E7%8C%AE.bib`
			)
		).toBe('文献.bib');
	});

	it('falls back to filename and then the export default', () => {
		expect(downloadFilename('attachment; filename="records.zip"')).toBe('records.zip');
		expect(downloadFilename('attachment')).toBe('quirebase-export');
	});
});

describe('non-JSON API errors', () => {
	it.each([
		[
			'download',
			(fetcher: typeof fetch) =>
				apiDownloadGet(
					'/items/{item_id}/attachments/{attachment_id}/content',
					{ params: { path: { item_id: 'item-1', attachment_id: 'attachment-1' } } },
					fetcher
				)
		],
		[
			'text',
			(fetcher: typeof fetch) =>
				apiText(
					'/items/{item_id}/citation/content',
					{ params: { path: { item_id: 'item-1' } } },
					fetcher
				)
		]
	])('preserves the HTTP status for %s responses', async (_name, request) => {
		const fetcher = (async () =>
			new Response('<h1>Bad gateway</h1>', {
				status: 502,
				statusText: 'Bad Gateway',
				headers: { 'Content-Type': 'text/html' }
			})) as typeof fetch;

		await expect(request(fetcher)).rejects.toMatchObject({
			status: 502,
			code: 'request_failed',
			message: 'Bad Gateway'
		});
	});
});

describe('structured API errors', () => {
	it('preserves the code, field errors, and metadata', async () => {
		const fetcher = (async () =>
			new Response(
				JSON.stringify({
					code: 'validation_failed',
					message: 'request validation failed',
					fields: [{ path: ['body', 'title'], code: 'missing', message: 'Field required' }],
					meta: { request_id: 'request-1' }
				}),
				{ status: 422, headers: { 'Content-Type': 'application/json' } }
			)) as typeof fetch;

		let error: ApiError | undefined;
		try {
			await apiRequest(
				'POST',
				'/items',
				{
					body: {
						title: 'Item',
						keywords: [],
						urls: [],
						authors: [],
						editors: [],
						identifiers: [],
						custom_fields: []
					}
				},
				fetcher
			);
		} catch (reason) {
			error = reason as ApiError;
		}

		expect(error).toMatchObject({ status: 422, code: 'validation_failed' });
		expect(error?.fields).toEqual([
			{ path: ['body', 'title'], code: 'missing', message: 'Field required' }
		]);
		expect(error?.meta).toEqual({ request_id: 'request-1' });
	});
});
