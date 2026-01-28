<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import type { Snippet } from 'svelte';

	// Props for Svelte 5 layout
	let { children }: { children: Snippet } = $props();

	// Environment check - in production, require password
	const isProduction = import.meta.env.VITE_ENVIRONMENT === 'production';
	const requiredPassword = import.meta.env.VITE_FRONTEND_PASSWORD || '';

	let isAuthenticated = $state(false);
	let password = $state('');
	let error = $state('');
	let isChecking = $state(true);

	onMount(() => {
		// In local mode, skip auth
		if (!isProduction || !requiredPassword) {
			isAuthenticated = true;
			isChecking = false;
			return;
		}

		// Check sessionStorage for existing auth
		const storedAuth = sessionStorage.getItem('bowerbirder_auth');
		if (storedAuth === 'true') {
			isAuthenticated = true;
		}
		isChecking = false;
	});

	function handleSubmit() {
		error = '';
		if (password === requiredPassword) {
			isAuthenticated = true;
			sessionStorage.setItem('bowerbirder_auth', 'true');
		} else {
			error = 'Incorrect password';
			password = '';
		}
	}

	function handleKeydown(event: KeyboardEvent) {
		if (event.key === 'Enter') {
			handleSubmit();
		}
	}
</script>

{#if isChecking}
	<div class="loading">Loading...</div>
{:else if !isAuthenticated}
	<div class="auth-gate">
		<div class="auth-box">
			<h1>Bowerbirder</h1>
			<p>Enter password to continue</p>
			<input
				type="password"
				bind:value={password}
				onkeydown={handleKeydown}
				placeholder="Password"
			/>
			<button onclick={handleSubmit}>Enter</button>
			{#if error}
				<p class="error">{error}</p>
			{/if}
		</div>
	</div>
{:else}
	{@render children()}
{/if}

<style>
	.loading {
		display: flex;
		justify-content: center;
		align-items: center;
		height: 100vh;
		font-size: 1.2rem;
		color: #666;
	}

	.auth-gate {
		display: flex;
		justify-content: center;
		align-items: center;
		height: 100vh;
		background: #f5f5f5;
	}

	.auth-box {
		background: white;
		padding: 2rem;
		border-radius: 8px;
		box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
		text-align: center;
		width: 300px;
	}

	.auth-box h1 {
		margin: 0 0 0.5rem 0;
		font-size: 1.5rem;
	}

	.auth-box p {
		margin: 0 0 1rem 0;
		color: #666;
	}

	.auth-box input {
		width: 100%;
		padding: 0.75rem;
		border: 1px solid #ddd;
		border-radius: 4px;
		font-size: 1rem;
		margin-bottom: 1rem;
		box-sizing: border-box;
	}

	.auth-box button {
		width: 100%;
		padding: 0.75rem;
		background: #333;
		color: white;
		border: none;
		border-radius: 4px;
		font-size: 1rem;
		cursor: pointer;
	}

	.auth-box button:hover {
		background: #555;
	}

	.error {
		color: #e53935;
		margin-top: 0.5rem;
	}
</style>
