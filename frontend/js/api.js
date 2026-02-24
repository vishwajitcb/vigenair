/**
 * API Client for ViGenAiR
 */

const API_BASE = '/api/v1';

class ApiClient {
    constructor(baseUrl = API_BASE) {
        this.baseUrl = baseUrl;
    }

    async request(endpoint, options = {}) {
        const url = `${this.baseUrl}${endpoint}`;
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
            },
        };

        const mergedOptions = {
            ...defaultOptions,
            ...options,
            headers: {
                ...defaultOptions.headers,
                ...options.headers,
            },
        };

        try {
            const response = await fetch(url, mergedOptions);

            if (!response.ok) {
                const errorData = await response.json().catch(() => ({}));
                throw new Error(errorData.detail || `HTTP ${response.status}`);
            }

            return await response.json();
        } catch (error) {
            console.error(`API Error: ${endpoint}`, error);
            throw error;
        }
    }

    // Jobs API
    async listJobs(params = {}) {
        const queryParams = new URLSearchParams();
        if (params.status) queryParams.set('status', params.status);
        if (params.search) queryParams.set('search', params.search);
        if (params.sort) queryParams.set('sort', params.sort);
        if (params.order) queryParams.set('order', params.order);
        if (params.page) queryParams.set('page', params.page);
        if (params.pageSize) queryParams.set('pageSize', params.pageSize);

        const query = queryParams.toString();
        return this.request(`/jobs${query ? '?' + query : ''}`);
    }

    async getJob(folder) {
        return this.request(`/jobs/${encodeURIComponent(folder)}`);
    }

    async deleteJob(folder) {
        return this.request(`/jobs/${encodeURIComponent(folder)}`, {
            method: 'DELETE',
        });
    }

    async updateJobVariants(folder, variants, selectedIndex = 0, settings = null) {
        const body = {
            variants,
            selectedVariantIndex: selectedIndex,
        };
        if (settings) {
            body.generationSettings = settings;
        }
        return this.request(`/jobs/${encodeURIComponent(folder)}/variants`, {
            method: 'PATCH',
            body: JSON.stringify(body),
        });
    }

    async updateJobUI(folder, ui) {
        return this.request(`/jobs/${encodeURIComponent(folder)}/ui`, {
            method: 'PATCH',
            body: JSON.stringify({ ui }),
        });
    }

    // Videos API (existing endpoints)
    async uploadVideo(file, analyzeAudio = true, userId = 'anonymous') {
        const formData = new FormData();
        formData.append('video', file);
        formData.append('analyse_audio', analyzeAudio);
        formData.append('user_id', userId);

        const response = await fetch(`${this.baseUrl}/videos/upload`, {
            method: 'POST',
            body: formData,
        });

        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.detail || `HTTP ${response.status}`);
        }

        return await response.json();
    }

    async initiateMultipartUpload(filename, fileSize, contentType, analyzeAudio, userId = 'anonymous') {
        return this.request('/videos/upload/initiate', {
            method: 'POST',
            body: JSON.stringify({ filename, fileSize, contentType, analyzeAudio, userId }),
        });
    }

    async completeMultipartUpload(uploadId, folder, s3Key, parts) {
        return this.request('/videos/upload/complete', {
            method: 'POST',
            body: JSON.stringify({ uploadId, folder, s3Key, parts }),
        });
    }

    async abortMultipartUpload(uploadId, folder, s3Key) {
        return this.request('/videos/upload/abort', {
            method: 'POST',
            body: JSON.stringify({ uploadId, folder, s3Key }),
        });
    }

    async getVideoStatus(folder) {
        return this.request(`/videos/${encodeURIComponent(folder)}/status`);
    }

    async getSegments(folder) {
        return this.request(`/videos/${encodeURIComponent(folder)}/segments`);
    }

    async generateVariants(folder, settings) {
        return this.request(`/videos/${encodeURIComponent(folder)}/variants/generate`, {
            method: 'POST',
            body: JSON.stringify(settings),
        });
    }

    async startRender(folder, renderRequest) {
        return this.request(`/videos/${encodeURIComponent(folder)}/render`, {
            method: 'POST',
            body: JSON.stringify(renderRequest),
        });
    }

    async getRenders(folder) {
        return this.request(`/videos/${encodeURIComponent(folder)}/renders`);
    }

    // Files API
    async getFileUrl(key, expiresIn = 3600) {
        return this.request(`/files/url?key=${encodeURIComponent(key)}&expires_in=${expiresIn}`);
    }

    async getSegmentVideoUrl(folder, segmentId) {
        return this.request(`/files/${encodeURIComponent(folder)}/segment-video/${segmentId}`);
    }

    async getSegmentThumbnailUrl(folder, segmentId) {
        return this.request(`/files/${encodeURIComponent(folder)}/thumbnail/${segmentId}`);
    }
}

// Export singleton instance
export const api = new ApiClient();
export default api;
