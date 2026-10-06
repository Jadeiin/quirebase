import { ESLint } from 'eslint';
import { beforeAll, describe, expect, it } from 'vitest';

const eslint = new ESLint();

async function violations(source: string) {
	const [result] = await eslint.lintText(source, {
		filePath: 'src/lib/workspaces/context.svelte.ts'
	});
	expect(result.fatalErrorCount).toBe(0);
	return result.messages.filter((message) => message.ruleId === 'no-restricted-syntax');
}

describe('capability policy boundary', () => {
	beforeAll(async () => {
		// Configuration and the TypeScript project service load lazily on the first lint.
		await violations('const warmup = true;');
	}, 15_000);

	it('rejects each principal role decision in TypeScript', async () => {
		const decisions = [
			"workspace.role === 'admin'",
			"workspaceContext.role !== 'viewer'",
			"workspace.view.current_role === 'owner'",
			"workspace.view?.current_role === 'owner'",
			"session.data.user?.role === 'administrator'",
			"['owner', 'admin'].includes(workspace.role)"
		];
		const source = decisions
			.map((decision, index) => `const allowed${index} = ${decision};`)
			.join('\n');
		expect((await violations(source)).map((message) => message.line)).toEqual(
			decisions.map((_, index) => index + 1)
		);
	});

	it('rejects role decisions in Svelte templates', async () => {
		const [result] = await eslint.lintText(
			"<script lang='ts'>const workspace = getWorkspaceContext();</script>{#if workspace.role === 'admin'}<button>Delete</button>{/if}",
			{ filePath: 'src/lib/features/projects/Projects.svelte' }
		);
		expect(result.fatalErrorCount).toBe(0);
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
