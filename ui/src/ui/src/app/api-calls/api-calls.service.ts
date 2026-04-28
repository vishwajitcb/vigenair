/**
 * Copyright 2025 Google LLC
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *       https://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * API Service for ViGenAiR - REST API Implementation
 * Replaces Google Apps Script calls with standard HTTP calls to FastAPI backend
 */

import { HttpClient, HttpHeaders } from '@angular/common/http';
import { Injectable, NgZone } from '@angular/core';
import { catchError, map, Observable, of, retry, switchMap, timer, throwError } from 'rxjs';
import { environment } from '../../environments/environment';

import {
  ApiCalls,
  GeneratePreviewsResponse,
  GenerateVariantsResponse,
  GenerationSettings,
  PreviewSettings,
  PreviousRunsResponse,
  RenderedVariant,
  RenderQueue,
  SegmentMarker,
  VariantTextAsset,
} from './api-calls.service.interface';

// Configuration
const API_BASE_URL = environment.apiBaseUrl || '/api/v1';
const MAX_RETRIES = 3;
const RETRY_DELAY = 2000;

@Injectable({
  providedIn: 'root',
})
export class ApiCallsService implements ApiCalls {
  constructor(
    private ngZone: NgZone,
    private httpClient: HttpClient
  ) {}

  /**
   * Load a previous run by folder name
   */
  loadPreviousRun(folder: string): string[] {
    // Return folder and presigned URL for the video
    return [
      folder,
      `${API_BASE_URL}/files/download/${folder}/input.mp4`,
    ];
  }

  /**
   * Get user auth token - not needed for REST API, returns empty observable
   */
  getUserAuthToken(): Observable<string> {
    // No auth token needed for local REST API
    return of('');
  }

