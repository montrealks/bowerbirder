<script lang="ts">
	import { onMount } from 'svelte';
	import imageCompression from 'browser-image-compression';

	// Types
	interface UploadedFile {
		id: string;
		name: string;
		preview: string;
		file: File;
	}

	interface UppyFile {
		id: string;
		name: string;
		size: number;
		type: string;
		data: File | Blob;
		preview?: string;
	}

	interface UppyInstance {
		use: (plugin: unknown, opts?: unknown) => UppyInstance;
		on: (event: string, callback: () => void) => void;
		getFiles: () => UppyFile[];
		close: () => void;
	}

	interface StylePreset {
		id: string;
		name: string;
	}

	// State
	let files: UploadedFile[] = $state([]);
	let selectedStyle: string = $state('fridge');
	let aspectRatio: '16:9' | '9:16' | '1:1' = $state('16:9');
	let isGenerating: boolean = $state(false);
	let status: string = $state('');
	let statusType: 'info' | 'error' | 'success' = $state('info');
	let imageUrl: string = $state('');
	let imageExpiresAt: string = $state('');
	let uppy: UppyInstance | null = $state(null);
	let totalFileSize: number = $state(0);
	let styles: StylePreset[] = $state([]);

	// Track object URLs we create so we can revoke them
	let createdObjectUrls: Map<string, string> = new Map();

	// Track abort controller for cancelling fetch requests on unmount
	let abortController: AbortController | null = null;

	// Track pending timeouts so we can clear them on unmount
	let pendingTimeouts: Set<ReturnType<typeof setTimeout>> = new Set();

	// Use relative URLs by default (works in production with Caddy proxy)
	const API_URL = import.meta.env.VITE_API_URL || '';
	const STORAGE_KEY = 'bowerbirder_last_image';
	const MAX_FILE_SIZE_MB = 100;
	const MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024;
	const MIN_IMAGES = 2;
	const MAX_IMAGES = 6;

	const aspectRatios = [
		{ value: '16:9', label: 'Landscape', icon: 'landscape' },
		{ value: '1:1', label: 'Square', icon: 'square' },
		{ value: '9:16', label: 'Portrait', icon: 'portrait' }
	] as const;

	// Persist image to localStorage
	function saveImageToStorage(url: string, expiresAt: string) {
		localStorage.setItem(STORAGE_KEY, JSON.stringify({ url, expiresAt }));
	}

	// Restore image from localStorage if still valid
	function restoreImageFromStorage() {
		try {
			const stored = localStorage.getItem(STORAGE_KEY);
			if (!stored) return;

			const { url, expiresAt } = JSON.parse(stored);
			const expiry = new Date(expiresAt);

			if (expiry > new Date()) {
				imageUrl = url;
				imageExpiresAt = expiresAt;
			} else {
				localStorage.removeItem(STORAGE_KEY);
			}
		} catch {
			localStorage.removeItem(STORAGE_KEY);
		}
	}

	// Countdown timer
	let timeRemaining: string = $state('');
	let timerInterval: ReturnType<typeof setInterval> | null = null;

	function stopTimer() {
		if (timerInterval) {
			clearInterval(timerInterval);
			timerInterval = null;
		}
	}

	function clearImage() {
		imageUrl = '';
		imageExpiresAt = '';
		timeRemaining = '';
		status = '';
		localStorage.removeItem(STORAGE_KEY);
		stopTimer();
	}

	function startExpiryTimer() {
		stopTimer();

		function updateTimer() {
			if (!imageExpiresAt) return;

			const now = new Date();
			const expiry = new Date(imageExpiresAt);
			const diff = expiry.getTime() - now.getTime();

			if (diff <= 0) {
				timeRemaining = 'Expired';
				clearImage();
				return;
			}

			const minutes = Math.floor(diff / 60000);
			const seconds = Math.floor((diff % 60000) / 1000);
			timeRemaining = `${minutes}m ${seconds}s remaining`;
		}

		updateTimer();
		timerInterval = setInterval(updateTimer, 1000);
	}

	onMount(async () => {
		// Fetch style options from API
		try {
			const response = await fetch(`${API_URL}/options`);
			if (response.ok) {
				styles = await response.json();
				// Set default style to first option if available
				if (styles.length > 0 && !selectedStyle) {
					selectedStyle = styles[0].id;
				}
			}
		} catch (error) {
			console.error('Failed to fetch style options:', error);
			// Fallback to hardcoded styles if API fails
			styles = [
				{ id: 'fridge', name: 'On the Fridge' },
				{ id: 'scrapbook', name: 'Old Scrapbook' },
				{ id: 'clean', name: 'Clean' }
			];
		}

		// Dynamic import for Uppy (client-side only)
		const Uppy = (await import('@uppy/core')).default;
		const Dashboard = (await import('@uppy/dashboard')).default;
		const ImageEditor = (await import('@uppy/image-editor')).default;

		// Import CSS
		await import('@uppy/core/dist/style.min.css');
		await import('@uppy/dashboard/dist/style.min.css');
		await import('@uppy/image-editor/dist/style.min.css');

		uppy = new Uppy({
			restrictions: {
				maxNumberOfFiles: MAX_IMAGES,
				allowedFileTypes: ['image/*']
			},
			autoProceed: false
		})
		.use(Dashboard, {
			target: '#uppy-dashboard',
			inline: true,
			height: 350,
			width: '100%',
			showProgressDetails: false,
			proudlyDisplayPoweredByUppy: false,
			theme: 'light',
			hideUploadButton: true,
			hideRetryButton: true,
			hideCancelButton: true,
			note: `Drag & drop ${MIN_IMAGES}-${MAX_IMAGES} images or click to browse`
		})
		.use(ImageEditor, {
			target: Dashboard
		});

		// Update files list when Uppy state changes
		uppy.on('file-added', updateFilesList);
		uppy.on('file-removed', updateFilesList);

		function updateFilesList() {
			if (!uppy) return;
			const uppyFiles: UppyFile[] = uppy.getFiles();
			const currentFileIds = new Set(uppyFiles.map((f) => f.id));

			// Revoke object URLs for files that were removed
			for (const [fileId, objectUrl] of createdObjectUrls) {
				if (!currentFileIds.has(fileId)) {
					URL.revokeObjectURL(objectUrl);
					createdObjectUrls.delete(fileId);
				}
			}

			files = uppyFiles.map((f) => {
				let preview = f.preview;
				if (!preview) {
					if (createdObjectUrls.has(f.id)) {
						preview = createdObjectUrls.get(f.id)!;
					} else {
						preview = URL.createObjectURL(f.data);
						createdObjectUrls.set(f.id, preview);
					}
				}
				return {
					id: f.id,
					name: f.name,
					preview,
					file: f.data as File
				};
			});

			totalFileSize = uppyFiles.reduce((sum, f) => sum + f.size, 0);
		}

		// Restore previous image from storage
		restoreImageFromStorage();
		if (imageUrl && imageExpiresAt) {
			startExpiryTimer();
		}

		return () => {
			uppy?.close();
			stopTimer();
			abortController?.abort();
			abortController = null;
			for (const timeoutId of pendingTimeouts) {
				clearTimeout(timeoutId);
			}
			pendingTimeouts.clear();
			for (const objectUrl of createdObjectUrls.values()) {
				URL.revokeObjectURL(objectUrl);
			}
			createdObjectUrls.clear();
		};
	});

	async function generateCollage() {
		// Get fresh files directly from Uppy (cached files array can have stale File objects)
		const uppyFiles = uppy?.getFiles() ?? [];

		if (uppyFiles.length < MIN_IMAGES) {
			status = `Please add at least ${MIN_IMAGES} images`;
			statusType = 'error';
			return;
		}

		// Cancel any previous request
		abortController?.abort();
		abortController = new AbortController();

		isGenerating = true;
		status = 'Uploading images...';
		statusType = 'info';
		imageUrl = '';

		try {
			const imageUrls: string[] = [];

			for (const f of uppyFiles) {
				const base64 = await fileToBase64(f.data as File);
				imageUrls.push(base64);
			}

			status = 'Creating collage job...';

			const response = await fetch(`${API_URL}/jobs`, {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					images: imageUrls,
					style: selectedStyle,
					aspect_ratio: aspectRatio
				}),
				signal: abortController.signal
			});

			if (!response.ok) {
				const error = await response.json();
				throw new Error(error.detail || `API error: ${response.statusText}`);
			}

			const result = await response.json();
			const jobId = result.job_id;

			status = 'Processing...';

			// Poll for completion
			await pollJobStatus(jobId);

		} catch (error) {
			if (error instanceof Error && error.name === 'AbortError') {
				return;
			}
			status = `Error: ${error instanceof Error ? error.message : 'Unknown error'}`;
			statusType = 'error';
			safeTimeout(() => {
				status = '';
				statusType = 'info';
			}, 5000);
		} finally {
			isGenerating = false;
			abortController = null;
		}
	}

	async function pollJobStatus(jobId: string) {
		const maxAttempts = 180; // 3 minutes max (collage generation can take a while)
		let attempts = 0;

		while (attempts < maxAttempts) {
			if (abortController?.signal.aborted) {
				throw new Error('Request cancelled');
			}

			const response = await fetch(`${API_URL}/jobs/${jobId}`, {
				signal: abortController?.signal
			});

			if (!response.ok) {
				throw new Error(`API error: ${response.statusText}`);
			}

			const job = await response.json();

			if (job.status === 'completed') {
				status = 'Collage ready!';
				statusType = 'success';
				imageUrl = job.image_url;
				imageExpiresAt = job.expires_at;
				saveImageToStorage(imageUrl, imageExpiresAt);
				startExpiryTimer();
				safeTimeout(() => {
					status = '';
					statusType = 'info';
				}, 2000);
				return;
			} else if (job.status === 'failed') {
				throw new Error(job.error || 'Collage generation failed');
			}

			status = job.status_detail || `Processing... (${attempts + 1}s)`;
			await sleep(1000);
			attempts++;
		}

		throw new Error('Timeout waiting for collage');
	}

	async function fileToBase64(file: File | Blob): Promise<string> {
		// Use browser-image-compression to fix EXIF orientation
		// This draws the image to canvas (which applies EXIF rotation in modern browsers)
		// and re-exports it, ensuring correct orientation
		const fileToProcess = file instanceof File ? file : new File([file], 'image.jpg', { type: file.type });

		const options = {
			maxSizeMB: 10, // Don't compress much, just fix orientation
			maxWidthOrHeight: 4096, // Keep high resolution
			useWebWorker: true,
			fileType: 'image/jpeg' as const,
			exifOrientation: 1 // Reset EXIF orientation to normal
		};

		const compressedFile = await imageCompression(fileToProcess, options);

		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(reader.result as string);
			reader.onerror = reject;
			reader.readAsDataURL(compressedFile);
		});
	}

	function sleep(ms: number): Promise<void> {
		return new Promise(resolve => {
			const timeoutId = setTimeout(() => {
				pendingTimeouts.delete(timeoutId);
				resolve();
			}, ms);
			pendingTimeouts.add(timeoutId);
		});
	}

	function safeTimeout(callback: () => void, ms: number): void {
		const timeoutId = setTimeout(() => {
			pendingTimeouts.delete(timeoutId);
			callback();
		}, ms);
		pendingTimeouts.add(timeoutId);
	}

	function formatMB(bytes: number): string {
		return (bytes / 1024 / 1024).toFixed(1);
	}

	// Derived state
	let capacityPercent = $derived(Math.min((files.length / MAX_IMAGES) * 100, 100));
	let isOverCapacity = $derived(totalFileSize > MAX_FILE_SIZE_BYTES);
	let canGenerate = $derived(files.length >= MIN_IMAGES && files.length <= MAX_IMAGES && !isOverCapacity);
