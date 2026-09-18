import { mutationOptions, type QueryClient } from '@tanstack/svelte-query';
import { itemKeys } from './queries';

export type ItemMutation = {
	run: () => Promise<unknown>;
	form?: HTMLFormElement;
};

export function itemMutationOptions(itemId: string, queryClient: QueryClient) {
	return mutationOptions({
		mutationKey: ['item-mutation', itemId],
		mutationFn: ({ run }: ItemMutation) => run(),
		onSuccess: async (_result, mutation) => {
			await Promise.all([
				queryClient.invalidateQueries({ queryKey: itemKeys.shell(itemId) }),
				queryClient.invalidateQueries({ queryKey: itemKeys.details(itemId) }),
				queryClient.invalidateQueries({ queryKey: itemKeys.sections(itemId) })
			]);
			mutation.form?.reset();
		}
	});
}
