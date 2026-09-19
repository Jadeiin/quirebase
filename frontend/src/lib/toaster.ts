import { createToaster } from '@skeletonlabs/skeleton-svelte';

// Shared singleton: render <Toast /> (design/Toast.svelte) once in the application shell,
// then push from anywhere with toaster.success(...) / toaster.error(...) / toaster.info(...).
export const toaster = createToaster({
	placement: 'bottom',
	duration: 6000,
	max: 5
});
