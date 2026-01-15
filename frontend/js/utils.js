/**
 * Utility functions for ViGenAiR
 */

// DOM helpers
export const $ = (selector) => document.querySelector(selector);
export const $$ = (selector) => document.querySelectorAll(selector);

// Format seconds to mm:ss
export function formatDuration(seconds) {
    if (!seconds || isNaN(seconds)) return '0:00';
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

// Format date
export function formatDate(dateString) {
    if (!dateString) return '';
    const date = new Date(dateString);
    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: date.getFullYear() !== new Date().getFullYear() ? 'numeric' : undefined,
    });
}

// Format relative time
export function formatRelativeTime(dateString) {
    if (!dateString) return '';
    const date = new Date(dateString);
    const now = new Date();
    const diffMs = now - date;
    const diffMins = Math.floor(diffMs / 60000);
    const diffHours = Math.floor(diffMs / 3600000);
    const diffDays = Math.floor(diffMs / 86400000);

    if (diffMins < 1) return 'Just now';
    if (diffMins < 60) return `${diffMins}m ago`;
    if (diffHours < 24) return `${diffHours}h ago`;
    if (diffDays < 7) return `${diffDays}d ago`;
    return formatDate(dateString);
}

// Format file size
export function formatFileSize(bytes) {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    let unitIndex = 0;
    let size = bytes;
    while (size >= 1024 && unitIndex < units.length - 1) {
        size /= 1024;
        unitIndex++;
    }
    return `${size.toFixed(1)} ${units[unitIndex]}`;
}

// Status badge colors and labels
export const STATUS_CONFIG = {
    processing: { color: 'bg-yellow-100 text-yellow-800', label: 'Processing', icon: 'animate-spin' },
    segments_ready: { color: 'bg-blue-100 text-blue-800', label: 'Segments Ready', icon: '' },
    variants_generated: { color: 'bg-purple-100 text-purple-800', label: 'Variants Ready', icon: '' },
    rendering: { color: 'bg-orange-100 text-orange-800', label: 'Rendering', icon: 'animate-spin' },
    complete: { color: 'bg-green-100 text-green-800', label: 'Complete', icon: '' },
    error: { color: 'bg-red-100 text-red-800', label: 'Error', icon: '' },
};

// Stage labels
export const STAGE_LABELS = {
    uploading: 'Uploading video...',
    extracting_audio: 'Extracting audio...',
    transcribing: 'Transcribing voice-over...',
    analyzing: 'Analyzing video...',
    creating_segments: 'Creating segments...',
    done: 'Complete',
    // Render stages
    render_preparing: 'Preparing render...',
    render_cropping: 'Cropping video for formats...',
    render_encoding: 'Encoding video...',
    render_uploading: 'Uploading rendered files...',
    render_finalizing: 'Finalizing render...',
};

// Create status badge HTML
export function createStatusBadge(status) {
    const config = STATUS_CONFIG[status] || STATUS_CONFIG.processing;
    return `
        <span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${config.color}">
            ${config.icon ? `<span class="w-3 h-3 border-2 border-current border-t-transparent rounded-full ${config.icon}"></span>` : ''}
            ${config.label}
        </span>
    `;
}

// Debounce function
export function debounce(fn, delay) {
    let timeoutId;
    return function (...args) {
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => fn.apply(this, args), delay);
    };
}

// Toast notifications
export function showToast(message, type = 'info') {
    const container = $('#toastContainer');
    if (!container) return;

    const colors = {
        success: 'bg-green-500',
        error: 'bg-red-500',
        warning: 'bg-yellow-500',
        info: 'bg-blue-500',
    };

    const toast = document.createElement('div');
    toast.className = `${colors[type]} text-white px-4 py-3 rounded-lg shadow-lg flex items-center gap-2 transform translate-x-full transition-transform duration-300`;
    toast.innerHTML = `
        <span>${message}</span>
        <button class="ml-2 hover:opacity-75" onclick="this.parentElement.remove()">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
        </button>
    `;

    container.appendChild(toast);

    // Animate in
    requestAnimationFrame(() => {
        toast.classList.remove('translate-x-full');
    });

    // Auto remove after 5 seconds
    setTimeout(() => {
        toast.classList.add('translate-x-full');
        setTimeout(() => toast.remove(), 300);
    }, 5000);
}

// Score to stars
export function scoreToStars(score, maxScore = 5) {
    // Handle scores > 5 (e.g., scores out of 100)
    if (score > 5) {
        maxScore = 100;
    }
    const normalizedScore = Math.min(5, Math.max(0, Math.round((score / maxScore) * 5)));
    return '★'.repeat(normalizedScore) + '☆'.repeat(5 - normalizedScore);
}

// Parse folder name to get metadata
export function parseFolderName(folder) {
    const parts = folder.split('--');
    if (parts.length < 4) {
        return { name: folder, timestamp: Date.now(), userId: 'unknown' };
    }
    return {
        name: parts[0],
        transcriptionService: parts[1],
        timestamp: parseInt(parts[2], 10),
        userId: parts[3].replace(/_at_/g, '@').replace(/_dot_/g, '.'),
    };
}
