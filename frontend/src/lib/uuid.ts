// Follows https://github.com/TanStack/db/blob/main/packages/db/src/utils/uuid.ts.
// getRandomValues is available on LAN HTTP origins, unlike crypto.randomUUID.
export function randomUUID(): string {
	const crypto = globalThis.crypto;
	if (typeof crypto?.randomUUID === 'function') return crypto.randomUUID();
	if (typeof crypto?.getRandomValues !== 'function')
		throw new Error('No cryptographic random number generator is available');

	const bytes = crypto.getRandomValues(new Uint8Array(16));
	// RFC 4122: version 4 and variant 10xx.
	bytes[6] = (bytes[6] & 0x0f) | 0x40;
	bytes[8] = (bytes[8] & 0x3f) | 0x80;
	const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('');
	return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
