/** Canonical display/query iD; the Library independently validates every server-side filter. */
export function orcidId(value: unknown): string | undefined {
	if (typeof value !== 'string') return undefined;
	const match = /^(?:https?:\/\/orcid\.org\/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])\/?$/i.exec(
		value.trim()
	);
	if (!match) return undefined;
	const id = match[1].toUpperCase();
	const digits = id.replaceAll('-', '');
	// ISO 7064 MOD 11-2 check digit, with X representing ten.
	let total = 0;
	for (const digit of digits.slice(0, -1)) total = (total + Number(digit)) * 2;
	const checksum = (12 - (total % 11)) % 11;
	return digits.at(-1) === (checksum === 10 ? 'X' : String(checksum)) ? id : undefined;
}
