/**
 * Job Detail Page Logic
 */

import { api } from '../api.js';
import {
    $, $$,
    formatDuration, formatDate,
    createStatusBadge, showToast,
    STAGE_LABELS, scoreToStars
} from '../utils.js';

// State
let job = null;
let folder = null;
let selectedVariantIndex = 0;
let pollInterval = null;

// Elements
const loadingState = $('#loadingState');
const processingState = $('#processingState');
const errorState = $('#errorState');
const mainContent = $('#mainContent');

// Initialize
document.addEventListener('DOMContentLoaded', init);

async function init() {
    // Get folder from URL
    const params = new URLSearchParams(window.location.search);
    folder = params.get('folder');

    if (!folder) {
        showError('No job specified');
        return;
    }

    setupEventListeners();
    await loadJob();
}

function setupEventListeners() {
    // Generate variants
    $('#generateBtn').addEventListener('click', handleGenerateVariants);

    // Prompt selection
    $('#promptSelect').addEventListener('change', (e) => {
        const customContainer = $('#customPromptContainer');
        if (e.target.value === 'custom') {
            customContainer.classList.remove('hidden');
        } else {
            customContainer.classList.add('hidden');
        }
    });

    // Duration slider
    $('#durationSlider').addEventListener('input', (e) => {
        $('#durationValue').textContent = `${e.target.value}s`;
    });

    // Advanced settings toggle
    $('#advancedToggle').addEventListener('click', () => {
        const settings = $('#advancedSettings');
        const icon = $('#advancedIcon');
        settings.classList.toggle('hidden');
        icon.classList.toggle('rotate-180');
    });

    // Number of variants slider
    $('#numVariantsSlider').addEventListener('input', (e) => {
        $('#numVariantsValue').textContent = e.target.value;
    });

    // Render button
    $('#renderBtn').addEventListener('click', handleStartRender);
}

async function loadJob() {
    try {
        const response = await api.getJob(folder);
        job = response.job;

        $('#jobName').textContent = job.name;
        $('#statusBadge').innerHTML = createStatusBadge(job.status);

        if (job.status === 'error') {
            // Check if we have segments - if yes, this is a render error (can retry)
            // If no, this is an extraction error (need to re-upload)
            if (job.segments && job.segments.length > 0) {
                // Render error - show main content with error notification
                showMainContent();
                showToast(job.error || 'Render failed. Please adjust settings and try again.', 'error');
            } else {
                // Extraction error - show error page (can't retry)
                showError(job.error || 'An error occurred during video processing');
            }
        } else if (job.status === 'processing' || job.status === 'rendering') {
            // Show progress UI for both processing and rendering
            showProcessing();
            startPolling();
        } else {
            showMainContent();
        }
    } catch (error) {
        showError('Failed to load job');
        console.error(error);
    } finally {
        loadingState.classList.add('hidden');
    }
}

function showError(message) {
    errorState.classList.remove('hidden');
    $('#errorMessage').textContent = message;
    processingState.classList.add('hidden');
    mainContent.classList.add('hidden');
}

function showProcessing() {
    processingState.classList.remove('hidden');
    errorState.classList.add('hidden');
    mainContent.classList.add('hidden');

    const stage = job.stage || 'uploading';
    const progress = job.progress || 0;

    $('#processingStage').textContent = STAGE_LABELS[stage] || 'Processing...';
    $('#processingProgress').style.width = `${progress}%`;
    $('#processingPercent').textContent = `${progress}%`;
}

function showMainContent() {
    mainContent.classList.remove('hidden');
    processingState.classList.add('hidden');
    errorState.classList.add('hidden');

    renderVideoPlayer();
    renderSegments();
    configureAudioModeOptions();

    if (job.variants && job.variants.length > 0) {
        selectedVariantIndex = job.selectedVariantIndex || 0;
        renderVariants();
        $('#variantsSection').classList.remove('hidden');
        $('#renderSection').classList.remove('hidden');
    }

    if (job.renders && job.renders.length > 0) {
        renderRenderedVideos();
        $('#rendersSection').classList.remove('hidden');
    }
}

/**
 * Configure audio mode options based on whether audio tracks were separated
 */
