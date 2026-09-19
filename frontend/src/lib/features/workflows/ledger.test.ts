// @vitest-environment jsdom

import { afterEach, describe, expect, it } from 'vitest';

import { localStorageWorkflowLedger } from './ledger';

const entry = {
	id: 'workflow-1',
	label: 'Document processing',
	successMessage: 'done',
	failureMessage: 'failed',
	startedAt: 1
};

afterEach(() => {
	localStorage.clear();
});

describe('localStorageWorkflowLedger', () => {
	it('scopes persisted workflows to the authenticated user', () => {
		const first = localStorageWorkflowLedger('user-a');
		const second = localStorageWorkflowLedger('user-b');

		first.write([entry]);

		expect(first.read()).toEqual([entry]);
		expect(second.read()).toEqual([]);
	});

	it('reads back every persisted active workflow without a cap', () => {
		const ledger = localStorageWorkflowLedger('user-a');
		const entries = Array.from({ length: 25 }, (_, index) => ({
			...entry,
			id: `workflow-${index}`
		}));

		ledger.write(entries);

		expect(ledger.read().map((stored) => stored.id)).toEqual(entries.map((stored) => stored.id));
	});

	it('ignores malformed entries', () => {
		const ledger = localStorageWorkflowLedger('user-a');
		localStorage.setItem(
			'quirebase:tracked-workflows:user-a',
			JSON.stringify([entry, { id: 42 }, null])
		);

		expect(ledger.read()).toEqual([entry]);
	});
});
