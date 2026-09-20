import { describe, expect, it } from 'vitest';

import { ApiError } from '$lib/api/client';
import { isRecoverableWorkflowStatusError } from './queries';

describe('isRecoverableWorkflowStatusError', () => {
	it('keeps transport and transient HTTP failures recoverable', () => {
		expect(isRecoverableWorkflowStatusError(new Error('network unavailable'))).toBe(true);
		for (const status of [408, 425, 429, 500, 503]) {
			expect(
				isRecoverableWorkflowStatusError(
					new ApiError(status, { code: 'request_failed', message: 'temporary failure' })
				)
			).toBe(true);
		}
	});

	it('settles permanent API failures', () => {
		for (const status of [400, 401, 403, 404, 409]) {
			expect(
				isRecoverableWorkflowStatusError(
					new ApiError(status, { code: 'request_failed', message: 'permanent failure' })
				)
			).toBe(false);
		}
	});
});