function configureAudioModeOptions() {
    const audioModeSelect = $('#audioMode');
    const hasAudioSeparation = checkAudioSeparationAvailable();

    if (!hasAudioSeparation) {
        // Remove music overlay option if audio wasn't separated
        const musicOption = Array.from(audioModeSelect.options).find(opt => opt.value === 'music');
        if (musicOption) {
            musicOption.disabled = true;
            musicOption.textContent += ' (Requires voice-over analysis)';
        }

        // If music was selected, switch to continuous audio
        if (audioModeSelect.value === 'music') {
            audioModeSelect.value = 'continuous';
            showToast('Audio mode changed to Continuous Audio (music overlay not available for this video)', 'info');
        }
    }

    // If there was a render error related to audio, show a warning
    if (job.status === 'error' && job.error && job.error.includes('Invalid file index')) {
        const warningDiv = document.createElement('div');
        warningDiv.className = 'mt-2 p-3 bg-yellow-50 border border-yellow-200 rounded-lg text-sm text-yellow-800';
        warningDiv.innerHTML = `
            <div class="flex items-start gap-2">
                <svg class="w-5 h-5 flex-shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/>
                </svg>
                <div>
                    <strong>Previous render failed:</strong> Music overlay requires voice-over analysis. Please select "Continuous Audio" or "Segment Audio" instead.
                </div>
            </div>
        `;
        audioModeSelect.parentElement.appendChild(warningDiv);
    }
}

/**
 * Check if audio separation is available for this video
 * Videos uploaded with --w flag won't have separated audio tracks
 */
function checkAudioSeparationAvailable() {
    // Check if the folder name contains --w-- flag
    if (folder && folder.includes('--w--')) {
        return false;
    }

    // Could also check if job has metadata indicating separation
    if (job && job.metadata && job.metadata.audioSeparated === false) {
        return false;
    }

    return true; // Assume available by default
}

function renderVideoPlayer() {
    const video = $('#videoPlayer');
    if (job.inputVideoUrl) {
        video.src = job.inputVideoUrl;
    }
}

function renderSegments() {
    const strip = $('#segmentsStrip');
    const segments = job.segments || [];

    if (segments.length === 0) {
        strip.innerHTML = '<p class="text-gray-500 text-sm">No segments available</p>';
        return;
    }

    strip.innerHTML = segments.map((seg, idx) => `
        <div class="segment-thumb flex-shrink-0 cursor-pointer group" data-id="${seg.id}">
            <div class="w-24 h-16 rounded-lg overflow-hidden bg-gray-200 relative">
                ${seg.thumbnailUrl
                    ? `<img src="${seg.thumbnailUrl}" class="w-full h-full object-cover" alt="Segment ${idx}">`
                    : `<div class="w-full h-full bg-gradient-to-br from-primary/20 to-secondary/20"></div>`
                }
                <div class="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-xs px-1 py-0.5">
                    ${formatDuration(seg.duration)}
                </div>
            </div>
            <p class="text-xs text-gray-500 mt-1 truncate w-24" title="${seg.description || ''}">
                ${seg.description || `Segment ${idx + 1}`}
            </p>
        </div>
    `).join('');

    // Click to play segment
    $$('.segment-thumb').forEach(thumb => {
        thumb.addEventListener('click', () => {
            const segId = thumb.dataset.id;
            const segment = segments.find(s => s.id === segId);
            if (segment && segment.videoUrl) {
                const video = $('#videoPlayer');
                video.src = segment.videoUrl;
                video.play();
            }
        });
    });
}

