// @vitest-environment jsdom

import { describe, expect, it, vi } from 'vitest';

import {
	apiDownload,
	apiDownloadGet,
	apiRequest,
	apiText,
	DownloadCancelledError,
	downloadFilename,
	onAuthenticationRequired
} from './client';

describe('apiRequest', () => {
	it('uses the shared API and browser credentials without a CSRF token', async () => {
		let received: Request | undefined;
		const fetcher: typeof fetch = async (input) => {
			received = input as Request;
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

		expect(new URL(received!.url).pathname).toBe('/api/v1/items');
		expect(received?.method).toBe('POST');
		expect(received?.headers.get('Content-Type')).toBe('application/json');
		expect(received?.headers.has('X-CSRF-Token')).toBe(false);
	});

	it('expands typed path and query parameters', async () => {
		let received: Request | undefined;
		const fetcher: typeof fetch = async (input) => {
			received = input as Request;
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

		const url = new URL(received!.url);
		expect(url.pathname).toBe('/api/v1/items/item%2Fwith%20slash/annotations');
		expect(url.searchParams.get('revision_id')).toBe('revision-1');
		expect(url.searchParams.get('project_id')).toBe('project-1');
	});

	it('omits empty query values', async () => {
		let received: Request | undefined;
		const fetcher: typeof fetch = async (input) => {
			received = input as Request;
			return new Response(JSON.stringify({ total: 0, page: 1, per_page: 25, items: [] }));
		};

		await apiRequest('GET', '/items', { params: { query: { query: '', author: 'ada' } } }, fetcher);

		expect(new URL(received!.url).search).toBe('?author=ada');
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

describe('GET downloads', () => {
	it('streams the default fetch response into the selected file', async () => {
		const encoder = new TextEncoder();
		const events: string[] = [];
		const write = vi.fn(async (chunk: Uint8Array) => {
			void chunk;
		});
		const close = vi.fn(async () => undefined);
		const createWritable = vi.fn(async () => ({ write, close }));
		const showSaveFilePicker = vi.fn(async () => {
			events.push('picker');
			return { createWritable };
		});
		const fetcher = vi.fn(async (input: RequestInfo | URL) => {
			events.push('fetch');
			expect((input as Request).method).toBe('GET');
			return new Response(
				new ReadableStream({
					start(controller) {
						controller.enqueue(encoder.encode('first'));
						controller.enqueue(encoder.encode('second'));
						controller.close();
					}
				}),
				{ headers: { 'Content-Disposition': 'attachment; filename="paper.pdf"' } }
			);
		}) as typeof fetch;
		vi.stubGlobal('fetch', fetcher);
		vi.stubGlobal('showSaveFilePicker', showSaveFilePicker);

		await apiDownloadGet(
			'/items/{item_id}/attachments/{attachment_id}/content',
			{ params: { path: { item_id: 'item-1', attachment_id: 'attachment-1' } } },
			{ suggestedName: 'paper.pdf' }
		);

		expect(showSaveFilePicker).toHaveBeenCalledWith({ suggestedName: 'paper.pdf' });
		expect(events.slice(0, 2)).toEqual(['picker', 'fetch']);
		expect(write).toHaveBeenNthCalledWith(1, encoder.encode('first'));
		expect(write).toHaveBeenNthCalledWith(2, encoder.encode('second'));
		expect(close).toHaveBeenCalledOnce();
	});

	it('falls back to a Blob download when the save picker lacks user activation', async () => {
		const link = document.createElement('a');
		const click = vi.spyOn(link, 'click').mockImplementation(() => undefined);
		vi.spyOn(document, 'createElement').mockReturnValue(link);
		vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:fallback');
		const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
		const fetcher = vi.fn(
			async () =>
				new Response('content', {
					headers: { 'Content-Disposition': 'attachment; filename="paper.pdf"' }
				})
		) as typeof fetch;
		const showSaveFilePicker = vi.fn(async () => {
			throw new DOMException('blocked', 'SecurityError');
		});
		vi.stubGlobal('fetch', fetcher);
		vi.stubGlobal('showSaveFilePicker', showSaveFilePicker);

		await apiDownloadGet('/items/{item_id}/attachments/{attachment_id}/content', {
			params: { path: { item_id: 'item-1', attachment_id: 'attachment-1' } }
		});

		expect(click).toHaveBeenCalledOnce();
		expect(revokeObjectURL).toHaveBeenCalledWith('blob:fallback');
	});

	it('saves a zero-byte file when a successful response has no body', async () => {
		const link = document.createElement('a');
		const click = vi.spyOn(link, 'click').mockImplementation(() => undefined);
		vi.spyOn(document, 'createElement').mockReturnValue(link);
		const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:empty');
		vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
		const fetcher = vi.fn(
			async () =>
				new Response(null, {
					status: 200,
					headers: {
						'Content-Length': '0',
						'Content-Disposition': 'attachment; filename="empty.txt"'
					}
				})
		) as typeof fetch;
		vi.stubGlobal('fetch', fetcher);

		await apiDownloadGet('/items/{item_id}/attachments/{attachment_id}/content', {
			params: { path: { item_id: 'item-1', attachment_id: 'attachment-1' } }
		});

		expect(createObjectURL).toHaveBeenCalledWith(expect.objectContaining({ size: 0 }));
		expect(link.download).toBe('empty.txt');
		expect(click).toHaveBeenCalledOnce();
	});

	it('waits for the GET response before saving the returned content', async () => {
		const link = document.createElement('a');
		const click = vi.spyOn(link, 'click').mockImplementation(() => undefined);
		vi.spyOn(document, 'createElement').mockReturnValue(link);
		vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:download');
		const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined);
		const fetcher = vi.fn(async (input: RequestInfo | URL) => {
			expect((input as Request).method).toBe('GET');
			return new Response('content', {
				status: 200,
				headers: { 'Content-Disposition': 'attachment; filename="paper.pdf"' }
			});
		}) as typeof fetch;

		await apiDownloadGet(
			'/items/{item_id}/attachments/{attachment_id}/content',
			{ params: { path: { item_id: 'item-1', attachment_id: 'attachment-1' } } },
			fetcher
		);

		expect(fetcher).toHaveBeenCalledOnce();
		expect(link.download).toBe('paper.pdf');
		expect(link.href).toBe('blob:download');
		expect(click).toHaveBeenCalledOnce();
		expect(revokeObjectURL).toHaveBeenCalledWith('blob:download');
	});

	it('preserves structured errors returned by the GET', async () => {
		const fetcher = vi.fn(
			async () =>
				new Response(JSON.stringify({ code: 'document_not_ready', message: 'not ready' }), {
					status: 409,
					headers: { 'Content-Type': 'application/json' }
				})
		) as typeof fetch;

		await expect(
			apiDownloadGet(
				'/items/{item_id}/revisions/{revision_id}/export',
				{ params: { path: { item_id: 'item-1', revision_id: 'revision-1' } } },
				fetcher
			)
		).rejects.toMatchObject({ status: 409, code: 'document_not_ready', message: 'not ready' });
	});
});

describe('POST downloads', () => {
	it('reports save-picker cancellation distinctly from download failures', async () => {
		const fetcher = vi.fn(async (input: RequestInfo | URL) => {
			expect((input as Request).method).toBe('POST');
			return new Response('archive');
		}) as typeof fetch;
		const showSaveFilePicker = vi.fn(async () => {
			throw new DOMException('cancelled', 'AbortError');
		});
		vi.stubGlobal('fetch', fetcher);
		vi.stubGlobal('showSaveFilePicker', showSaveFilePicker);

		await expect(
			apiDownload('/items/documents/archive', {
				body: {
					item_ids: ['item-1'],
					include_annotations: false,
					include_supplements: false,
					timezone: 'UTC'
				}
			})
		).rejects.toBeInstanceOf(DownloadCancelledError);
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
	it('notifies the session owner for authentication failures', async () => {
		let notified = 0;
		const unregister = onAuthenticationRequired(() => {
			notified += 1;
		});
		const fetcher = (async () =>
			new Response(JSON.stringify({ code: 'authentication_required', message: 'expired' }), {
				status: 401,
				headers: { 'Content-Type': 'application/json' }
			})) as typeof fetch;

		await expect(apiRequest('GET', '/items', undefined, fetcher)).rejects.toMatchObject({
			status: 401,
			code: 'authentication_required'
		});
		expect(notified).toBe(1);
		unregister();
	});

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

		await expect(
			apiRequest(
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
			)
		).rejects.toMatchObject({
			status: 422,
			code: 'validation_failed',
			fields: [{ path: ['body', 'title'], code: 'missing', message: 'Field required' }],
			meta: { request_id: 'request-1' }
		});
	});
});
