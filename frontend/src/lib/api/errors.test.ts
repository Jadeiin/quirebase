import { describe, expect, it } from 'vitest';

import { ApiError } from './client';
import { apiErrorMessage } from './errors';

describe('apiErrorMessage', () => {
	it('localizes known API error codes instead of exposing the server message', () => {
		const error = new ApiError(409, {
			code: 'version_conflict',
			message: 'server-only wording',
			meta: { version: 2 }
		});

		expect(apiErrorMessage(error, 'Unable to save changes')).toBe(
			'This record changed. Refresh and try again.'
		);
	});

	it('uses the translated feature fallback for unknown failures', () => {
		expect(apiErrorMessage(new Error('network wording'), 'Unable to save changes')).toBe(
			'Unable to save changes'
		);
	});

	it('does not expose an unexpected server failure message', () => {
		const error = new ApiError(500, {
			code: 'internal_error',
			message: 'database connection details'
		});

		expect(apiErrorMessage(error, 'Unable to save changes')).toBe(
			'Something went wrong. Try again.'
		);
	});
});
