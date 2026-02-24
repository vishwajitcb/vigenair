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
    // Abort active multipart upload if in progress
    if (activeUpload && !activeUpload.aborted) {
        activeUpload.aborted = true;
        api.abortMultipartUpload(
            activeUpload.uploadId, activeUpload.folder, activeUpload.s3Key
        ).catch(err => console.warn('Abort cleanup error:', err));
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
        await handleMultipartUpload();
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

async function handleMultipartUpload() {
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

    updateProgress(0, 'Initiating upload...');

    try {
        // 1. Initiate
        const initResponse = await api.initiateMultipartUpload(
            selectedFile.name,
            selectedFile.size,
            selectedFile.type || 'video/mp4',
            analyzeAudio,
        );

        const { uploadId, folder, s3Key, presignedUrls, partSize, totalParts } = initResponse;

        activeUpload = { uploadId, folder, s3Key, aborted: false };

        // Save to localStorage for potential resume
        localStorage.setItem('activeMultipartUpload', JSON.stringify({
            uploadId, folder, s3Key, totalParts, partSize, fileName: selectedFile.name,
        }));

        updateProgress(1, `Uploading 0/${totalParts} parts...`);

        // 2. Upload parts with concurrency pool
        const CONCURRENCY = 4;
        const MAX_RETRIES = 3;
        const completedParts = [];
        let completedCount = 0;
        let partIndex = 0;

        async function uploadPart(partNum) {
            const start = (partNum - 1) * partSize;
            const end = Math.min(start + partSize, selectedFile.size);
            const blob = selectedFile.slice(start, end);
            const url = presignedUrls[partNum - 1];

            for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
                if (activeUpload && activeUpload.aborted) {
                    throw new Error('Upload aborted');
                }

                try {
                    const response = await fetch(url, {
                        method: 'PUT',
                        body: blob,
                    });

                    if (!response.ok) {
                        throw new Error(`Part ${partNum} failed: HTTP ${response.status}`);
                    }

                    const etag = response.headers.get('ETag');
                    return { ETag: etag, PartNumber: partNum };
                } catch (err) {
                    if (attempt === MAX_RETRIES || (activeUpload && activeUpload.aborted)) {
                        throw err;
                    }
                    // Exponential backoff: 1s, 2s, 4s
                    await new Promise(r => setTimeout(r, 1000 * Math.pow(2, attempt)));
                }
            }
        }

        // Worker pool
        async function worker() {
            while (true) {
                let myPartNum;
                // Grab next part atomically
                partIndex++;
                myPartNum = partIndex;
                if (myPartNum > totalParts) break;

                const result = await uploadPart(myPartNum);
                completedParts.push(result);
                completedCount++;

                const pct = (completedCount / totalParts) * 95;
                updateProgress(pct, `Uploading ${completedCount}/${totalParts} parts...`);
            }
        }

        const workers = [];
        for (let i = 0; i < Math.min(CONCURRENCY, totalParts); i++) {
            workers.push(worker());
        }
        await Promise.all(workers);

        if (activeUpload && activeUpload.aborted) {
            throw new Error('Upload aborted');
        }

        // 3. Complete
        updateProgress(96, 'Finalizing upload...');

        await api.completeMultipartUpload(uploadId, folder, s3Key, completedParts);

        // Cleanup
        localStorage.removeItem('activeMultipartUpload');
        activeUpload = null;

        updateProgress(100, 'Upload complete!');
        showToast('Video uploaded successfully!', 'success');

        setTimeout(() => {
            closeUploadModal();
            loadJobs();
        }, 500);

    } catch (error) {
        if (error.message === 'Upload aborted') {
            showToast('Upload cancelled', 'info');
        } else {
            showToast('Failed to upload video', 'error');
            console.error('Multipart upload error:', error);

            // Abort the upload on failure
            if (activeUpload && !activeUpload.aborted) {
                activeUpload.aborted = true;
                api.abortMultipartUpload(
                    activeUpload.uploadId, activeUpload.folder, activeUpload.s3Key
                ).catch(err => console.warn('Abort cleanup error:', err));
            }
        }

        localStorage.removeItem('activeMultipartUpload');
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
