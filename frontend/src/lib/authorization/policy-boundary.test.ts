import { ESLint } from 'eslint';
import { describe, expect, it } from 'vitest';

const eslint = new ESLint();

async function violations(source: string) {
	const [result] = await eslint.lintText(source, {
		filePath: 'src/lib/workspaces/context.svelte.ts'
	});
	expect(result.fatalErrorCount).toBe(0);
	return result.messages.filter((message) => message.ruleId === 'no-restricted-syntax');
}

describe('capability policy boundary', () => {
	it.each([
		"workspace.role === 'admin'",
		"workspaceContext.role !== 'viewer'",
		"workspace.view.current_role === 'owner'",
		"workspace.view?.current_role === 'owner'",
		"session.data.user?.role === 'administrator'",
		"['owner', 'admin'].includes(workspace.role)"
	])('rejects principal role decisions in TypeScript: %s', async (decision) => {
		expect(await violations(`const allowed = ${decision};`)).toHaveLength(1);
	});

	it('rejects role decisions in Svelte templates', async () => {
		const [result] = await eslint.lintText(
			"<script lang='ts'>const workspace = getWorkspaceContext();</script>{#if workspace.role === 'admin'}<button>Delete</button>{/if}",
			{ filePath: 'src/lib/features/projects/Projects.svelte' }
		);
		expect(
			result.messages.filter((message) => message.ruleId === 'no-restricted-syntax')
		).toHaveLength(1);
	});

	it('allows capabilities, domain choices, role labels, and target-role form values', async () => {
		expect(
			await violations(`
			const allowed = can(workspace.view.authorization, 'item.delete');
			const modes = workspace.view.allowed_project_participations;
			const label = domainLabel(workspace.role);
			const unchanged = member.role === requestedRole;
		`)
		).toEqual([]);
	});
});
