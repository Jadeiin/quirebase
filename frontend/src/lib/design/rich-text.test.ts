import { describe, expect, it } from 'vitest';
import { hasInlineMath, projectRichText, projectRichTextAsync } from '$lib/design/rich-text';

describe('Web rich-text projection', () => {
	it('converts every inline TeX span to allowlisted MathML inside canonical markup', async () => {
		const rendered = await projectRichTextAsync(
			String.raw`Energy $E_{mc}\in\mathbb{R}$ and <i>$x^2$</i>`
		);

		expect(rendered.match(/<math/g)).toHaveLength(2);
		expect(rendered).toContain('<i><math');
		expect(rendered).toContain('<msub>');
		expect(rendered).toContain('<msup>');
		expect(rendered).not.toContain('$E_');
	});

	it('drops elements and attributes outside the rich-text and MathML allowlists', async () => {
		const rendered = await projectRichTextAsync(
			String.raw`<script>alert(1)</script>$\href{javascript:alert(1)}{x}$`
		);

		expect(rendered).not.toContain('<script');
		expect(rendered).not.toContain('href=');
		expect(rendered).not.toContain('javascript:');
		expect(rendered).toContain('<mi>x</mi>');
	});

	it('falls back to literal text for malformed or oversized TeX spans', async () => {
		const malformed = await projectRichTextAsync(String.raw`Invalid $\frac{$ formula`);
		const oversized = await projectRichTextAsync(`$${'x'.repeat(201)}$`);

		expect(malformed).toBe(String.raw`Invalid $\frac{$ formula`);
		expect(oversized).toBe(`$${'x'.repeat(201)}$`);
		expect(malformed).not.toContain('<math');
		expect(oversized).not.toContain('<math');
	});

	it('keeps currency dollars outside the inline-math grammar', () => {
		const rendered = projectRichText('Costs $5 and $10; US$5 and CA$10');

		expect(rendered).toBe('Costs $5 and $10; US$5 and CA$10');
		expect(rendered).not.toContain('<math');
	});

	it('detects inline math without treating currency as math', () => {
		expect(hasInlineMath(String.raw`Energy $E_{mc}\in\mathbb{R}$`)).toBe(true);
		expect(hasInlineMath(String.raw`<i>$x^2$</i>`)).toBe(true);
		expect(hasInlineMath('Costs $5 and $10; US$5 and CA$10')).toBe(false);
		expect(hasInlineMath('<script>$x^2$</script>')).toBe(false);
		expect(hasInlineMath('<i>Visible</i> text')).toBe(false);
	});

	it('rebuilds canonical rich text without source attributes or unknown elements', () => {
		const rendered = projectRichText(
			'<i onclick="alert(1)">Visible</i><span data-source="x"> text</span><img src=x onerror=alert(1)>'
		);

		expect(rendered).toBe('<i>Visible</i> text');
		expect(rendered).not.toContain('onclick');
		expect(rendered).not.toContain('data-source');
		expect(rendered).not.toContain('<img');
	});
});
