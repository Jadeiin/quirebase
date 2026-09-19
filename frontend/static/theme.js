(() => {
	let mode;
	try {
		const preference = localStorage.getItem('quirebase:theme');
		const systemDark = matchMedia('(prefers-color-scheme: dark)').matches;
		mode = preference === 'dark' || (preference !== 'light' && systemDark) ? 'dark' : 'light';
	} catch {
		mode = matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
	}
	document.documentElement.dataset.mode = mode;
	document
		.querySelector('meta[name="theme-color"]')
		?.setAttribute('content', mode === 'dark' ? '#0e1713' : '#f4f6f5');
})();
