export type ButtonVariant =
	'tonal' | 'filled' | 'danger' | 'danger-filled' | 'primary' | 'success' | 'warning' | 'icon';

const variantClasses: Record<ButtonVariant, string> = {
	tonal: 'btn preset-tonal-surface preset-outlined-surface-300-700 font-semibold',
	filled: 'btn preset-filled-primary-700-300 font-semibold',
	danger: 'btn preset-tonal-error preset-outlined-error-200-800 font-semibold',
	'danger-filled': 'btn preset-filled-error-700-300 font-semibold',
	primary: 'btn preset-tonal-primary preset-outlined-primary-200-800 font-semibold',
	success: 'btn preset-tonal-success preset-outlined-success-200-800 font-semibold',
	warning: 'btn preset-tonal-warning preset-outlined-warning-200-800 font-semibold',
	icon: 'btn-icon preset-tonal-surface preset-outlined-surface-300-700'
};

export function buttonClass(variant: ButtonVariant, size: 'md' | 'sm' = 'md'): string {
	return `${variantClasses[variant]}${size === 'sm' ? ' btn-sm' : ''}`;
}
