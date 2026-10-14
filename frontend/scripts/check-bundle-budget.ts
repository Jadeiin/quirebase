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
const generatedApp = readFileSync('.svelte-kit/generated/build/client/app.js', 'utf8');

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
	return [0, ...layouts, match[1]].map((index) => manifestKeyByName(`nodes/${index}`));
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
const metadataEditorKey = manifestKeyByName('SchemaMetadataEditor');
if (dashboard.has(metadataEditorKey))
	throw new Error('Schema editor code leaked into the application shell');
const pdfRouteNodes = routeNodes('/(app)/workspace/[workspaceId]/item/[itemId]/pdf/[revisionId]');
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

// Skeleton's supported component stylesheet adds shared CSS; Progress and Navigation
// stay in the shell, while DateField/Combobox/Listbox/SegmentedControl remain route-owned.
// Schema editor field/type translations and theme utilities add about 17.5 KiB raw /
// 5.2 KiB gzip to shared catalogs/CSS. Add that measured cost to the existing budgets.
// The earlier locked build measures 638.2 KiB raw / 177.4 KiB gzip for the shell (formerly
// 523.2 / 163.7), including 164.0 KiB CSS / 18.8 KiB gzip. Refresh route budgets
// against that build with about 2% headroom; never load the calendar in the shell.
if ([...dashboard].some((key) => manifest[key].name === 'DateField')) {
	throw new Error('DatePicker code leaked into the application shell');
}

enforce('Application shell', bundleSize(graphFiles(dashboard)), {
	raw: 683000,
	gzip: 192000
});
enforce('Library route', routeBundle('/(app)/workspace/[workspaceId]/library'), {
	raw: 893000,
	gzip: 256000
});
enforce('Discovery route', routeBundle('/(app)/workspace/[workspaceId]/discovery'), {
	raw: 808000,
	gzip: 228000
});
enforce('Account route', routeBundle('/(app)/account'), {
	raw: 799000,
	gzip: 226000
});
enforce('Tools route', routeBundle('/(app)/workspace/[workspaceId]/tools'), {
	raw: 813000,
	gzip: 233000
});
enforce('Import route', routeBundle('/(app)/workspace/[workspaceId]/import'), {
	raw: 829000,
	gzip: 236000
});
enforce(
	'Item overview route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)'),
	{
		raw: 801000,
		gzip: 229000
	}
);
enforce(
	'Item metadata route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/metadata'),
	{
		raw: 903000,
		gzip: 258000
	}
);
enforce(
	'Item files route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/files'),
	{
		raw: 807000,
		gzip: 232000
	}
);
enforce(
	'Item organize route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/organize'),
	{
		raw: 806000,
		gzip: 231000
	}
);
enforce(
	'Item annotations route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/annotations'),
	{
		raw: 815000,
		gzip: 234000
	}
);
enforce(
	'Item discussion route',
	routeBundle('/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/discussion'),
	{
		raw: 803000,
		gzip: 232000
	}
);
enforce('Admin overview route', routeBundle('/(app)/admin'), {
	raw: 695000,
	gzip: 198000
});
enforce('Admin users route', routeBundle('/(app)/admin/users'), {
	raw: 717000,
	gzip: 205000
});
enforce('Admin workspaces route', routeBundle('/(app)/admin/workspaces'), {
	raw: 747000,
	gzip: 213000
});
enforce('Admin audit route', routeBundle('/(app)/admin/audit'), {
	raw: 709000,
	gzip: 202000
});
enforce('Admin workflows route', routeBundle('/(app)/admin/workflows'), {
	raw: 693000,
	gzip: 197000
});
enforce('Admin settings route', routeBundle('/(app)/admin/settings'), {
	raw: 699000,
	gzip: 200000
});
enforce('Admin maintenance route', routeBundle('/(app)/admin/maintenance'), {
	raw: 699000,
	gzip: 200000
});
enforce('PDF reader route', bundleSize(graphFiles(pdfReader)), {
	raw: 8_000_000,
	gzip: 3_100_000
});

const metadataRoute = '/(app)/workspace/[workspaceId]/item/[itemId]/(sections)/metadata';
const openedEditor = mergeGraphs(
	dependencyGraph([...runtime, ...routeNodes(metadataRoute)], false),
	dependencyGraph([metadataEditorKey], true)
);
enforce('Metadata editor when open', bundleSize(graphFiles(openedEditor)), {
	raw: 1050000,
	gzip: 300000
});
