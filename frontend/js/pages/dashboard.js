/**
 * Dashboard Page Logic
 */

import { api } from '../api.js';
import {
    $, $$,
    formatDate, formatRelativeTime, formatFileSize,
    createStatusBadge, showToast, debounce
} from '../utils.js';

// State
let jobs = [];
let selectedFile = null;
let currentPage = 1;
let totalJobs = 0;
let isLoading = false;
let pollInterval = null;
let activeUpload = null;

const MULTIPART_THRESHOLD = 100 * 1024 * 1024; // 100 MB
const PARALLEL_PART_TARGET_SIZE = 256 * 1024 * 1024; // 256 MB per part

// Elements
const jobsGrid = $('#jobsGrid');
const emptyState = $('#emptyState');
const loadingState = $('#loadingState');
const uploadModal = $('#uploadModal');
const searchInput = $('#searchInput');
const statusFilter = $('#statusFilter');
const sortSelect = $('#sortSelect');

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
    setupEventListeners();
    await loadJobs();
    startPolling();
}

function setupEventListeners() {
    // Upload buttons
    $('#uploadBtn').addEventListener('click', openUploadModal);
    $('#emptyUploadBtn')?.addEventListener('click', openUploadModal);

    // Modal
    $('#closeModal').addEventListener('click', closeUploadModal);
    $('#cancelUpload').addEventListener('click', closeUploadModal);
    uploadModal.addEventListener('click', (e) => {
        if (e.target === uploadModal) closeUploadModal();
    });

    // File input
    const dropZone = $('#dropZone');
    const fileInput = $('#fileInput');

    dropZone.addEventListener('click', () => fileInput.click());
    dropZone.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropZone.classList.add('border-primary', 'bg-primary/5');
    });
    dropZone.addEventListener('dragleave', () => {
        dropZone.classList.remove('border-primary', 'bg-primary/5');
    });
    dropZone.addEventListener('drop', (e) => {
        e.preventDefault();
        dropZone.classList.remove('border-primary', 'bg-primary/5');
        if (e.dataTransfer.files.length) {
            handleFileSelect(e.dataTransfer.files[0]);
        }
    });

    fileInput.addEventListener('change', (e) => {
        if (e.target.files.length) {
            handleFileSelect(e.target.files[0]);
        }
    });

    $('#removeFile').addEventListener('click', clearSelectedFile);
    $('#startUpload').addEventListener('click', handleUpload);

    // Filters
    searchInput.addEventListener('input', debounce(() => {
        currentPage = 1;
        loadJobs();
    }, 300));

    statusFilter.addEventListener('change', () => {
        currentPage = 1;
        loadJobs();
    });

    sortSelect.addEventListener('change', () => {
        currentPage = 1;
        loadJobs();
    });
}

async function loadJobs() {
    if (isLoading) return;
    isLoading = true;

    try {
        const [sortField, sortOrder] = sortSelect.value.split('-');

        const response = await api.listJobs({
            search: searchInput.value || undefined,
            status: statusFilter.value || undefined,
            sort: sortField,
            order: sortOrder,
            page: currentPage,
            pageSize: 20,
        });

        jobs = response.jobs;
        totalJobs = response.total;

        renderJobs();
    } catch (error) {
        showToast('Failed to load jobs', 'error');
        console.error(error);
    } finally {
        isLoading = false;
        loadingState.classList.add('hidden');
    }
}

function renderJobs() {
    if (jobs.length === 0) {
        jobsGrid.classList.add('hidden');
        emptyState.classList.remove('hidden');
        return;
    }

    emptyState.classList.add('hidden');
    jobsGrid.classList.remove('hidden');

    jobsGrid.innerHTML = jobs.map(job => createJobCard(job)).join('');

    // Add click handlers
    $$('.job-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (!e.target.closest('.delete-btn')) {
                window.location.href = `job.html?folder=${encodeURIComponent(card.dataset.folder)}`;
            }
        });
    });

    $$('.delete-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            handleDeleteJob(btn.dataset.folder);
        });
    });
}

