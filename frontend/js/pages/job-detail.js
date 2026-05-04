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

// Stable id for a variant based on its content (title + sorted segments).
// Same content -> same id, different content -> different id.
// Using FNV-1a 32-bit so the result fits in a short hex string safe for use
// in GCS keys and filenames.
function hashVariantId(title, segments) {
    const sortedSegs = [...(segments || [])].map(String).sort().join(',');
    const input = `${title || ''}|${sortedSegs}`;
    let hash = 0x811c9dc5;
    for (let i = 0; i < input.length; i++) {
        hash ^= input.charCodeAt(i);
        hash = (hash + ((hash << 1) + (hash << 4) + (hash << 7) + (hash << 8) + (hash << 24))) >>> 0;
    }
    // No underscore: filename parsing in service/combiner/combiner.py:288 splits
    // on '_' to recover variant_id, and our id must survive that split intact.
    return 'v' + hash.toString(16).padStart(8, '0');
}

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

        // Load segments for display in variant chips
        try {
            const segResponse = await api.getSegments(folder);
            job.segments = (segResponse.data && Array.isArray(segResponse.data))
                ? segResponse.data
                : (segResponse.data?.av_segments || []);
        } catch (_) {
            job.segments = [];
        }

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
    configureAudioModeOptions();

    if (job.variants && job.variants.length > 0) {
        // Normalize scores for existing variants (fix old data with scores > 5)
        job.variants = job.variants.map(v => {
            let normalizedScore = v.score || 3;
            if (normalizedScore > 5) {
                normalizedScore = Math.min(5, Math.max(0, (normalizedScore / 100) * 5));
                normalizedScore = Math.round(normalizedScore * 10) / 10;
            }
            return { ...v, score: normalizedScore };
        });

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
            prompt_option: promptOption,
            custom_prompt: customPrompt,
            business_objective: businessObjective,
            shorten_video: shortenVideo,
        });

        if (response.error) {
            throw new Error(response.error);
        }

        // Convert to our variant format
        const variants = (response.variants || []).map((v, idx) => {
            // Normalize score to a 0-5 star scale.
            // Backend stamps `score_max` (17/16/18 for ABCD rubrics, 100 for narrative).
            // Fall back to 100 for old responses that lacked the field.
            const rawScore = typeof v.score === 'number' ? v.score : 3;
            const scoreMax = typeof v.score_max === 'number' && v.score_max > 0 ? v.score_max : 100;
            let normalizedScore;
            if (rawScore <= 5 && scoreMax === 100) {
                // Already on a 0-5 scale (legacy / fallback default).
                normalizedScore = rawScore;
            } else {
                normalizedScore = Math.min(5, Math.max(0, (rawScore / scoreMax) * 5));
            }
            normalizedScore = Math.round(normalizedScore * 10) / 10;

            const title = v.title || `Variant ${idx + 1}`;
            const segments = (v.scenes || v.segments || []).map(s => String(s));
            return {
                id: hashVariantId(title, segments),
                title,
                description: v.description || '',
                score: normalizedScore,
                reasoning: v.reasoning || '',
                segments,
                duration: v.estimated_duration || targetDuration,
                userModified: false,
                angle: v.angle || null,
                hook_scene: typeof v.hook_scene === 'number' ? v.hook_scene : null,
                structure: v.structure || null,
            };
        });

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
            <div>
                <h4 class="text-sm font-medium text-gray-700 mb-2">Selected Segments</h4>
                <div class="flex flex-wrap gap-2">
                    ${variant.segments.map(segId => {
                        const idx = parseInt(segId, 10) - 1;
                        const seg = (job.segments || [])[idx];
                        const label = seg
                            ? (seg.description || seg.av_segment_id || `Segment ${segId}`).substring(0, 30) + '...'
                            : `Segment ${segId}`;
                        return `
                            <span class="px-2 py-1 bg-primary/10 text-primary rounded text-sm">
                                ${label}
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
        const exportAsXml = $('#exportAsXml')?.checked === true;
        const formats = Array.from($$('input[name="format"]:checked')).map(cb => cb.value);
        const audioMode = $('#audioMode').value;

        if (!exportAsXml && formats.length === 0) {
            showToast('Please select at least one format', 'warning');
            return;
        }

        const variant = job.variants[selectedVariantIndex];
        if (!variant) {
            showToast('Please select a variant first', 'warning');
            return;
        }

        // Validate audio mode selection (only for video output)
        if (!exportAsXml && audioMode === 'music' && !checkAudioSeparationAvailable()) {
            showToast('Music overlay requires voice-over analysis. Please select a different audio mode.', 'warning');
            // Auto-switch to continuous audio
            $('#audioMode').value = 'continuous';
            return;
        }

        const outputType = exportAsXml ? 'xml' : 'video';
        await api.startRender(folder, {
            variants: [{
                ...variant,
                formats,
                audioMode,
                outputType,
            }],
            settings: {
                formats,
                audioMode,
            },
            output_type: outputType,
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

    list.innerHTML = renders.map((render, renderIdx) => {
        if (render.outputType === 'xml') {
            const zipUrl = render.formats?.zip?.url || '';
            const downloadName = render.formats?.zip?.downloadName
                || ((render.title || 'variant').replace(/[^A-Za-z0-9_-]+/g, '_') + '.zip');
            return `
        <div class="border border-gray-200 rounded-lg overflow-hidden bg-white">
            <div class="p-4 border-b border-gray-100">
                <div class="flex items-center gap-2">
                    <span class="inline-block px-2 py-0.5 text-xs font-semibold bg-indigo-100 text-indigo-700 rounded">Premiere bundle</span>
                    <h4 class="font-medium text-gray-900">${render.title || `Render ${renderIdx + 1}`}</h4>
                </div>
                ${render.description ? `<p class="text-sm text-gray-500 mt-1">${render.description}</p>` : ''}
                <p class="text-xs text-gray-400 mt-1">${formatDate(render.createdAt)}</p>
            </div>
            <div class="p-4 space-y-3">
                <p class="text-sm text-gray-600">
                    Unzip the bundle, then in Adobe Premiere Pro or DaVinci Resolve: File &rarr; Import &rarr; the <code>*_timeline.xml</code> file.
                    The <code>media/</code> and <code>music/</code> folders next to it contain pre-cut video and audio clips per segment.
                </p>
                <div class="flex flex-wrap gap-2">
                    <a href="${zipUrl}" download="${downloadName}"
                       class="inline-flex items-center gap-1 bg-primary hover:bg-indigo-600 text-white px-4 py-2 rounded-lg text-sm font-medium">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"></path></svg>
                        Download Premiere bundle (.zip)
                    </a>
                </div>
            </div>
        </div>
            `;
        }
        return `
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
        `;
    }).join('');
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
