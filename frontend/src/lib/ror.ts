/** ROR's Crockford base32 identifier with its ISO 7064 MOD 97-10 checksum. */
export function rorId(value: unknown): string | undefined {
	if (typeof value !== 'string') return undefined;
	const match = /^(?:https?:\/\/ror\.org\/)?(0[0-9a-hjkmnp-tv-z]{6}[0-9]{2})\/?$/i.exec(
		value.trim()
	);
	if (!match) return undefined;
	const id = match[1].toLowerCase();
	let number = 0;
	for (const character of id.slice(0, 7))
		number = number * 32 + '0123456789abcdefghjkmnpqrstvwxyz'.indexOf(character);
	return Number(id.slice(-2)) === 98 - ((number * 100) % 97) ? id : undefined;
}
