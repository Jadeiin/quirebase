import { readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { gzipSync } from 'node:zlib';

type ManifestEntry = {
	file: string;
	name?: string;
	imports?: string[];
	dynamicImports?: string[];
	css?: string[];
	assets?: string[];
};

type BundleSize = { raw: number; gzip: number };

const outputDirectory = '.svelte-kit/output/client';
const manifest = JSON.parse(
	readFileSync(join(outputDirectory, '.vite/manifest.json'), 'utf8')
) as Record<string, ManifestEntry>;
const generatedApp = readFileSync('.svelte-kit/generated/client/app.js', 'utf8');

function manifestKeyByName(name: string): string {
	const match = Object.entries(manifest).find(([, entry]) => entry.name === name);
	if (!match) throw new Error(`Bundle manifest entry not found: ${name}`);
	return match[0];
}

function routeNodes(route: string): string[] {
	const escaped = route.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
	const match = generatedApp.match(new RegExp(`"${escaped}": \\[(\\d+),\\[([^\\]]*)\\]\\]`));
	if (!match) throw new Error(`SvelteKit route node not found: ${route}`);
	const layouts = match[2]
		.split(',')
		.map((value) => value.trim())
		.filter(Boolean);
	return [0, ...layouts, match[1]].map(
		(index) => `.svelte-kit/generated/client-optimized/nodes/${index}.js`
	);
}

function dependencyGraph(roots: string[], includeDynamicImports: boolean): Set<string> {
	const graph = new Set<string>();
	const pending = [...roots];
	while (pending.length) {
		const key = pending.pop();
		if (!key || graph.has(key)) continue;
		const entry = manifest[key];
		if (!entry) throw new Error(`Bundle dependency not found: ${key}`);
		graph.add(key);
		pending.push(...(entry.imports ?? []));
		if (includeDynamicImports) pending.push(...(entry.dynamicImports ?? []));
	}
	return graph;
}

function mergeGraphs(...graphs: Set<string>[]): Set<string> {
	return new Set(graphs.flatMap((graph) => [...graph]));
}

function graphFiles(graph: Set<string>): Set<string> {
	const files = new Set<string>();
	for (const key of graph) {
		const entry = manifest[key];
		files.add(entry.file);
		for (const file of entry.css ?? []) files.add(file);
		for (const file of entry.assets ?? []) files.add(file);
	}
	return files;
}

function bundleSize(files: Set<string>): BundleSize {
	let raw = 0;
	let gzip = 0;
	for (const file of files) {
		const path = join(outputDirectory, file);
		const contents = readFileSync(path);
		raw += statSync(path).size;
		gzip += gzipSync(contents).byteLength;
	}
	return { raw, gzip };
}

function format(bytes: number): string {
	return `${(bytes / 1024).toFixed(1)} KiB`;
}

function enforce(name: string, actual: BundleSize, budget: BundleSize) {
	console.log(`${name}: ${format(actual.raw)} raw, ${format(actual.gzip)} gzip`);
	if (actual.raw > budget.raw || actual.gzip > budget.gzip) {
		throw new Error(
			`${name} exceeds its budget (${format(budget.raw)} raw, ${format(budget.gzip)} gzip)`
		);
	}
}

const runtime = [manifestKeyByName('entry/start'), manifestKeyByName('entry/app')];
const dashboard = dependencyGraph([...runtime, ...routeNodes('/(app)')], false);
const pdfRouteNodes = routeNodes('/(app)/item/[itemId]/pdf/[revisionId]');
const pdfReader = mergeGraphs(
	dependencyGraph([...runtime, ...pdfRouteNodes], false),
	dependencyGraph([pdfRouteNodes.at(-1)!], true)
);

function routeBundle(route: string): BundleSize {
	return bundleSize(graphFiles(dependencyGraph([...runtime, ...routeNodes(route)], false)));
}

const dashboardPdfDependencies = [...dashboard].filter((key) => {
	const entry = manifest[key];
	return (
		entry.name?.toLowerCase().includes('embedpdf') ||
		(entry.assets ?? []).some((asset) => asset.includes('pdfium'))
	);
});
if (dashboardPdfDependencies.length) {
	throw new Error(
		`PDF reader code leaked into the application shell: ${dashboardPdfDependencies.join(', ')}`
	);
}

enforce('Application shell', bundleSize(graphFiles(dashboard)), {
	raw: 500000,
	gzip: 155000
});
enforce('Library route', routeBundle('/(app)/library'), {
	raw: 530000,
	gzip: 167000
});
enforce('Import route', routeBundle('/(app)/import'), {
	raw: 520000,
	gzip: 163000
});
enforce('Item overview route', routeBundle('/(app)/item/[itemId]/(workspace)'), {
	raw: 534000,
	gzip: 167000
});
enforce('Item metadata route', routeBundle('/(app)/item/[itemId]/(workspace)/metadata'), {
	raw: 542000,
	gzip: 170000
});
enforce('Item files route', routeBundle('/(app)/item/[itemId]/(workspace)/files'), {
	raw: 539000,
	gzip: 170000
});
enforce('Item organize route', routeBundle('/(app)/item/[itemId]/(workspace)/organize'), {
	raw: 537000,
	gzip: 168000
});
enforce('Item annotations route', routeBundle('/(app)/item/[itemId]/(workspace)/annotations'), {
	raw: 530000,
	gzip: 166000
});
enforce('Item discussion route', routeBundle('/(app)/item/[itemId]/(workspace)/discussion'), {
	raw: 532000,
	gzip: 167000
});
enforce('Admin overview route', routeBundle('/(app)/admin'), {
	raw: 500000,
	gzip: 155000
});
enforce('Admin users route', routeBundle('/(app)/admin/users'), {
	raw: 510000,
	gzip: 159000
});
enforce('Admin projects route', routeBundle('/(app)/admin/projects'), {
	raw: 500000,
	gzip: 155000
});
enforce('Admin items route', routeBundle('/(app)/admin/items'), {
	raw: 522000,
	gzip: 164000
});
enforce('Admin audit route', routeBundle('/(app)/admin/audit'), {
	raw: 501000,
	gzip: 156000
});
enforce('Admin workflows route', routeBundle('/(app)/admin/workflows'), {
	raw: 498000,
	gzip: 155000
});
enforce('Admin settings route', routeBundle('/(app)/admin/settings'), {
	raw: 502000,
	gzip: 157000
});
enforce('Admin maintenance route', routeBundle('/(app)/admin/maintenance'), {
	raw: 504000,
	gzip: 158000
});
enforce('PDF reader route', bundleSize(graphFiles(pdfReader)), {
	raw: 8_000_000,
	gzip: 3_100_000
});