</script>

<div class="container">
	<h1>Bowerbirder</h1>
	<p class="subtitle">Upload photos, choose a style, generate a collage</p>

	<div class="section">
		<h2 class="section-title">
			<span>1. Add Photos</span>
			{#if files.length > 0}
				<span class="image-count">({files.length}/{MAX_IMAGES} selected)</span>
			{/if}
		</h2>
		<div id="uppy-dashboard"></div>

		{#if files.length > 0}
			<div class="capacity-bar-container">
				<div class="capacity-bar" class:over-capacity={isOverCapacity}>
					<div class="capacity-fill" style="width: {capacityPercent}%"></div>
				</div>
				<span class="capacity-text" class:over-capacity={isOverCapacity}>
					{files.length}/{MAX_IMAGES} images
				</span>
			</div>
		{/if}
	</div>

	<div class="section">
		<h2 class="section-title">2. Choose Style</h2>
		<div class="styles-grid">
			{#each styles as style}
				<button
					class="style-btn"
					class:selected={selectedStyle === style.id}
					onclick={() => selectedStyle = style.id}
				>
					{style.name}
				</button>
			{/each}
		</div>
	</div>

	<div class="section">
		<h2 class="section-title">3. Aspect Ratio</h2>

		<div class="setting-group">
			<div class="aspect-ratio-buttons">
				{#each aspectRatios as ratio}
					<button
						class="aspect-btn"
						class:selected={aspectRatio === ratio.value}
						onclick={() => aspectRatio = ratio.value}
						title={ratio.label}
					>
						{#if ratio.icon === 'landscape'}
							<svg width="32" height="20" viewBox="0 0 32 20" fill="none" stroke="currentColor" stroke-width="2">
								<rect x="1" y="1" width="30" height="18" rx="1" />
							</svg>
						{:else if ratio.icon === 'square'}
							<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
								<rect x="1" y="1" width="22" height="22" rx="1" />
							</svg>
						{:else if ratio.icon === 'portrait'}
							<svg width="20" height="32" viewBox="0 0 20 32" fill="none" stroke="currentColor" stroke-width="2">
								<rect x="1" y="1" width="18" height="30" rx="1" />
							</svg>
						{/if}
					</button>
				{/each}
			</div>
		</div>
	</div>

	<button
		class="generate-btn"
		class:generating={isGenerating}
		class:error={statusType === 'error' && status}
		class:success={statusType === 'success' && status}
		onclick={generateCollage}
		disabled={isGenerating || !canGenerate}
	>
		{#if isGenerating}
			<span class="btn-status">{status || 'Starting...'}</span>
		{:else if status && statusType !== 'info'}
			<span class="btn-status">{status}</span>
		{:else if files.length < MIN_IMAGES}
			Add at least {MIN_IMAGES} photos
		{:else}
			Generate Collage ({files.length} photos)
		{/if}
	</button>

	{#if imageUrl}
		<div class="image-preview">
			<img src={imageUrl} alt="Generated collage" />
			<div class="image-actions">
				<a href={imageUrl} download class="download-link">Download Collage</a>
				{#if timeRemaining}
					<span class="expiry-timer">{timeRemaining}</span>
				{/if}
				<button class="clear-btn" onclick={clearImage}>Clear</button>
			</div>
		</div>
	{/if}
</div>
