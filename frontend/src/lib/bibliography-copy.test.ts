import { describe, expect, it, vi } from 'vitest';
import { copyBibliographyText, type BibliographyCopyState } from './bibliography-copy.js';

describe('bibliography clipboard recovery', () => {
	it('retains generated text after clipboard rejection and retries without generation', async () => {
		const state: BibliographyCopyState = { text: null };
		const generate = vi.fn().mockResolvedValue('Captured bibliography');
		const write = vi
			.fn()
			.mockRejectedValueOnce(new Error('Clipboard denied'))
			.mockResolvedValueOnce(undefined);

		await expect(copyBibliographyText(state, generate, () => true, write)).rejects.toThrow(
			'Clipboard denied'
		);
		expect(state.text).toBe('Captured bibliography');
		await copyBibliographyText(state, generate, () => true, write);
		expect(generate).toHaveBeenCalledTimes(1);
		expect(write).toHaveBeenNthCalledWith(2, 'Captured bibliography');
	});

	it('retries failed generation without treating it as an empty bibliography', async () => {
		const state: BibliographyCopyState = { text: null };
		const generate = vi
			.fn()
			.mockRejectedValueOnce(new Error('Offline'))
			.mockResolvedValueOnce('Recovered bibliography');
		const write = vi.fn().mockResolvedValue(undefined);

		await expect(copyBibliographyText(state, generate, () => true, write)).rejects.toThrow(
			'Offline'
		);
		expect(state.text).toBeNull();
		expect(write).not.toHaveBeenCalled();
		await copyBibliographyText(state, generate, () => true, write);
		expect(write).toHaveBeenCalledWith('Recovered bibliography');
	});

	it('does not change the clipboard after the initiating view has unmounted', async () => {
		const state: BibliographyCopyState = { text: null };
		const write = vi.fn();
		await copyBibliographyText(
			state,
			async () => 'Late bibliography',
			() => false,
			write
		);
		expect(state.text).toBe('Late bibliography');
		expect(write).not.toHaveBeenCalled();
	});
});
