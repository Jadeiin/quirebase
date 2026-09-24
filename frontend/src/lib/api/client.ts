import createClient, {
	createQuerySerializer,
	mergeHeaders,
	type FetchOptions
} from 'openapi-fetch';
import type { components, paths } from '$lib/api/schema';

type ApiErrorView = components['schemas']['ApiErrorView'];

const authenticationRequiredHandlers = new Set<() => void>();
const workspaceUnavailableHandlers = new Set<(workspaceId: string) => void>();

export function onAuthenticationRequired(handler: () => void): () => void {
	authenticationRequiredHandlers.add(handler);
	return () => authenticationRequiredHandlers.delete(handler);
}

export function onWorkspaceUnavailable(handler: (workspaceId: string) => void): () => void {
	workspaceUnavailableHandlers.add(handler);
	return () => workspaceUnavailableHandlers.delete(handler);
}

export class ApiError extends Error {
	constructor(
		readonly status: number,
		readonly error: ApiErrorView
	) {
		super(error.message);
	}

	get code(): string {
		return this.error.code;
	}

	get fields(): components['schemas']['ErrorField'][] {
		return this.error.fields ?? [];
	}

	get meta(): Record<string, unknown> {
		return this.error.meta ?? {};
	}
}

export class DownloadCancelledError extends Error {
	constructor() {
		super();
		this.name = 'DownloadCancelledError';
	}
}

export function isDownloadCancelled(reason: unknown): reason is DownloadCancelledError {
	return reason instanceof DownloadCancelledError;
}

type HttpMethod = 'get' | 'put' | 'post' | 'delete' | 'patch';
type RequestMethod = Uppercase<HttpMethod>;
type SchemaPath = Extract<keyof paths, `/api/v1${string}`>;
export type ApiPath = SchemaPath extends infer Path
	? Path extends `/api/v1${infer RelativePath}`
		? RelativePath
		: never
	: never;
type FullPath<Path extends ApiPath> = `/api/v1${Path}` & SchemaPath;
type Operation<
	Path extends ApiPath,
	Method extends HttpMethod
> = Method extends keyof paths[FullPath<Path>]
	? Exclude<paths[FullPath<Path>][Method], undefined>
	: never;
type PathsWithMethod<Method extends HttpMethod> = {
	[Path in ApiPath]: [Operation<Path, Method>] extends [never] ? never : Path;
}[ApiPath];

type WorkspaceApiPath = Extract<ApiPath, `/workspaces/{workspace_id}${string}`>;
type WorkspacePathsWithMethod<Method extends HttpMethod> = {
	[Path in WorkspaceApiPath]: [Operation<Path, Method>] extends [never] ? never : Path;
}[WorkspaceApiPath];

type RequiredKeys<Value> = Value extends object
	? { [Key in keyof Value]-?: object extends Pick<Value, Key> ? never : Key }[keyof Value]
	: never;
type OptionsArguments<Options> = [RequiredKeys<Options>] extends [never]
	? [options?: Options, fetcher?: typeof fetch]
	: [options: Options, fetcher?: typeof fetch];

type RequestContent<OperationType> = OperationType extends {
	requestBody: { content: infer Content };
}
	? Content
	: OperationType extends { requestBody?: { content: infer Content } }
		? Content
		: never;
type RequestBody<OperationType> =
	RequestContent<OperationType> extends infer Content
		? Content extends { 'application/json': infer Body }
			? Body
			: Content extends { 'multipart/form-data': unknown }
				? FormData
				: Content extends { 'application/x-www-form-urlencoded': infer Body }
					? Body
					: never
		: never;
type BodyOptions<OperationType> = [RequestBody<OperationType>] extends [never]
	? { body?: never }
	: OperationType extends { requestBody: unknown }
		? { body: RequestBody<OperationType> }
		: { body?: RequestBody<OperationType> };

type SuccessStatus = 200 | 201 | 202 | 203 | 204 | 205 | 206;
type SuccessResponse<OperationType> = OperationType extends { responses: infer Responses }
	? Responses[Extract<keyof Responses, SuccessStatus>]
	: never;
type ResponseData<ResponseType> = ResponseType extends { content: infer Content }
	? Content extends { 'application/json': infer Data }
		? Data
		: Content extends { 'text/plain': infer Data }
			? Data
			: Content[keyof Content]
	: void;

export type ApiRequestOptions<Path extends ApiPath, Method extends HttpMethod> = Omit<
	FetchOptions<Operation<Path, Method>>,
	'body'
