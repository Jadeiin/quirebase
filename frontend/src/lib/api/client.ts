import type { components, paths } from '$lib/api/schema';

type ApiErrorView = components['schemas']['ApiErrorView'];

const authenticationRequiredHandlers = new Set<() => void>();

export function onAuthenticationRequired(handler: () => void): () => void {
	authenticationRequiredHandlers.add(handler);
	return () => authenticationRequiredHandlers.delete(handler);
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

type ParameterValue<OperationType, Key extends PropertyKey> = OperationType extends {
	parameters: infer Parameters;
}
	? Key extends keyof Parameters
		? NonNullable<Parameters[Key]>
		: never
	: never;
type RequiredKeys<Value> = Value extends object
	? {
			[Key in keyof Value]-?: object extends Pick<Value, Key> ? never : Key;
		}[keyof Value]
	: never;
type ParameterSegment<Key extends string, Value> = [Value] extends [never]
	? object
	: [RequiredKeys<Value>] extends [never]
		? { [Property in Key]?: Value }
		: { [Property in Key]: Value };
type ParameterBag<OperationType> = ParameterSegment<'path', ParameterValue<OperationType, 'path'>> &
	ParameterSegment<'query', ParameterValue<OperationType, 'query'>>;
type ParameterOptions<OperationType> = [keyof ParameterBag<OperationType>] extends [never]
	? { params?: never }
	: [RequiredKeys<ParameterBag<OperationType>>] extends [never]
		? { params?: ParameterBag<OperationType> }
		: { params: ParameterBag<OperationType> };

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

type RequestOptions<OperationType> = ParameterOptions<OperationType> &
	BodyOptions<OperationType> & {
		headers?: HeadersInit;
		signal?: AbortSignal;
	};
type OptionsArguments<OperationType> = [RequiredKeys<RequestOptions<OperationType>>] extends [never]
	? [options?: RequestOptions<OperationType>, fetcher?: typeof fetch]
	: [options: RequestOptions<OperationType>, fetcher?: typeof fetch];

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
export type ApiResponse<Path extends ApiPath, Method extends HttpMethod> = ResponseData<
	SuccessResponse<Operation<Path, Method>>
>;

async function responseError(response: Response): Promise<ApiError> {
	const payload = (await response.json().catch(() => null)) as ApiErrorView | null;
	const error = new ApiError(
		response.status,
		payload?.code && payload.message
			? payload
			: {
					code: 'request_failed',
					message: response.statusText || `HTTP ${response.status}`
				}
	);
	if (error.status === 401 && error.code === 'authentication_required') {
		for (const handler of authenticationRequiredHandlers) handler();
	}
	return error;
}

function requestUrl(path: string, params: unknown): string {
	const parameterBag = (params ?? {}) as {
		path?: Record<string, string | number>;
		query?: Record<string, unknown>;
	};
	let resolved = path;
	for (const [name, value] of Object.entries(parameterBag.path ?? {})) {
		resolved = resolved.replace(`{${name}}`, encodeURIComponent(String(value)));
	}
	const query = new URLSearchParams();
	for (const [name, value] of Object.entries(parameterBag.query ?? {})) {
		if (value === undefined || value === null || value === '') continue;
		for (const entry of Array.isArray(value) ? value : [value]) query.append(name, String(entry));
	}
	const encoded = query.toString();
	return `/api/v1${resolved}${encoded ? `?${encoded}` : ''}`;
}

export async function apiRequest<
	Method extends RequestMethod,
	Path extends PathsWithMethod<Lowercase<Method> & HttpMethod>
>(
	method: Method,
	path: Path,
	...args: OptionsArguments<Operation<Path, Lowercase<Method> & HttpMethod>>
): Promise<ApiResponse<Path, Lowercase<Method> & HttpMethod>> {
	const options = args[0] as
		| {
				body?: unknown;
				headers?: HeadersInit;
				params?: unknown;
				signal?: AbortSignal;
		  }
		| undefined;
	const fetcher = args[1] ?? fetch;
	const headers = new Headers(options?.headers);
	let body: BodyInit | undefined;
	if (options?.body instanceof FormData || options?.body instanceof Blob) {
		body = options.body;
	} else if (options?.body !== undefined) {
		headers.set('Content-Type', 'application/json');
		body = JSON.stringify(options.body);
	}
	headers.set('Accept', 'application/json');

	const response = await fetcher(requestUrl(path, options?.params), {
		method,
		body,
		credentials: 'same-origin',
		headers,
		signal: options?.signal
	});
	if (!response.ok) throw await responseError(response);
	if (response.status === 204)
		return undefined as ApiResponse<Path, Lowercase<Method> & HttpMethod>;
	return (await response.json()) as ApiResponse<Path, Lowercase<Method> & HttpMethod>;
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

function requestBody(bodyValue: unknown, headers: Headers): BodyInit | undefined {
	if (bodyValue instanceof FormData || bodyValue instanceof Blob) return bodyValue;
	if (bodyValue === undefined) return undefined;
	headers.set('Content-Type', 'application/json');
	return JSON.stringify(bodyValue);
}

async function rawResponse(
	method: RequestMethod,
	path: string,
	options: { body?: unknown; headers?: HeadersInit; params?: unknown; signal?: AbortSignal },
	accept: string,
	fetcher: typeof fetch
): Promise<Response> {
	const headers = new Headers(options.headers);
	headers.set('Accept', accept);
	const response = await fetcher(requestUrl(path, options.params), {
		method,
		body: requestBody(options.body, headers),
		credentials: 'same-origin',
		headers,
		signal: options.signal
	});
	if (!response.ok) throw await responseError(response);
	return response;
}

export async function apiDownload<Path extends PathsWithMethod<'post'>>(
	path: Path,
	options: RequestOptions<Operation<Path, 'post'>>,
	fetcher: typeof fetch = fetch
): Promise<void> {
	const response = await rawResponse('POST', path, options, '*/*', fetcher);
	const filename = downloadFilename(response.headers.get('Content-Disposition') ?? '');
	const url = URL.createObjectURL(await response.blob());
	const link = document.createElement('a');
	link.href = url;
	link.download = filename;
	link.click();
	URL.revokeObjectURL(url);
}

export async function apiDownloadGet<Path extends PathsWithMethod<'get'>>(
	path: Path,
	options: RequestOptions<Operation<Path, 'get'>>,
	fetcher: typeof fetch = fetch
): Promise<void> {
	const response = await rawResponse('GET', path, options, '*/*', fetcher);
	const filename = downloadFilename(response.headers.get('Content-Disposition') ?? '');
	const url = URL.createObjectURL(await response.blob());
	const link = document.createElement('a');
	link.href = url;
	link.download = filename;
	link.click();
	URL.revokeObjectURL(url);
}

export async function apiText<Path extends PathsWithMethod<'get'>>(
	path: Path,
	options: RequestOptions<Operation<Path, 'get'>>,
	fetcher: typeof fetch = fetch
): Promise<string> {
	const response = await rawResponse('GET', path, options, 'text/plain', fetcher);
	return response.text();
}

export type SessionView = components['schemas']['SessionView'];
export type ItemSummary = components['schemas']['ItemSearchView'];
export type ProjectSummary = components['schemas']['ProjectSummaryView'];
export type WorkspaceView = components['schemas']['ItemWorkspaceView'];
export type LibraryView = components['schemas']['LibrarySearchView'];