  /**
   * Upload a video file
   */
  uploadVideo(
    file: File,
    analyseAudio: boolean,
    encodedUserId: string,
    filename?: string,
    contentType?: string
  ): Observable<string[]> {
    const formData = new FormData();
    formData.append('video', file);
    formData.append('analyse_audio', String(analyseAudio));
    formData.append('user_id', encodedUserId);

    return this.httpClient
      .post<{ folder: string; status: string; message: string }>(
        `${API_BASE_URL}/videos/upload`,
        formData
      )
      .pipe(
        map(response => {
          console.log('Upload complete!', response);
          const videoFilePath = `${API_BASE_URL}/files/download/${response.folder}/input.mp4`;
          return [response.folder, videoFilePath];
        }),
        catchError(error => {
          console.error('Upload failed with error: ', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Wait for converted video (for .mov to .mp4 conversion)
   */
  waitForConvertedVideo(folder: string): Observable<string> {
    const videoUrl = `${API_BASE_URL}/files/download/${folder}/input.mp4`;

    console.log('Checking for converted MP4 file...');

    return this.httpClient
      .head(`${API_BASE_URL}/files/download/${folder}/input.mp4`, {
        observe: 'response',
      })
      .pipe(
        map(() => {
          console.log('Converted MP4 file is ready!');
          return videoUrl;
        }),
        retry({
          count: 30,
          delay: (error, retryCount) => {
            if (error.status && error.status === 404 && retryCount < 30) {
              console.log(`Conversion in progress, retrying (${retryCount}/30)...`);
              return timer(2000);
            }
            throw error;
          },
        })
      );
  }

  /**
   * Delete a video folder
   */
  deleteGcsFolder(folder: string): void {
    this.httpClient
      .delete(`${API_BASE_URL}/videos/${folder}`)
      .subscribe({
        next: () => console.log(`Deleted folder: ${folder}`),
        error: (error) => console.error('Delete failed:', error),
      });
  }

  /**
   * Soft-delete a job: clears GCS files and marks as deleted in MongoDB
   */
  deleteJob(folder: string): Observable<any> {
    return this.httpClient
      .delete(`${API_BASE_URL}/jobs/${folder}`)
      .pipe(
        catchError(error => {
          console.error('Delete job failed:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Get GCS bucket storage usage
   */
  getStorageUsage(): Observable<{ totalBytes: number; totalFiles: number; humanReadable: string }> {
    return this.httpClient
      .get<{ totalBytes: number; totalFiles: number; humanReadable: string }>(
        `${API_BASE_URL}/jobs/storage/usage`
      )
      .pipe(
        catchError(error => {
          console.error('Get storage usage failed:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Nuclear wipe: soft-delete all jobs and clear all GCS files
   */
  wipeAllJobs(): Observable<any> {
    return this.httpClient
      .delete(`${API_BASE_URL}/jobs/wipe/all`)
      .pipe(
        catchError(error => {
          console.error('Wipe all failed:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Get file content from storage
   */
  getFromGcs(url: string, retryDelay = 0, maxRetries = 0): Observable<string> {
    return this.httpClient
      .get(`${API_BASE_URL}/files/download/${url}`, {
        responseType: 'text',
      })
      .pipe(
        retry({
          count: maxRetries,
          delay: (error, retryCount) => {
            if (error.status && error.status === 404 && retryCount < maxRetries) {
              console.log(`Expected output not available yet, retrying (${retryCount}/${maxRetries})...`);
              return timer(retryDelay);
            }
            throw error;
          },
        })
      );
  }

  /**
   * Generate AI-powered variant suggestions
   */
  generateVariants(
    gcsFolder: string,
    settings: GenerationSettings
  ): Observable<GenerateVariantsResponse[]> {
    console.log('API Service: Starting generateVariants call');
    console.log('Settings:', settings);

    return this.httpClient
      .post<{ variants: GenerateVariantsResponse[] }>(
        `${API_BASE_URL}/videos/${gcsFolder}/variants/generate`,
        {
          prompt: settings.prompt || '',
          eval_prompt: settings.evalPrompt || '',
          target_duration: settings.duration,
          demand_gen_assets: settings.demandGenAssets,
          shorten_video: settings.shortenVideo,
        }
      )
      .pipe(
        map(response => {
          console.log('Variants received:', response.variants);
          return response.variants || [];
        }),
        retry({ count: MAX_RETRIES, delay: RETRY_DELAY }),
        catchError(error => {
          console.error('Error generating variants:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Generate preview crops for different aspect ratios
   */
  generatePreviews(
    gcsFolder: string,
    analysis: any,
    segments: any,
    settings: PreviewSettings
  ): Observable<GeneratePreviewsResponse> {
    return this.httpClient
      .post<GeneratePreviewsResponse>(
        `${API_BASE_URL}/videos/${gcsFolder}/previews/generate`,
        {
          analysis,
          segments,
          settings,
        }
      )
      .pipe(
        retry({ count: MAX_RETRIES, delay: RETRY_DELAY }),
        catchError(error => {
          console.error('Error generating previews:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Get list of previous video processing runs
   */
  getRunsFromGcs(): Observable<PreviousRunsResponse> {
    return this.httpClient
      .get<{ videos: any[]; encoded_user_id?: string }>(`${API_BASE_URL}/videos`)
      .pipe(
        map(response => {
          // Transform to expected format - runs is array of folder names
          const runs = response.videos.map(v => v.folder);
          return {
            encodedUserId: response.encoded_user_id || '',
            runs,
          } as PreviousRunsResponse;
        }),
        retry({ count: MAX_RETRIES, delay: RETRY_DELAY }),
        catchError(error => {
          console.error('Error getting runs:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Get rendered variants for a video
   */
  /**
   * Build a downloadable URL for a GCS object key.
   */
  getDownloadUrl(gcsKey: string): string {
    return `${API_BASE_URL}/files/download/${gcsKey}`;
  }

  getRendersFromGcs(gcsFolder: string): Observable<string[]> {
    return this.httpClient
      .get<{ folder: string; combos: any }>(`${API_BASE_URL}/videos/${gcsFolder}/renders`)
      .pipe(
        map(response => {
          // Return render file paths
          if (response.combos && response.combos.variants) {
            return response.combos.variants.map((v: any) => v.path || '');
          }
          return [];
        }),
        retry({ count: MAX_RETRIES, delay: RETRY_DELAY }),
        catchError(error => {
          console.error('Error getting renders:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Fetch the structured renders array (covers XML and video entries).
   * Polls until at least one entry exists or retries are exhausted.
   */
  getRendersArray(gcsFolder: string): Observable<any[]> {
    return this.httpClient
      .get<{ folder: string; combos: any; renders: any[] | null; error?: string }>(
        `${API_BASE_URL}/videos/${gcsFolder}/renders`
      )
      .pipe(
        map(response => {
          if (response.error) {
            throw new Error(response.error);
          }
          if (!response.renders || response.renders.length === 0) {
            throw new Error('renders not yet available');
          }
          return response.renders;
        }),
        retry({ count: 80, delay: 6000 }),
        catchError(error => {
          console.error('Error getting renders array:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Submit render request for variants
   */
  renderVariants(
    gcsFolder: string,
    renderQueue: RenderQueue
  ): Observable<string> {
    const variants = renderQueue.queue.map((v, idx) => ({
      id: v.original_variant_id ?? idx,
      title: v.title,
      description: v.description,
      score: v.score,
      reasoning: v.score_reasoning,
      segments: (v.av_segments || []).map((seg: any) => seg.av_segment_id),
      formats: v.render_settings?.formats ?? ['16:9'],
      audioMode: v.render_settings?.use_continuous_audio
        ? 'continuous'
        : v.render_settings?.use_music_overlay
          ? 'music'
          : 'segment',
      outputType: renderQueue.outputType ?? 'video',
    }));
    return this.httpClient
      .post<{ folder: string; status: string; message: string }>(
        `${API_BASE_URL}/videos/${gcsFolder}/render`,
        {
          variants,
          settings: {
            queue_name: renderQueue.queueName,
            preview_analyses: renderQueue.previewAnalyses,
            source_dimensions: renderQueue.sourceDimensions,
          },
          output_type: renderQueue.outputType ?? 'video',
        }
      )
      .pipe(
        map(response => response.message),
        catchError(error => {
          console.error('Error rendering variants:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Get folder path for browsing
   */
  getGcsFolderPath(folder: string): Observable<string> {
    // Return API file listing URL
    return of(`${API_BASE_URL}/files/list?prefix=${encodeURIComponent(folder)}`);
  }

  /**
   * Get web app URL
   */
  getWebAppUrl(): Observable<string> {
    // Return current origin
    return of(window.location.origin);
  }

  /**
   * Regenerate a single text asset
   */
  regenerateTextAsset(
    variantVideoPath: string,
    textAsset: VariantTextAsset,
    textAssetLanguage: string
  ): Observable<VariantTextAsset> {
    return this.httpClient
      .post<VariantTextAsset>(
        `${API_BASE_URL}/videos/text-assets/regenerate`,
        {
          variant_video_path: variantVideoPath,
          text_asset: textAsset,
          language: textAssetLanguage,
        }
      )
      .pipe(
        map(response => {
          response.approved = true;
          response.editable = false;
          return response;
        }),
        retry({ count: MAX_RETRIES, delay: RETRY_DELAY }),
        catchError(error => {
          console.error('Error regenerating text asset:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Store approval status for rendered variants
   */
  storeApprovalStatus(
    folder: string,
    combos: RenderedVariant[]
  ): Observable<boolean> {
    return this.httpClient
      .post<{ success: boolean }>(
        `${API_BASE_URL}/videos/${folder}/approval`,
        { combos }
      )
      .pipe(
        map(response => response.success),
        catchError(error => {
          console.error('Error storing approval status:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Get detected video language
   */
  getVideoLanguage(gcsFolder: string): Observable<string> {
    return this.getFromGcs(`${gcsFolder}/language.txt`, RETRY_DELAY, MAX_RETRIES).pipe(
      map(content => content.trim()),
      catchError(() => of('English')) // Default to English
    );
  }

  /**
   * Generate text assets for a variant
   */
  generateTextAssets(
    variantVideoPath: string,
    textAssetsLanguage: string
  ): Observable<VariantTextAsset[]> {
    return this.httpClient
      .post<{ assets: VariantTextAsset[] }>(
        `${API_BASE_URL}/videos/text-assets/generate`,
        {
          variant_video_path: variantVideoPath,
          language: textAssetsLanguage,
        }
      )
      .pipe(
        map(response => {
          const assets = response.assets || [];
          assets.forEach(asset => {
            asset.approved = true;
            asset.editable = false;
          });
          return assets;
        }),
        retry({ count: MAX_RETRIES, delay: RETRY_DELAY }),
        catchError(error => {
          console.error('Error generating text assets:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Split a segment at specified markers
   */
  splitSegment(
    gcsFolder: string,
    segmentMarkers: SegmentMarker[]
  ): Observable<string> {
    return this.httpClient
      .post<{ status: string; message: string }>(
        `${API_BASE_URL}/videos/${gcsFolder}/segments/split`,
        {
          segment_id: segmentMarkers[0]?.av_segment_id || '',
          split_times: segmentMarkers.map(m => m.marker_cut_time_s),
        }
      )
      .pipe(
        map(response => response.message),
        catchError(error => {
          console.error('Error splitting segment:', error);
          return throwError(() => error);
        })
      );
  }

  /**
   * Update transcription for a video
   */
  updateTranscription(
    gcsFolder: string,
    transcriptionText: string
  ): Observable<boolean> {
    return this.httpClient
      .put<{ success: boolean }>(
        `${API_BASE_URL}/videos/${gcsFolder}/transcription`,
        { transcription: transcriptionText }
      )
      .pipe(
        map(response => response.success),
        catchError(error => {
          console.error('Error updating transcription:', error);
          return throwError(() => error);
        })
      );
  }
}