> &
	BodyOptions<Operation<Path, Method>>;
export type ApiResponse<Path extends ApiPath, Method extends HttpMethod> = ResponseData<
	SuccessResponse<Operation<Path, Method>>
>;

type RequestParams<Path extends ApiPath, Method extends HttpMethod> =
	ApiRequestOptions<Path, Method> extends { params?: infer Params } ? NonNullable<Params> : object;
type PathParams<Path extends ApiPath, Method extends HttpMethod> =
	RequestParams<Path, Method> extends { path?: infer Params }
		? NonNullable<Params>
		: RequestParams<Path, Method> extends { path: infer Params }
			? Params
			: object;
type WorkspacePathParams<Path extends WorkspaceApiPath, Method extends HttpMethod> = Omit<
	PathParams<Path, Method>,
	'workspace_id'
>;
type WorkspacePathOption<Path extends WorkspaceApiPath, Method extends HttpMethod> =
	RequiredKeys<WorkspacePathParams<Path, Method>> extends never
		? { path?: WorkspacePathParams<Path, Method> }
		: { path: WorkspacePathParams<Path, Method> };
type WorkspaceParams<Path extends WorkspaceApiPath, Method extends HttpMethod> = Omit<
	RequestParams<Path, Method>,
	'path'
> &
	WorkspacePathOption<Path, Method>;
export type WorkspaceApiRequestOptions<
	Path extends WorkspaceApiPath,
	Method extends HttpMethod
> = Omit<ApiRequestOptions<Path, Method>, 'params'> &
	(RequiredKeys<WorkspaceParams<Path, Method>> extends never
		? { params?: WorkspaceParams<Path, Method> }
		: { params: WorkspaceParams<Path, Method> });

const serializeQuery = createQuerySerializer();
const client = createClient<paths>({
	baseUrl: `${typeof location === 'undefined' ? '' : location.origin}/api/v1`,
	credentials: 'same-origin',
	headers: { Accept: 'application/json' },
	querySerializer: (query) =>
		serializeQuery(
			Object.fromEntries(
				Object.entries(query as Record<string, unknown>).filter(([, value]) => value !== '')
			)
		)
});

type ClientCall = (
	path: string,
	options?: Record<string, unknown>
) => Promise<{ data?: unknown; error?: unknown; response: Response }>;

function isApiErrorView(payload: unknown): payload is ApiErrorView {
	return (
		payload !== null && typeof payload === 'object' && 'code' in payload && 'message' in payload
	);
}

function responseError(response: Response, payload: unknown): ApiError {
	const error = new ApiError(
		response.status,
		isApiErrorView(payload)
			? payload
			: {
					code: 'request_failed',
					message: response.statusText || `HTTP ${response.status}`
				}
	);
	if (error.code === 'workspace_context_required') {
		console.error('Workspace scoped request was missing its URL context', {
			status: error.status,
			code: error.code,
			path: response.url
		});
	}
	if (response.status === 404 || error.code === 'workspace_membership_required') {
		const workspaceId = response.url.match(/\/api\/v1\/workspaces\/([^/]+)/)?.[1];
		if (workspaceId) {
			for (const handler of workspaceUnavailableHandlers) handler(decodeURIComponent(workspaceId));
		}
	}
	if (error.status === 401 && error.code === 'authentication_required') {
		for (const handler of authenticationRequiredHandlers) handler();
	}
	return error;
}

function callOptions(options: unknown, fetcher: typeof fetch | undefined): Record<string, unknown> {
	const resolved = (options ?? {}) as Record<string, unknown>;
	return { ...resolved, fetch: fetcher ?? resolved.fetch ?? fetch };
}

export async function apiRequest<
	Method extends RequestMethod,
	Path extends PathsWithMethod<Lowercase<Method> & HttpMethod>
>(
	method: Method,
	path: Path,
	...args: OptionsArguments<ApiRequestOptions<Path, Lowercase<Method> & HttpMethod>>
): Promise<ApiResponse<Path, Lowercase<Method> & HttpMethod>> {
	const call = (client as unknown as Record<string, ClientCall>)[method];
	const { data, error, response } = await call(path, callOptions(args[0], args[1]));
	if (!response.ok) throw responseError(response, error);
	return data as ApiResponse<Path, Lowercase<Method> & HttpMethod>;
}

