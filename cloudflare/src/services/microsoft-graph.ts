import { Env } from '../types/env';
import { decrypt, encrypt } from '../utils/crypto';

export interface MicrosoftAuthConfig {
  clientId: string;
  clientSecret: string;
  tenantId: string;
  redirectUri: string;
  scope: string;
}

export interface MicrosoftTokenResponse {
  access_token: string;
  refresh_token?: string;
  id_token?: string;
  token_type: string;
  expires_in: number;
  scope: string;
}

export interface GraphEmail {
  id: string;
  conversationId: string;
  subject: string;
  bodyPreview: string;
  body: {
    contentType: 'text' | 'html';
    content: string;
  };
  from: {
    emailAddress: {
      name: string;
      address: string;
    };
  };
  toRecipients: Array<{
    emailAddress: {
      name: string;
      address: string;
    };
  }>;
  ccRecipients: Array<{
    emailAddress: {
      name: string;
      address: string;
    };
  }>;
  hasAttachments: boolean;
  importance: 'low' | 'normal' | 'high';
  isRead: boolean;
  receivedDateTime: string;
}

export interface GraphUser {
  id: string;
  displayName: string;
  mail: string;
  userPrincipalName: string;
}

/**
 * Microsoft Graph API Service
 * Handles all interactions with Microsoft Graph API
 */
export class MicrosoftGraphService {
  private config: MicrosoftAuthConfig;
  private env: Env;

  constructor(env: Env, config?: Partial<MicrosoftAuthConfig>) {
    this.env = env;
    this.config = {
      clientId: config?.clientId || env.MICROSOFT_CLIENT_ID,
      clientSecret: config?.clientSecret || env.MICROSOFT_CLIENT_SECRET,
      tenantId: config?.tenantId || env.MICROSOFT_TENANT_ID,
      redirectUri: config?.redirectUri || env.MICROSOFT_REDIRECT_URI,
      scope: config?.scope || env.MICROSOFT_SCOPE,
    };
  }

  /**
   * Get OAuth authorization URL
   */
  getAuthorizationUrl(state?: string): string {
    const params = new URLSearchParams({
      client_id: this.config.clientId,
      response_type: 'code',
      redirect_uri: this.config.redirectUri,
      scope: this.config.scope,
      response_mode: 'query',
    });

    if (state) {
      params.append('state', state);
    }

    return `https://login.microsoftonline.com/common/oauth2/v2.0/authorize?${params}`;
  }

  /**
   * Exchange authorization code for access token
   */
  async getTokenFromCode(code: string): Promise<MicrosoftTokenResponse> {
    const params = new URLSearchParams({
      client_id: this.config.clientId,
      client_secret: this.config.clientSecret,
      code,
      redirect_uri: this.config.redirectUri,
      grant_type: 'authorization_code',
      scope: this.config.scope,
    });

    const response = await fetch('https://login.microsoftonline.com/common/oauth2/v2.0/token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: params.toString(),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(`Failed to get token: ${error.error_description || error.error}`);
    }

    return response.json();
  }

  /**
   * Refresh access token using refresh token
   */
  async refreshToken(refreshToken: string): Promise<MicrosoftTokenResponse> {
    // Decrypt refresh token
    const decryptedToken = await decrypt(refreshToken, this.env.DATABASE_ENCRYPTION_KEY);

    const params = new URLSearchParams({
      client_id: this.config.clientId,
      client_secret: this.config.clientSecret,
      refresh_token: decryptedToken,
      grant_type: 'refresh_token',
      scope: this.config.scope,
    });

    const response = await fetch('https://login.microsoftonline.com/common/oauth2/v2.0/token', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
      },
      body: params.toString(),
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(`Failed to refresh token: ${error.error_description || error.error}`);
    }

