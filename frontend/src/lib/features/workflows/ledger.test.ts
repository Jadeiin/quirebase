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

	it('restores import destinations and terminal status within the account ledger', () => {
		const ledger = localStorageWorkflowLedger('user-a');
		const completed = {
			...entry,
			workspaceId: 'workspace-1',
			target: { kind: 'import_batch' as const, id: 'batch-1' },
			outcome: { id: entry.id, state: 'succeeded' as const, error: null }
		};
		ledger.write([completed]);
		expect(ledger.read()).toEqual([completed]);
		expect(localStorageWorkflowLedger('user-b').read()).toEqual([]);
	});

	it.each([
		{ successMessage: '' },
		{ failureMessage: '' },
		{ workspaceId: 'workspace-1', target: { kind: 'url', id: 'javascript:alert(1)' } },
		{ workspaceId: 'workspace-1', target: { kind: 'import_batch', id: '' } },
		{ target: { kind: 'import_batch', id: 'batch-1' } },
		{ workspaceId: 42 },
		{
			workspaceId: 'workspace-1',
			target: { kind: 'import_batch', id: 'batch-1' },
			outcome: { id: 'other-workflow', state: 'succeeded' }
		},
		{
			workspaceId: 'workspace-1',
			target: { kind: 'import_batch', id: 'batch-1' },
			outcome: { id: entry.id, state: 'pending' }
		}
	])('rejects malformed stored workflows: %j', (invalid) => {
		localStorage.setItem(
			'quirebase:tracked-workflows:user-a',
			JSON.stringify([{ ...entry, ...invalid }])
		);
		expect(localStorageWorkflowLedger('user-a').read()).toEqual([]);
	});
});
