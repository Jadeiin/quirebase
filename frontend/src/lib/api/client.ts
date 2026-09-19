import createClient, {
	createQuerySerializer,
	mergeHeaders,
	type FetchOptions
} from 'openapi-fetch';
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
	parseAs: 'text' | 'blob',
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

export async function apiDownload<Path extends PathsWithMethod<'post'>>(
	path: Path,
	options: ApiRequestOptions<Path, 'post'>,
	fetcher: typeof fetch = fetch
): Promise<void> {
	const { data, response } = await rawRequest(path, 'post', options, '*/*', 'blob', fetcher);
	const filename = downloadFilename(response.headers.get('Content-Disposition') ?? '');
	saveBlob(data as Blob, filename);
}

export async function apiDownloadGet<Path extends PathsWithMethod<'get'>>(
	path: Path,
	options: ApiRequestOptions<Path, 'get'>,
	fetcher: typeof fetch = fetch
): Promise<void> {
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

export type SessionView = components['schemas']['SessionView'];
export type ItemSummary = components['schemas']['ItemSearchView'];
export type ProjectSummary = components['schemas']['ProjectSummaryView'];
export type WorkspaceView = components['schemas']['ItemWorkspaceView'];
export type LibraryView = components['schemas']['LibrarySearchView'];
