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

export type SessionView = {
	authenticated: boolean;
	user: null | { id: string; username: string; role: 'administrator' | 'member' };
	locale: string;
};

export type ItemSummary = {
	id: string;
	title_html: string;
	authors: string | null;
	publication_date: string | null;
	publication_title: string | null;
	doi: string | null;
	version: number;
};

export type ProjectSummary = {
	id: string;
	name: string;
	role: string;
	item_count: number;
	state: string;
	visibility: string;
	description: string;
};

export type WorkspaceView = {
	item: ItemSummary;
	permissions: { edit: boolean; delete: boolean };
	counts: { revisions: number; attachments: number; annotations: number; discussion: number };
	tags: Array<{ id: string; name: string }>;
	owner: { id: string; username: string };
	identifiers: Array<{ provider: string; value: string }>;
	latest_revision: null | {
		id: string;
		original_name: string;
		size: number;
		page_count: number | null;
		processing_state: string;
	};
};

export type LibraryView = {
	items: ItemSummary[];
	total: number;
	page: number;
	per_page: number;
};