function createJobCard(job) {
    const thumbnailBg = job.thumbnailUrl
        ? `background-image: url('${job.thumbnailUrl}')`
        : '';

    // Check if voice-over analysis was skipped (--w-- flag in folder name)
    const voiceOverSkipped = job.folder && job.folder.includes('--w--');
    const indicatorColor = voiceOverSkipped ? 'bg-red-500' : 'bg-green-500';
    const indicatorTitle = voiceOverSkipped ? 'Voice-over analysis skipped' : 'Voice-over analysis enabled';

    return `
        <div class="job-card bg-white rounded-xl shadow-sm border border-gray-200 overflow-hidden cursor-pointer hover:shadow-md transition-shadow"
             data-folder="${job.folder}">
            <div class="aspect-video bg-cover bg-center relative" style="${thumbnailBg}">
                ${!job.thumbnailUrl ? `
                    <div class="absolute inset-0 flex items-center justify-center bg-gradient-to-br from-indigo-500 via-purple-500 to-pink-500">
                        <svg class="w-16 h-16 text-white/90" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"></path>
                        </svg>
                        <div class="absolute inset-0 bg-black/5"></div>
                    </div>
                ` : ''}
                <div class="absolute top-2 right-2 w-2 h-2 rounded-full ${indicatorColor}" title="${indicatorTitle}"></div>
            </div>
            <div class="p-4">
                <h3 class="font-medium text-gray-900 truncate mb-1">${job.name}</h3>
                <div class="flex items-center justify-between">
                    ${createStatusBadge(job.status)}
                    <span class="text-xs text-gray-400">${formatRelativeTime(job.createdAt)}</span>
                </div>
                <div class="flex items-center justify-between mt-3 pt-3 border-t border-gray-100">
                    <div class="flex items-center gap-2 text-xs text-gray-500">
                        ${job.variantCount > 0 ? `<span>${job.variantCount} variants</span>` : ''}
                        ${job.renderCount > 0 ? `<span>${job.renderCount} renders</span>` : ''}
                    </div>
                    <button class="delete-btn text-gray-400 hover:text-red-500 p-1" data-folder="${job.folder}">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                        </svg>
                    </button>
                </div>
            </div>
        </div>
    `;
}

async function handleDeleteJob(folder) {
    if (!confirm('Are you sure you want to delete this job? This cannot be undone.')) {
        return;
    }

    try {
        await api.deleteJob(folder);
        showToast('Job deleted', 'success');
        await loadJobs();
    } catch (error) {
        showToast('Failed to delete job', 'error');
        console.error(error);
    }
}

// Upload Modal
function openUploadModal() {
    uploadModal.classList.remove('hidden');
    uploadModal.classList.add('flex');
}

function closeUploadModal() {
    // Abort active upload if in progress
    if (activeUpload && !activeUpload.aborted) {
        activeUpload.aborted = true;

        // Abort all in-flight fetch requests
        if (activeUpload.abortControllers) {
            activeUpload.abortControllers.forEach(c => c.abort());
        }

        if (activeUpload.numParts) {
            api.abortParallelUpload(
                activeUpload.folder, activeUpload.objectKey, activeUpload.numParts
            ).catch(err => console.warn('Abort cleanup error:', err));
        } else {
            api.abortResumableUpload(
                activeUpload.folder, activeUpload.objectKey
            ).catch(err => console.warn('Abort cleanup error:', err));
        }
        activeUpload = null;
    }

    uploadModal.classList.add('hidden');
    uploadModal.classList.remove('flex');
    clearSelectedFile();
    $('#uploadProgress').classList.add('hidden');
    const statusLabel = $('#uploadStatusLabel');
    if (statusLabel) statusLabel.textContent = 'Uploading...';
}

function handleFileSelect(file) {
    if (!file.type.startsWith('video/')) {
        showToast('Please select a video file', 'error');
        return;
    }

    selectedFile = file;
    $('#fileName').textContent = file.name;
    $('#fileSize').textContent = formatFileSize(file.size);
    $('#selectedFile').classList.remove('hidden');
    $('#dropZone').classList.add('hidden');
    $('#startUpload').disabled = false;
}

function clearSelectedFile() {
    selectedFile = null;
    $('#selectedFile').classList.add('hidden');
    $('#dropZone').classList.remove('hidden');
    $('#startUpload').disabled = true;
    $('#fileInput').value = '';
}

async function handleUpload() {
    if (!selectedFile) return;

    if (selectedFile.size > MULTIPART_THRESHOLD) {
        await handleParallelUpload();
    } else {
        await handleSimpleUpload();
    }
}

async function handleSimpleUpload() {
    const analyzeAudio = $('#analyzeAudio').checked;
    const progressDiv = $('#uploadProgress');
    const progressBar = $('#progressBar');
    const progressPercent = $('#progressPercent');

    progressDiv.classList.remove('hidden');
    $('#startUpload').disabled = true;

    let progress = 0;
    const progressInterval = setInterval(() => {
        progress = Math.min(progress + Math.random() * 20, 90);
        progressBar.style.width = `${progress}%`;
        progressPercent.textContent = `${Math.round(progress)}%`;
    }, 500);

    try {
        await api.uploadVideo(selectedFile, analyzeAudio);

        clearInterval(progressInterval);
        progressBar.style.width = '100%';
        progressPercent.textContent = '100%';

        showToast('Video uploaded successfully!', 'success');

        setTimeout(() => {
            closeUploadModal();
            loadJobs();
        }, 500);

    } catch (error) {
        clearInterval(progressInterval);
        showToast('Failed to upload video', 'error');
        console.error(error);
        $('#startUpload').disabled = false;
        progressDiv.classList.add('hidden');
    }
}

