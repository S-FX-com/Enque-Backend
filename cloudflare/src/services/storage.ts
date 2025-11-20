import { Env } from '../types/env';
import { generateId } from '../utils/crypto';

export interface UploadOptions {
  contentType?: string;
  metadata?: Record<string, string>;
  customKey?: string;
}

export interface UploadResult {
  key: string;
  url: string;
  size: number;
  contentType?: string;
}

/**
 * R2 Storage Service
 * Handles file uploads and downloads using Cloudflare R2
 */
export class StorageService {
  private bucket: R2Bucket;
  private env: Env;

  constructor(env: Env) {
    this.env = env;
    this.bucket = env.STORAGE;
  }

  /**
   * Upload a file to R2
   */
  async uploadFile(
    file: File | ArrayBuffer,
    filename: string,
    options: UploadOptions = {}
  ): Promise<UploadResult> {
    const key = options.customKey || this.generateFileKey(filename);

    // Get file content
    const content = file instanceof File ? await file.arrayBuffer() : file;

    // Determine content type
    const contentType = options.contentType || (file instanceof File ? file.type : 'application/octet-stream');

    // Upload to R2
    await this.bucket.put(key, content, {
      httpMetadata: {
        contentType,
      },
      customMetadata: options.metadata,
    });

    // Get file size
    const size = content.byteLength;

    return {
      key,
      url: this.getPublicUrl(key),
      size,
      contentType,
    };
  }

  /**
   * Upload file from URL (e.g., from Microsoft Graph attachment)
   */
  async uploadFromUrl(url: string, filename: string, options: UploadOptions = {}): Promise<UploadResult> {
    const response = await fetch(url);

    if (!response.ok) {
      throw new Error(`Failed to fetch file from URL: ${response.statusText}`);
    }

    const content = await response.arrayBuffer();
    const contentType = options.contentType || response.headers.get('content-type') || 'application/octet-stream';

    return this.uploadFile(content, filename, { ...options, contentType });
  }

  /**
   * Upload base64 encoded content (from Microsoft Graph attachments)
   */
  async uploadBase64(
    base64Content: string,
    filename: string,
    options: UploadOptions = {}
  ): Promise<UploadResult> {
    // Decode base64
    const binaryString = atob(base64Content);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }

    return this.uploadFile(bytes.buffer, filename, options);
  }

  /**
   * Get a file from R2
   */
  async getFile(key: string): Promise<R2ObjectBody | null> {
    return this.bucket.get(key);
  }

  /**
   * Delete a file from R2
   */
  async deleteFile(key: string): Promise<void> {
    await this.bucket.delete(key);
  }

  /**
   * Delete multiple files
   */
  async deleteFiles(keys: string[]): Promise<void> {
    await this.bucket.delete(keys);
  }

  /**
   * Check if file exists
   */
  async fileExists(key: string): Promise<boolean> {
    const object = await this.bucket.head(key);
    return object !== null;
  }

  /**
   * Get file metadata
   */
  async getFileMetadata(key: string): Promise<{
    size: number;
    contentType?: string;
    uploaded: Date;
    customMetadata?: Record<string, string>;
  } | null> {
    const object = await this.bucket.head(key);

    if (!object) {
      return null;
    }

    return {
      size: object.size,
      contentType: object.httpMetadata?.contentType,
      uploaded: object.uploaded,
      customMetadata: object.customMetadata,
    };
  }

  /**
   * List files with prefix
   */
  async listFiles(prefix: string, limit: number = 1000): Promise<string[]> {
    const list = await this.bucket.list({ prefix, limit });
    return list.objects.map(obj => obj.key);
  }

  /**
   * Generate a unique file key
   */
  private generateFileKey(filename: string): string {
    const timestamp = Date.now();
    const random = generateId();
    const extension = filename.split('.').pop();
    const baseName = filename.replace(/\.[^/.]+$/, '').replace(/[^a-zA-Z0-9-_]/g, '-');

    return `uploads/${timestamp}/${random}-${baseName}.${extension}`;
  }

  /**
   * Get public URL for a file
   * Note: R2 buckets can be configured with custom domains for public access
   */
  private getPublicUrl(key: string): string {
    // In production, this would use your R2 public domain
    // For now, return a placeholder
    return `${this.env.API_BASE_URL}/files/${key}`;
  }

  /**
   * Generate a signed URL for temporary access (if R2 is private)
   */
  async getSignedUrl(key: string, expiresIn: number = 3600): Promise<string> {
    // R2 doesn't support signed URLs directly like S3
    // You would need to implement this using Workers or return the key
    // and handle access control in your API
    return this.getPublicUrl(key);
  }
}
