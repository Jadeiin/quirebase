import { describe, expect, it, vi } from 'vitest';
import { randomUUID } from './uuid.js';

describe('randomUUID', () => {
	it('prefers the native UUID generator when available', () => {
		const uuid = '706a31a4-7040-4c13-941f-2729a19b6888';
		const native = vi.spyOn(crypto, 'randomUUID').mockReturnValue(uuid);
		const fallback = vi.spyOn(crypto, 'getRandomValues');
		expect(randomUUID()).toBe(uuid);
		expect(native).toHaveBeenCalledOnce();
		expect(fallback).not.toHaveBeenCalled();
	});

	it.each([
		{ byte: 0, uuid: '00000000-0000-4000-8000-000000000000' },
		{ byte: 255, uuid: 'ffffffff-ffff-4fff-bfff-ffffffffffff' }
	])('generates UUID v4 without randomUUID using random byte $byte', ({ byte, uuid }) => {
		vi.stubGlobal('crypto', {
			getRandomValues: (bytes: Uint8Array) => bytes.fill(byte)
		});
		expect(randomUUID()).toBe(uuid);
	});

	it.each([undefined, {}])('fails when no cryptographic generator is available (%j)', (crypto) => {
		vi.stubGlobal('crypto', crypto);
		expect(randomUUID).toThrow('No cryptographic random number generator is available');
	});
});