    return response.json();
  }

  /**
   * Get current user info from Microsoft Graph
   */
  async getCurrentUser(accessToken: string): Promise<GraphUser> {
    const response = await this.graphRequest('/me', accessToken);
    return response;
  }

  /**
   * Get messages from a mailbox
   */
  async getMessages(
    accessToken: string,
    options: {
      folder?: string;
      top?: number;
      skip?: number;
      filter?: string;
      orderBy?: string;
    } = {}
  ): Promise<{ value: GraphEmail[]; '@odata.nextLink'?: string }> {
    const { folder = 'Inbox', top = 50, skip = 0, filter, orderBy = 'receivedDateTime desc' } = options;

    const params = new URLSearchParams({
      $top: top.toString(),
      $skip: skip.toString(),
      $orderby: orderBy,
    });

    if (filter) {
      params.append('$filter', filter);
    }

    const path = folder === 'Inbox'
      ? `/me/mailFolders/Inbox/messages?${params}`
      : `/me/messages?${params}`;

    return this.graphRequest(path, accessToken);
  }

  /**
   * Get a specific message
   */
  async getMessage(messageId: string, accessToken: string): Promise<GraphEmail> {
    return this.graphRequest(`/me/messages/${messageId}`, accessToken);
  }

  /**
   * Send an email
   */
  async sendMail(
    accessToken: string,
    message: {
      subject: string;
      body: string;
      bodyType?: 'text' | 'html';
      toRecipients: string[];
      ccRecipients?: string[];
      importance?: 'low' | 'normal' | 'high';
    }
  ): Promise<void> {
    const emailMessage = {
      message: {
        subject: message.subject,
        body: {
          contentType: message.bodyType || 'html',
          content: message.body,
        },
        toRecipients: message.toRecipients.map(email => ({
          emailAddress: { address: email },
        })),
        ccRecipients: message.ccRecipients?.map(email => ({
          emailAddress: { address: email },
        })) || [],
        importance: message.importance || 'normal',
      },
      saveToSentItems: true,
    };

    await this.graphRequest('/me/sendMail', accessToken, {
      method: 'POST',
      body: JSON.stringify(emailMessage),
    });
  }

  /**
   * Reply to an email
   */
  async replyToMessage(
    messageId: string,
    accessToken: string,
    comment: string,
    replyAll: boolean = false
  ): Promise<void> {
    const endpoint = replyAll ? `/me/messages/${messageId}/replyAll` : `/me/messages/${messageId}/reply`;

    await this.graphRequest(endpoint, accessToken, {
      method: 'POST',
      body: JSON.stringify({
        comment,
      }),
    });
  }

  /**
   * Get message attachments
   */
  async getAttachments(messageId: string, accessToken: string): Promise<any[]> {
    const response = await this.graphRequest(`/me/messages/${messageId}/attachments`, accessToken);
    return response.value || [];
  }

  /**
   * Download an attachment
   */
  async downloadAttachment(
    messageId: string,
    attachmentId: string,
    accessToken: string
  ): Promise<{ name: string; contentType: string; contentBytes: string }> {
    return this.graphRequest(`/me/messages/${messageId}/attachments/${attachmentId}`, accessToken);
  }

  /**
   * Mark message as read
   */
  async markAsRead(messageId: string, accessToken: string): Promise<void> {
    await this.graphRequest(`/me/messages/${messageId}`, accessToken, {
      method: 'PATCH',
      body: JSON.stringify({
        isRead: true,
      }),
    });
  }

  /**
   * Get mail folders
   */
  async getMailFolders(accessToken: string): Promise<any[]> {
    const response = await this.graphRequest('/me/mailFolders', accessToken);
    return response.value || [];
  }

  /**
   * Generic Microsoft Graph API request
   */
  private async graphRequest(
    path: string,
    accessToken: string,
    options: RequestInit = {}
  ): Promise<any> {
    const url = path.startsWith('http')
      ? path
      : `${this.env.MICROSOFT_GRAPH_URL}${path}`;

    const response = await fetch(url, {
      ...options,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        'Content-Type': 'application/json',
        ...options.headers,
      },
    });

    if (!response.ok) {
      const error = await response.json().catch(() => ({ error: 'Unknown error' }));
      throw new Error(`Graph API error: ${error.error?.message || response.statusText}`);
    }

    // Some endpoints return 204 No Content
    if (response.status === 204) {
      return null;
    }

    return response.json();
  }

  /**
   * Encrypt tokens for storage
   */
  async encryptTokens(tokens: MicrosoftTokenResponse): Promise<{
    accessToken: string;
    refreshToken?: string;
    idToken?: string;
  }> {
    return {
      accessToken: await encrypt(tokens.access_token, this.env.DATABASE_ENCRYPTION_KEY),
      refreshToken: tokens.refresh_token
        ? await encrypt(tokens.refresh_token, this.env.DATABASE_ENCRYPTION_KEY)
        : undefined,
      idToken: tokens.id_token
        ? await encrypt(tokens.id_token, this.env.DATABASE_ENCRYPTION_KEY)
        : undefined,
    };
  }

  /**
   * Decrypt tokens from storage
   */
  async decryptAccessToken(encryptedToken: string): Promise<string> {
    return decrypt(encryptedToken, this.env.DATABASE_ENCRYPTION_KEY);
  }
}
