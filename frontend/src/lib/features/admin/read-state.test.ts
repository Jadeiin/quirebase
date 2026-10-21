import { describe, expect, it } from 'vitest';
import { ApiError } from '#lib/api/client.js';
import { adminReadState, isAdminUnavailableError } from './read-state';

describe('administration read state', () => {
	it('shows initial loading until a usable snapshot exists', () => {
		expect(adminReadState({ loading: true, failed: false, available: false })).toBe('loading');
	});

	it('keeps existing content mounted while refreshing', () => {
		expect(adminReadState({ loading: true, failed: false, available: true })).toBe('ready');
	});

	it.each([
		new TypeError('Failed to fetch'),
		new ApiError(503, { code: 'request_failed', message: 'Unavailable' })
	])('keeps cached content and retry feedback after a transient refresh failure', (error) => {
		expect(adminReadState({ loading: false, failed: true, available: true, error })).toBe('stale');
		expect(adminReadState({ loading: false, failed: true, available: false, error })).toBe(
			'unavailable'
		);
	});

	it.each([401, 403, 404])('hides cached content after authoritative HTTP %i', (status) => {
		const error = new ApiError(status, { code: 'not_available', message: 'Unavailable' });
		expect(isAdminUnavailableError(error)).toBe(true);
		expect(adminReadState({ loading: false, failed: true, available: true, error })).toBe(
			'unavailable'
		);
		expect(adminReadState({ loading: true, failed: false, available: true, error })).toBe(
			'unavailable'
		);
	});

	it('does not treat a purged successful cache snapshot as an empty read', () => {
		expect(adminReadState({ loading: false, failed: false, available: false })).toBe('unavailable');
	});

	it('returns to normal content after a successful retry', () => {
		expect(adminReadState({ loading: false, failed: false, available: true, error: null })).toBe(
			'ready'
		);
	});

	it('retains existing callers that do not supply snapshot availability', () => {
		expect(adminReadState({ loading: false, failed: false })).toBe('ready');
		expect(adminReadState({ loading: true, failed: false })).toBe('loading');
		expect(adminReadState({ loading: false, failed: true })).toBe('unavailable');
	});
});
