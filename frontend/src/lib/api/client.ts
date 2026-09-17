export class ApiError extends Error {
	constructor(
		readonly status: number,
		readonly detail: unknown
	) {
		super(typeof detail === 'string' ? detail : `API request failed (${status})`);
	}
}

type ApiRequestOptions = Omit<RequestInit, 'body'> & {
	body?: unknown;
};

async function responseError(response: Response): Promise<ApiError> {
	const payload = await response.json().catch(() => ({ detail: response.statusText }));
	return new ApiError(response.status, payload.detail ?? payload);
}

export async function apiRequest<T>(
	path: string,
	options: ApiRequestOptions = {},
	fetcher: typeof fetch = fetch
): Promise<T> {
	const headers = new Headers(options.headers);
	let body: BodyInit | undefined;
	if (options.body instanceof FormData || options.body instanceof Blob) {
		body = options.body;
	} else if (options.body !== undefined) {
		headers.set('Content-Type', 'application/json');
		body = JSON.stringify(options.body);
	}
	headers.set('Accept', 'application/json');

	const response = await fetcher(`/api/v1${path}`, {
		...options,
		body,
		credentials: 'same-origin',
		headers
	});
	if (!response.ok) {
		throw await responseError(response);
	}
	if (response.status === 204) return undefined as T;
	return (await response.json()) as T;
}

export function downloadFilename(disposition: string): string {
	const extended = disposition.match(/(?:^|;)\s*filename\*\s*=\s*(?:"([^"]*)"|([^;]*))/i);
	const encoded = (extended?.[1] ?? extended?.[2] ?? '').trim();
	const parts = encoded.match(/^([^']*)'[^']*'(.*)$/);
	if (parts && /^(?:utf-8|us-ascii)$/i.test(parts[1])) {
		try {
			return decodeURIComponent(parts[2]);
		} catch {
			// Fall through to the plain filename when the extended value is malformed.
		}
	}
	const plain = disposition.match(/(?:^|;)\s*filename\s*=\s*(?:"([^"]*)"|([^;]*))/i);
	return (plain?.[1] ?? plain?.[2] ?? '').trim() || 'quirebase-export';
}

export async function apiDownload(path: string, body: unknown): Promise<void> {
	const response = await fetch(`/api/v1${path}`, {
		method: 'POST',
		body: JSON.stringify(body),
		credentials: 'same-origin',
		headers: { Accept: '*/*', 'Content-Type': 'application/json' }
	});
	if (!response.ok) {
		throw await responseError(response);
	}
	const filename = downloadFilename(response.headers.get('Content-Disposition') ?? '');
	const url = URL.createObjectURL(await response.blob());
	const link = document.createElement('a');
	link.href = url;
	link.download = filename;
	link.click();
	URL.revokeObjectURL(url);
}

export async function apiDownloadGet(path: string, fetcher: typeof fetch = fetch): Promise<void> {
	const response = await fetcher(`/api/v1${path}`, {
		credentials: 'same-origin',
		headers: { Accept: '*/*' }
	});
	if (!response.ok) {
		throw await responseError(response);
	}
	const filename = downloadFilename(response.headers.get('Content-Disposition') ?? '');
	const url = URL.createObjectURL(await response.blob());
	const link = document.createElement('a');
	link.href = url;
	link.download = filename;
	link.click();
	URL.revokeObjectURL(url);
}

export async function apiText(path: string, fetcher: typeof fetch = fetch): Promise<string> {
	const response = await fetcher(`/api/v1${path}`, {
		credentials: 'same-origin',
		headers: { Accept: 'text/plain' }
	});
	if (!response.ok) {
		throw await responseError(response);
	}
	return response.text();
}

import type { components } from '$lib/api/schema';

export type SessionView = components['schemas']['SessionView'];
export type ItemSummary = components['schemas']['ItemSearchView'];
export type ProjectSummary = components['schemas']['ProjectSummaryView'];
export type WorkspaceView = components['schemas']['ItemWorkspaceView'];
export type LibraryView = components['schemas']['LibrarySearchView'];