async function handleParallelUpload() {
    const analyzeAudio = $('#analyzeAudio').checked;
    const progressDiv = $('#uploadProgress');
    const progressBar = $('#progressBar');
    const progressPercent = $('#progressPercent');
    const statusLabel = $('#uploadStatusLabel');

    progressDiv.classList.remove('hidden');
    $('#startUpload').disabled = true;

    function updateProgress(pct, label) {
        progressBar.style.width = `${pct}%`;
        progressPercent.textContent = `${Math.round(pct)}%`;
        if (statusLabel && label) statusLabel.textContent = label;
    }

    updateProgress(0, 'Initiating parallel upload...');
    let firstError = null;

    try {
        // 1. Calculate number of parts
        const numParts = Math.max(2, Math.min(
            Math.ceil(selectedFile.size / PARALLEL_PART_TARGET_SIZE), 20
        ));

        // 2. Initiate parallel upload — get signed URLs for each part
        const initResponse = await api.initiateParallelUpload(
            selectedFile.name,
            selectedFile.size,
            selectedFile.type || 'video/mp4',
            analyzeAudio,
            numParts,
        );

        const { folder, objectKey, parts, maxConcurrentParts = 6 } = initResponse;
        const actualNumParts = parts.length;

        const abortControllers = [];
        activeUpload = { folder, objectKey, numParts: actualNumParts, aborted: false, abortControllers };

        updateProgress(1, `Uploading 0/${actualNumParts} parts...`);

        // 3. Track per-part progress
        const partBytesUploaded = new Array(actualNumParts).fill(0);
        let completedParts = 0;

        function refreshProgress() {
            const totalUploaded = partBytesUploaded.reduce((a, b) => a + b, 0);
            const pct = (totalUploaded / selectedFile.size) * 95; // reserve 5% for compose
            updateProgress(pct, `Uploading ${completedParts}/${actualNumParts} parts...`);
        }

        // 4. Upload a single part via signed URL (one PUT per part)
        async function uploadPart(part) {
            const MAX_RETRIES = 3;
            const partBlob = selectedFile.slice(part.offset, part.offset + part.size);

            for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
                if (activeUpload && activeUpload.aborted) return;

                const controller = new AbortController();
                abortControllers.push(controller);

                try {
                    const response = await fetch(part.signedUrl, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/octet-stream' },
                        body: partBlob,
                        signal: controller.signal,
                    });

                    if (response.ok) {
                        partBytesUploaded[part.partIndex] = part.size;
                        completedParts++;
                        refreshProgress();
                        return;
                    }

                    const body = await response.text().catch(() => '');
                    console.error(`Part ${part.partIndex} attempt ${attempt}: HTTP ${response.status} ${body}`);
                    if (attempt === MAX_RETRIES) {
                        throw new Error(`Part ${part.partIndex} failed: HTTP ${response.status}`);
                    }
                } catch (err) {
                    if (err.name === 'AbortError' || (activeUpload && activeUpload.aborted)) return;
                    console.error(`Part ${part.partIndex} attempt ${attempt}:`, err.message);
                    if (attempt === MAX_RETRIES) throw err;
                }

                await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt)));
            }
        }

        // 5. Run parts with concurrency limit
        const partQueue = [...parts];
        const workers = [];

        async function worker() {
            while (partQueue.length > 0) {
                if (activeUpload && activeUpload.aborted) return;
                const part = partQueue.shift();
                if (!part) return;
                try {
                    await uploadPart(part);
                } catch (err) {
                    if (!firstError) firstError = err;
                    if (activeUpload) activeUpload.aborted = true;
                    abortControllers.forEach(c => c.abort());
                    return;
                }
            }
        }

        for (let i = 0; i < Math.min(maxConcurrentParts, actualNumParts); i++) {
            workers.push(worker());
        }

        await Promise.all(workers);

        if (firstError) throw firstError;

        if (activeUpload && activeUpload.aborted) {
            throw new Error('Upload aborted');
        }

        // 6. Compose — trigger backend to compose parts and start processing
        updateProgress(96, 'Composing parts...');

        await api.completeParallelUpload(folder, objectKey, actualNumParts);

        activeUpload = null;

        updateProgress(100, 'Upload complete!');
        showToast('Video uploaded successfully!', 'success');

        setTimeout(() => {
            closeUploadModal();
            loadJobs();
        }, 500);

    } catch (error) {
        const wasUserCancel = error.message === 'Upload aborted';

        if (wasUserCancel) {
            showToast('Upload cancelled', 'info');
        } else {
            console.error('Parallel upload error:', error.name, error.message, error.stack);
            showToast(`Upload failed: ${error.message}`, 'error');
        }

        if (activeUpload) {
            if (!activeUpload.aborted) {
                activeUpload.aborted = true;
                if (activeUpload.abortControllers) {
                    activeUpload.abortControllers.forEach(c => c.abort());
                }
            }
            api.abortParallelUpload(
                activeUpload.folder, activeUpload.objectKey, activeUpload.numParts
            ).catch(err => console.warn('Abort cleanup error:', err));
        }

        activeUpload = null;
        $('#startUpload').disabled = false;
        progressDiv.classList.add('hidden');
        if (statusLabel) statusLabel.textContent = 'Uploading...';
    }
}

// Polling for status updates
function startPolling() {
    pollInterval = setInterval(async () => {
        const hasProcessingJobs = jobs.some(j =>
            j.status === 'processing' || j.status === 'rendering'
        );

        if (hasProcessingJobs) {
            await loadJobs();
        }
    }, 5000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

// Cleanup on page unload
window.addEventListener('beforeunload', stopPolling);
