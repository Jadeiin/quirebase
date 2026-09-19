import { createContext } from 'svelte';
import type { AdminFilters } from './queries';

export type AdminFilterContext = {
	filters: () => AdminFilters;
	setPage: (page: number) => void;
};

const [getAdminFilters, setAdminFilters] = createContext<AdminFilterContext>();

export { getAdminFilters, setAdminFilters };
