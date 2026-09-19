import { mutationOptions } from '@tanstack/svelte-query';

export type AdminMutation = {
	run: () => Promise<unknown>;
	form?: HTMLFormElement;
};

export function adminMutationOptions(section: string, refresh: () => Promise<unknown>) {
	return mutationOptions({
		mutationKey: ['admin-mutation', section],
		mutationFn: ({ run }: AdminMutation) => run(),
		onSuccess: async (_result, mutation) => {
			await refresh();
			mutation.form?.reset();
		}
	});
}
