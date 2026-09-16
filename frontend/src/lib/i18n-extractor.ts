import { parse } from 'svelte/compiler';
import ts from 'typescript';

export type SvelteExtractedMessage = {
	id: string;
	message: string;
	origin: [filename: string, line: number, column: number];
};

type SvelteExtractor = {
	match(filename: string): boolean;
	extract(
		filename: string,
		source: string,
		onMessageExtracted: (message: SvelteExtractedMessage) => void,
		context: unknown
	): void;
};

type TypeScriptExtractor = SvelteExtractor;

type AstNode = {
	type?: string;
	loc?: { start: { line: number; column: number } };
	callee?: { type?: string; name?: string };
	arguments?: AstNode[];
	value?: unknown;
};

function visit(value: unknown, callback: (node: AstNode) => void): void {
	if (!value || typeof value !== 'object') return;
	if (Array.isArray(value)) {
		for (const child of value) visit(child, callback);
		return;
	}

	const node = value as AstNode;
	if (node.type) callback(node);
	for (const [key, child] of Object.entries(node)) {
		if (key !== 'loc') visit(child, callback);
	}
}

function literalMessage(node: AstNode, filename: string): SvelteExtractedMessage | undefined {
	if (node.type !== 'CallExpression' || node.callee?.type !== 'Identifier') return;
	if (node.callee.name !== '$t' && node.callee.name !== 'msg') return;

	const argument = node.arguments?.[0];
	if (argument?.type === 'Literal' && typeof argument.value === 'string') {
		return {
			id: argument.value,
			message: argument.value,
			origin: [filename, node.loc!.start.line, node.loc!.start.column]
		};
	}
	if (node.callee.name === 'msg') {
		throw new Error(`${filename}:${node.loc!.start.line}: msg() requires a string literal`);
	}
}

export const svelteExtractor: SvelteExtractor = {
	match(filename) {
		return filename.endsWith('.svelte');
	},
	extract(filename, source, onMessageExtracted) {
		const ast = parse(source, { filename, modern: true });
		visit(ast, (node) => {
			const message = literalMessage(node, filename);
			if (message) onMessageExtracted(message);
		});
	}
};

export const typescriptExtractor: TypeScriptExtractor = {
	match(filename) {
		return filename.endsWith('.ts') && !filename.endsWith('.d.ts');
	},
	extract(filename, source, onMessageExtracted) {
		const sourceFile = ts.createSourceFile(
			filename,
			source,
			ts.ScriptTarget.Latest,
			true,
			ts.ScriptKind.TS
		);

		function visitTypeScript(node: ts.Node): void {
			if (ts.isCallExpression(node) && ts.isIdentifier(node.expression)) {
				const name = node.expression.text;
				if (name === '$t' || name === 'msg') {
					const argument = node.arguments[0];
					if (argument && ts.isStringLiteralLike(argument)) {
						const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
						onMessageExtracted({
							id: argument.text,
							message: argument.text,
							origin: [filename, position.line + 1, position.character]
						});
					} else if (name === 'msg') {
						const position = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
						throw new Error(`${filename}:${position.line + 1}: msg() requires a string literal`);
					}
				}
			}
			ts.forEachChild(node, visitTypeScript);
		}

		visitTypeScript(sourceFile);
	}
};
