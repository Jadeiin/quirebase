import { describe, expect, it } from 'vitest';

import { apiDownloadGet, apiRequest, apiText, downloadFilename } from './client';

describe('apiRequest', () => {
	it('uses the shared API and browser credentials without a CSRF token', async () => {
		let receivedInput: RequestInfo | URL | undefined;
		let receivedInit: RequestInit | undefined;
		const fetcher: typeof fetch = async (input, init) => {
			receivedInput = input;
			receivedInit = init;
			return new Response(JSON.stringify({ ok: true }));
		};

		await apiRequest('/items', { method: 'POST', body: { title: 'Item' } }, fetcher);

		expect(receivedInput).toBe('/api/v1/items');
		const headers = new Headers(receivedInit?.headers);
		expect(receivedInit?.credentials).toBe('same-origin');
		expect(headers.get('Content-Type')).toBe('application/json');
		expect(headers.has('X-CSRF-Token')).toBe(false);
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
		['download', (fetcher: typeof fetch) => apiDownloadGet('/export', fetcher)],
		['text', (fetcher: typeof fetch) => apiText('/citation', fetcher)]
	])('preserves the HTTP status for %s responses', async (_name, request) => {
		const fetcher = (async () =>
			new Response('<h1>Bad gateway</h1>', {
				status: 502,
				statusText: 'Bad Gateway',
				headers: { 'Content-Type': 'text/html' }
			})) as typeof fetch;

		await expect(request(fetcher)).rejects.toMatchObject({
			status: 502,
			detail: 'Bad Gateway',
			message: 'Bad Gateway'
		});
	});
});