async function rawRequest<Path extends ApiPath, Method extends HttpMethod>(
	path: Path,
	method: Method,
	options: ApiRequestOptions<Path, Method> | undefined,
	accept: string,
	parseAs: 'text' | 'blob' | 'stream',
	fetcher: typeof fetch
): Promise<{ data: unknown; response: Response }> {
	const call = (client as unknown as Record<string, ClientCall>)[method.toUpperCase()];
	const requestOptions = callOptions(options, fetcher);
	requestOptions.parseAs = parseAs;
	requestOptions.headers = mergeHeaders(
		{ Accept: accept },
		(options as { headers?: HeadersInit } | undefined)?.headers
	);
	const { data, error, response } = await call(path, requestOptions);
	if (!response.ok) throw responseError(response, error);
	return { data, response };
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

function saveBlob(blob: Blob, filename: string) {
	const url = URL.createObjectURL(blob);
	const link = document.createElement('a');
	link.href = url;
	link.download = filename;
	link.click();
	URL.revokeObjectURL(url);
}

type DownloadPicker = {
	createWritable(): Promise<{ write(data: Uint8Array): Promise<void>; close(): Promise<void> }>;
};

export type ApiDownloadOptions = {
	/** Filename to show in the save picker before the response headers arrive. */
	suggestedName?: string;
};

const defaultDownloadFilename = 'quirebase-export';

function downloadConfig(fetcherOrOptions: typeof fetch | ApiDownloadOptions): {
	fetcher: typeof fetch;
	suggestedName: string;
} {
	if (typeof fetcherOrOptions === 'function') {
		return { fetcher: fetcherOrOptions, suggestedName: defaultDownloadFilename };
	}
	return {
		fetcher: fetch,
		suggestedName: fetcherOrOptions.suggestedName ?? defaultDownloadFilename
	};
}

async function openSaveTarget(suggestedName: string): Promise<DownloadPicker | undefined> {
	const browser = globalThis as typeof globalThis & {
		showSaveFilePicker?: (options?: { suggestedName?: string }) => Promise<DownloadPicker>;
	};
	if (!browser.showSaveFilePicker) return undefined;
	try {
		return await browser.showSaveFilePicker({ suggestedName });
	} catch (error) {
		// A caller reached the helper outside the transient activation window.
		// Fall back to the streamed response/Blob path; explicit user
		// cancellation still propagates to the mutation.
		if (
			error !== null &&
			typeof error === 'object' &&
			'name' in error &&
			error.name === 'SecurityError'
		)
			return undefined;
		if (
			error !== null &&
			typeof error === 'object' &&
			'name' in error &&
			error.name === 'AbortError'
		)
			throw new DownloadCancelledError();
		throw error;
	}
}

async function saveStream(
	stream: ReadableStream<Uint8Array> | null,
	filename: string,
	target?: DownloadPicker
) {
	if (!target) {
		// File System Access is the only browser API that can write a fetch
		// stream directly to disk. Keep a compatibility fallback for browsers
		// without it.
		saveBlob(stream ? await new Response(stream).blob() : new Blob(), filename);
		return;
	}
	const writable = await target.createWritable();
	if (!stream) {
		await writable.close();
		return;
	}
	const reader = stream.getReader();
	try {
		while (true) {
			const chunk = await reader.read();
			if (chunk.done) break;
			await writable.write(chunk.value);
		}
		await writable.close();
	} catch (error) {
		await reader.cancel();
		throw error;
	}
}

export async function apiDownload<Path extends PathsWithMethod<'post'>>(
	path: Path,
	options: ApiRequestOptions<Path, 'post'>,
	fetcherOrOptions: typeof fetch | ApiDownloadOptions = fetch
): Promise<void> {
	const { fetcher, suggestedName } = downloadConfig(fetcherOrOptions);
	if (fetcher !== fetch) {
		const { data, response } = await rawRequest(path, 'post', options, '*/*', 'blob', fetcher);
		const filename = downloadFilename(response.headers.get('Content-Disposition') ?? '');
		saveBlob(data as Blob, filename);
		return;
	}
	// The picker must be invoked before awaiting the request. Browsers only
	// allow showSaveFilePicker during the click's transient activation window.
	// The response filename is not available yet, so use the caller's best
	// filename hint while preserving the click's transient activation.
	const target = await openSaveTarget(suggestedName);
	const { data, response } = await rawRequest(path, 'post', options, '*/*', 'stream', fetcher);
	const filename = downloadFilename(response.headers.get('Content-Disposition') ?? '');
	await saveStream(data as ReadableStream<Uint8Array> | null, filename, target);
}

export async function apiDownloadGet<Path extends PathsWithMethod<'get'>>(
	path: Path,
	options: ApiRequestOptions<Path, 'get'>,
	fetcherOrOptions: typeof fetch | ApiDownloadOptions = fetch
): Promise<void> {
	const { fetcher, suggestedName } = downloadConfig(fetcherOrOptions);
	if (fetcher === fetch) {
		// See apiDownload: opening the picker before awaiting fetch preserves the
		// transient user activation required by the File System Access API.
		const target = await openSaveTarget(suggestedName);
		const { data, response } = await rawRequest(path, 'get', options, '*/*', 'stream', fetcher);
		const filename = downloadFilename(response.headers.get('Content-Disposition') ?? '');
		await saveStream(data as ReadableStream<Uint8Array> | null, filename, target);
		return;
	}
	const { data, response } = await rawRequest(path, 'get', options, '*/*', 'blob', fetcher);
	const filename = downloadFilename(response.headers.get('Content-Disposition') ?? '');
	saveBlob(data as Blob, filename);
}

export async function apiText<Path extends PathsWithMethod<'get'>>(
	path: Path,
	options: ApiRequestOptions<Path, 'get'>,
	fetcher: typeof fetch = fetch
): Promise<string> {
	const { data } = await rawRequest(path, 'get', options, 'text/plain', 'text', fetcher);
	return (data as string) ?? '';
}

type WorkspaceRequestArguments<
	Path extends WorkspaceApiPath,
	Method extends HttpMethod
> = OptionsArguments<WorkspaceApiRequestOptions<Path, Method>>;

function withWorkspacePath<Path extends WorkspaceApiPath, Method extends HttpMethod>(
	workspaceId: string,
	options: WorkspaceApiRequestOptions<Path, Method> | undefined
): ApiRequestOptions<Path, Method> {
	const resolved = (options ?? {}) as Record<string, unknown>;
	const params = (resolved.params ?? {}) as Record<string, unknown>;
	const path = (params.path ?? {}) as Record<string, unknown>;
	return {
		...resolved,
		params: { ...params, path: { ...path, workspace_id: workspaceId } }
	} as unknown as ApiRequestOptions<Path, Method>;
}

/** Bind every Workspace-scoped request to an explicit URL Workspace ID. */
export function createWorkspaceApi(workspaceId: string) {
	return {
		request: async <
			Method extends RequestMethod,
			Path extends WorkspacePathsWithMethod<Lowercase<Method> & HttpMethod>
		>(
			method: Method,
			path: Path,
			...args: WorkspaceRequestArguments<Path, Lowercase<Method> & HttpMethod>
		): Promise<ApiResponse<Path, Lowercase<Method> & HttpMethod>> => {
			const options = args[0] as
				WorkspaceApiRequestOptions<Path, Lowercase<Method> & HttpMethod> | undefined;
			const fetcher = args[1] as typeof fetch | undefined;
			return apiRequest(method, path, withWorkspacePath(workspaceId, options), fetcher);
		},
		download: async <Path extends WorkspacePathsWithMethod<'post'>>(
			path: Path,
			options: WorkspaceApiRequestOptions<Path, 'post'>,
			fetcherOrOptions: typeof fetch | ApiDownloadOptions = fetch
		): Promise<void> =>
			apiDownload(path, withWorkspacePath(workspaceId, options), fetcherOrOptions),
		downloadGet: async <Path extends WorkspacePathsWithMethod<'get'>>(
			path: Path,
			options: WorkspaceApiRequestOptions<Path, 'get'>,
			fetcherOrOptions: typeof fetch | ApiDownloadOptions = fetch
		): Promise<void> =>
			apiDownloadGet(path, withWorkspacePath(workspaceId, options), fetcherOrOptions),
		text: async <Path extends WorkspacePathsWithMethod<'get'>>(
			path: Path,
			options: WorkspaceApiRequestOptions<Path, 'get'>,
			fetcher: typeof fetch = fetch
		): Promise<string> => apiText(path, withWorkspacePath(workspaceId, options), fetcher)
	};
}

export type SessionView = components['schemas']['SessionView'];
export type ItemSummary = components['schemas']['ItemSearchView'];
export type ProjectSummary = components['schemas']['ProjectSummaryView'];
export type WorkspaceView = components['schemas']['WorkspaceView'];
export type ItemOverviewView = components['schemas']['ItemOverviewView'];
export type LibraryView = components['schemas']['LibrarySearchView'];
