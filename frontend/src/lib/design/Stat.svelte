<script lang="ts">
	let { value, label } = $props<{ value: string | number; label: string }>();
</script>

<div class="grid grid-cols-1 gap-1 rounded-base bg-surface-200-800 p-3">
	<strong class="text-[1.4rem] tabular-nums">{value}</strong>
	<span class="text-xs text-surface-700-300">{label}</span>
</div>
