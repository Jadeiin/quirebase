export type ButtonVariant =
	'tonal' | 'filled' | 'danger' | 'danger-filled' | 'primary' | 'success' | 'warning' | 'icon';

const variantClasses: Record<ButtonVariant, string> = {
	tonal: 'btn preset-tonal-surface font-semibold',
	filled: 'btn preset-filled-primary-700-300 font-semibold',
	danger: 'btn preset-tonal-error font-semibold',
	'danger-filled': 'btn preset-filled-error-700-300 font-semibold',
	primary: 'btn preset-tonal-primary font-semibold',
	success: 'btn preset-tonal-success font-semibold',
	warning: 'btn preset-tonal-warning font-semibold',
	icon: 'btn-icon preset-tonal-surface'
};

export function buttonClass(variant: ButtonVariant, size: 'md' | 'sm' = 'md'): string {
	return `${variantClasses[variant]}${size === 'sm' ? ' btn-sm' : ''}`;
}
