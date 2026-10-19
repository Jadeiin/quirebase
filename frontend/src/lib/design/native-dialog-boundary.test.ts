import { ESLint } from 'eslint';
import { describe, expect, it } from 'vitest';

const eslint = new ESLint();
const rules = new Set(['no-restricted-globals', 'no-restricted-properties']);

describe('native dialog boundary', () => {
	it('rejects native dialogs in Svelte event handlers', async () => {
		const [result] = await eslint.lintText(
			'<button onclick={() => window.confirm("Delete?")}>Delete</button>',
			{ filePath: 'src/lib/features/workspaces/WorkspaceMembers.svelte' }
		);
		expect(result.fatalErrorCount).toBe(0);
		expect(result.messages.filter((message) => rules.has(message.ruleId ?? ''))).toHaveLength(1);
	}, 15000);
	for (const filePath of [
		'src/lib/features/workspaces/queries.ts',
		'src/lib/features/workspaces/WorkspaceMembers.svelte'
	]) {
		it(`rejects native dialogs in ${filePath}`, async () => {
			const source =
				"confirm('Delete?'); window.prompt('Name'); globalThis.alert('Done'); self['confirm']('Archive?');";
			const [result] = await eslint.lintText(
				filePath.endsWith('.svelte') ? `<script lang="ts">${source}</script>` : source,
				{ filePath }
			);
			expect(result.fatalErrorCount).toBe(0);
			expect(result.messages.filter((message) => rules.has(message.ruleId ?? ''))).toHaveLength(4);
		}, 15000);
	}
});
