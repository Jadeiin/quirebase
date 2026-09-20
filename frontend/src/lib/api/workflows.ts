import { apiRequest } from '$lib/api/client';
import { translate } from '$lib/i18n';
import type { components } from '$lib/api/schema';

type WorkflowStatus = components['schemas']['WorkflowStatusView'];

function abortError(): DOMException {
	return new DOMException('Workflow wait aborted', 'AbortError');
}

function delay(milliseconds: number, signal?: AbortSignal): Promise<void> {
	return new Promise((resolve, reject) => {
		if (signal?.aborted) return reject(abortError());
		const completed = () => {
			signal?.removeEventListener('abort', aborted);
			resolve();
		};
		const aborted = () => {
			window.clearTimeout(timer);
			reject(abortError());
		};
		const timer = window.setTimeout(completed, milliseconds);
		signal?.addEventListener('abort', aborted, { once: true });
	});
}

function waitUntilVisible(signal?: AbortSignal): Promise<void> {
	if (document.visibilityState !== 'hidden') return Promise.resolve();
	return new Promise((resolve, reject) => {
		if (signal?.aborted) return reject(abortError());
		const cleanup = () => {
			document.removeEventListener('visibilitychange', visible);
			signal?.removeEventListener('abort', aborted);
		};
		const visible = () => {
			if (document.visibilityState === 'hidden') return;
			cleanup();
			resolve();
		};
		const aborted = () => {
			cleanup();
			reject(abortError());
		};
		document.addEventListener('visibilitychange', visible);
		signal?.addEventListener('abort', aborted, { once: true });
	});
}

export async function waitForWorkflow(
	workflowId: string,
	options: { signal?: AbortSignal; failureMessage?: string } = {}
): Promise<WorkflowStatus> {
	let interval = 500;
	for (;;) {
		if (options.signal?.aborted) throw abortError();
		await waitUntilVisible(options.signal);
		const workflow = await apiRequest('GET', '/workflows/{workflow_id}', {
			params: { path: { workflow_id: workflowId } },
			signal: options.signal
		});
		if (workflow.state === 'succeeded') return workflow;
		if (workflow.state === 'failed' || workflow.state === 'cancelled') {
			throw new Error(workflow.error || options.failureMessage || translate('Workflow failed'));
		}
		await delay(interval, options.signal);
		interval = Math.min(interval * 2, 4000);
	}
}