async function handleGenerateVariants() {
    const btn = $('#generateBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = '<span class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full mr-2"></span>Generating...';

    try {
        const promptOption = $('#promptSelect').value;
        const targetDuration = parseInt($('#durationSlider').value, 10);
        const customPrompt = $('#customPrompt').value;
        const numVariants = parseInt($('#numVariantsSlider').value, 10);
        const businessObjective = $('#businessObjective').value || null;
        const shortenVideo = $('#shortenVideo').checked;

        const prompt = promptOption === 'custom' ? customPrompt : getPromptTemplate(promptOption, shortenVideo);

        const response = await api.generateVariants(folder, {
            prompt,
            target_duration: targetDuration,
            num_variants: numVariants,
            business_objective: businessObjective,
            shorten_video: shortenVideo,
        });

        if (response.error) {
            throw new Error(response.error);
        }

        // Convert to our variant format
        const variants = (response.variants || []).map((v, idx) => ({
            id: idx,
            title: v.title || `Variant ${idx + 1}`,
            description: v.description || '',
            score: v.score || 3,
            reasoning: v.reasoning || '',
            segments: (v.scenes || v.segments || []).map(s => String(s)),
            duration: v.estimated_duration || targetDuration,
            userModified: false,
        }));

        // Save to MongoDB
        await api.updateJobVariants(folder, variants, 0, {
            promptOption,
            customPrompt,
            targetDuration,
            shortenVideo,
            businessObjective,
        });

        job.variants = variants;
        job.selectedVariantIndex = 0;
        selectedVariantIndex = 0;

        renderVariants();
        $('#variantsSection').classList.remove('hidden');
        $('#renderSection').classList.remove('hidden');

        showToast('Variants generated!', 'success');

    } catch (error) {
        showToast('Failed to generate variants', 'error');
        console.error(error);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

function getPromptTemplate(option, shortenVideo = true) {
    const templates = {
        default: 'Create balanced video variants that maintain the key message while being engaging.',
        highlight: 'Focus on the most impactful moments and key highlights of the video.',
        engaging: 'Create variants with strong hooks that capture viewer attention immediately.',
        professional: 'Create professional, business-focused variants suitable for B2B marketing.',
        social: 'Optimize for social media platforms with quick, punchy edits.',
        'crop-only': 'Create variants that only adjust aspect ratio without shortening the video. Include all original segments in their original order.',
    };

    let prompt = templates[option] || templates.default;

    // If shortenVideo is false, append instruction to keep all content
    if (!shortenVideo && option !== 'crop-only') {
        prompt += ' Keep all original segments - do not shorten the video, only adjust for aspect ratio.';
    }

    return prompt;
}

function renderVariants() {
    const variants = job.variants || [];
    if (variants.length === 0) return;

    // Tabs
    const tabs = $('#variantTabs');
    tabs.innerHTML = variants.map((v, idx) => `
        <button class="variant-tab px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            idx === selectedVariantIndex
                ? 'bg-primary text-white'
                : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
        }" data-idx="${idx}">
            V${idx + 1} ${scoreToStars(v.score)}
        </button>
    `).join('');

    // Tab click handlers
    $$('.variant-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            selectedVariantIndex = parseInt(tab.dataset.idx, 10);
            renderVariants();
            // Save selection to MongoDB
            api.updateJobUI(folder, { ...job.ui, selectedVariantIndex });
        });
    });

    // Content
    const variant = variants[selectedVariantIndex];
    const content = $('#variantContent');
    content.innerHTML = `
        <div class="space-y-4">
            <div>
                <h3 class="text-lg font-semibold text-gray-900">${variant.title}</h3>
                <div class="flex items-center gap-4 mt-1 text-sm text-gray-500">
                    <span>Score: ${variant.score}/5 ${scoreToStars(variant.score)}</span>
                    <span>Duration: ~${formatDuration(variant.duration)}</span>
                    <span>Segments: ${variant.segments.length}</span>
                </div>
            </div>
            ${variant.description ? `<p class="text-gray-600">${variant.description}</p>` : ''}
            ${variant.reasoning ? `
                <div class="bg-gray-50 rounded-lg p-4">
                    <h4 class="text-sm font-medium text-gray-700 mb-1">AI Reasoning</h4>
                    <p class="text-sm text-gray-600">${variant.reasoning}</p>
                </div>
            ` : ''}
            <div>
                <h4 class="text-sm font-medium text-gray-700 mb-2">Selected Segments</h4>
                <div class="flex flex-wrap gap-2">
                    ${variant.segments.map(segId => {
                        const seg = (job.segments || []).find(s => s.id === segId);
                        return `
                            <span class="px-2 py-1 bg-primary/10 text-primary rounded text-sm">
                                ${seg ? seg.description?.substring(0, 30) + '...' : `Segment ${segId}`}
                            </span>
                        `;
                    }).join('')}
                </div>
            </div>
        </div>
    `;
}

