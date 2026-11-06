export type ScholarlyLink = {
	label: string;
	href?: string;
	icon?: string;
};

const resolvers = {
	doi: { label: 'DOI', pattern: /^10\.\d{4,9}\/\S+$/, base: 'https://doi.org/' },
	arxiv: {
		label: 'arXiv',
		pattern: /^(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[a-z]{2})?\/\d{7})(?:v\d+)?$/i,
		base: 'https://arxiv.org/abs/'
	},
	openalex: { label: 'OpenAlex', pattern: /^W\d+$/i, base: 'https://openalex.org/' },
	pmid: { label: 'PMID', pattern: /^\d+$/, base: 'https://pubmed.ncbi.nlm.nih.gov/' },
	pmcid: { label: 'PMCID', pattern: /^PMC\d+$/i, base: 'https://pmc.ncbi.nlm.nih.gov/articles/' },
	ror: { label: 'ROR', pattern: /^0[0-9a-hjkmnp-tv-z]{6}\d{2}$/i, base: 'https://ror.org/' }
};

export function scholarlyLink(value: string, namespace = ''): ScholarlyLink {
	if (!value.trim()) return { label: '' };
	const key = namespace.toLowerCase();
	const resolver = Object.hasOwn(resolvers, key)
		? resolvers[key as keyof typeof resolvers]
		: undefined;
	const label = namespace ? `${resolver?.label ?? namespace}: ${value}` : value;
	let candidate = value.trim();
	if (resolver?.pattern.test(candidate)) {
		candidate = resolver.base + candidate.split('/').map(encodeURIComponent).join('/');
	}
	try {
		const url = new URL(candidate);
		if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password)
			return { label };
		const host = url.hostname.toLowerCase();
		let icon = 'external-link';
		if (host === 'doi.org' || host === 'dx.doi.org') icon = 'doi';
		else if (host === 'arxiv.org' || host === 'export.arxiv.org') icon = 'arxiv';
		else if (host === 'ror.org') icon = 'ror';
		else if (host === 'pubmed.ncbi.nlm.nih.gov' || host === 'pmc.ncbi.nlm.nih.gov') icon = 'pubmed';
		else if (host === 'creativecommons.org' && /^\/(?:licenses|publicdomain)\//.test(url.pathname))
			icon = 'creative-commons';
		return { label, href: url.href, icon };
	} catch {
		return { label };
	}
}
