// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';

import {
	defaultExportPreferences,
	exportPreferencesKey,
	readExportPreferences,
	writeExportPreferences
} from './export-preferences';

describe('export preference storage', () => {
	afterEach(() => {
		localStorage.clear();
	});

	it('falls back to defaults when stored JSON is malformed', () => {
		localStorage.setItem(exportPreferencesKey('reader'), '{stale');

		expect(readExportPreferences('reader')).toEqual(defaultExportPreferences);
	});

	it('falls back to defaults when localStorage cannot be read', () => {
		vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
			throw new DOMException('blocked', 'SecurityError');
		});

		expect(readExportPreferences('reader')).toEqual(defaultExportPreferences);
	});

	it('rejects unknown versions and invalid preference field types', () => {
		localStorage.setItem(
			exportPreferencesKey('reader'),
			JSON.stringify({
				schemaVersion: 2,
				citation: { format: 'invalid', includeAbstract: 'yes' },
				document: { includeAnnotations: 'yes' }
			})
		);

		expect(readExportPreferences('reader')).toEqual(defaultExportPreferences);
	});

	it('keeps export controls usable when localStorage cannot be written', () => {
		vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
			throw new DOMException('full', 'QuotaExceededError');
		});

		expect(() =>
			writeExportPreferences('reader', structuredClone(defaultExportPreferences))
		).not.toThrow();
	});
});