async function handleStartRender() {
    const btn = $('#renderBtn');
    const originalText = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = '<span class="animate-spin inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full mr-2"></span>Starting render...';

    try {
        const formats = Array.from($$('input[name="format"]:checked')).map(cb => cb.value);
        const audioMode = $('#audioMode').value;

        if (formats.length === 0) {
            showToast('Please select at least one format', 'warning');
            return;
        }

        const variant = job.variants[selectedVariantIndex];
        if (!variant) {
            showToast('Please select a variant first', 'warning');
            return;
        }

        // Validate audio mode selection
        if (audioMode === 'music' && !checkAudioSeparationAvailable()) {
            showToast('Music overlay requires voice-over analysis. Please select a different audio mode.', 'warning');
            // Auto-switch to continuous audio
            $('#audioMode').value = 'continuous';
            return;
        }

        await api.startRender(folder, {
            variants: [{
                ...variant,
                formats,
                audioMode,
            }],
            settings: {
                formats,
                audioMode,
            },
        });

        showToast('Render started!', 'success');

        // Start polling for render completion
        startPolling();

    } catch (error) {
        showToast('Failed to start render', 'error');
        console.error(error);
    } finally {
        btn.disabled = false;
        btn.textContent = originalText;
    }
}

function renderRenderedVideos() {
    const renders = job.renders || [];
    const list = $('#rendersList');

    if (renders.length === 0) {
        list.innerHTML = '<p class="text-gray-500 text-sm">No rendered videos yet.</p>';
        return;
    }

    list.innerHTML = renders.map((render, renderIdx) => `
        <div class="border border-gray-200 rounded-lg overflow-hidden bg-white">
            <div class="p-4 border-b border-gray-100">
                <h4 class="font-medium text-gray-900">${render.title || `Render ${renderIdx + 1}`}</h4>
                ${render.description ? `<p class="text-sm text-gray-500 mt-1">${render.description}</p>` : ''}
                <p class="text-xs text-gray-400 mt-1">${formatDate(render.createdAt)}</p>
            </div>
            <div class="p-4">
                <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                    ${Object.entries(render.formats || {}).map(([format, data]) => `
                        <div class="space-y-2">
                            <div class="aspect-video bg-black rounded-lg overflow-hidden">
                                <video class="w-full h-full object-contain" controls preload="metadata">
                                    <source src="${data.url || ''}" type="video/mp4">
                                </video>
                            </div>
                            <div class="flex items-center justify-between">
                                <span class="text-sm font-medium text-gray-700">${format}</span>
                                <a href="${data.url || '#'}"
                                   download="${render.title || 'video'}_${format.replace(':', 'x')}.mp4"
                                   class="text-sm text-primary hover:text-indigo-600 flex items-center gap-1">
                                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path>
                                    </svg>
                                    Download
                                </a>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
        </div>
    `).join('');
}

// Polling
function startPolling() {
    if (pollInterval) return;

    pollInterval = setInterval(async () => {
        try {
            const response = await api.getJob(folder);
            const newJob = response.job;

            // Check if status, stage, or progress changed
            if (newJob.status !== job.status ||
                newJob.progress !== job.progress ||
                newJob.stage !== job.stage) {
                job = newJob;
                $('#statusBadge').innerHTML = createStatusBadge(job.status);

                if (job.status === 'error') {
                    stopPolling();
                    showError(job.error || 'An error occurred');
                } else if (job.status === 'processing' || job.status === 'rendering') {
                    // Show progress UI for both processing and rendering
                    showProcessing();
                } else if (job.status === 'complete') {
                    // Render completed
                    stopPolling();
                    showMainContent();
                    showToast('Render complete!', 'success');
                } else {
                    // segments_ready, variants_generated, etc.
                    showMainContent();
                    stopPolling();
                }
            }
        } catch (error) {
            console.error('Polling error:', error);
        }
    }, 3000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

// Cleanup
window.addEventListener('beforeunload', stopPolling);
