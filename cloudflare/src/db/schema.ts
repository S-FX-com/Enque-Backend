import { sqliteTable, text, integer, real, index } from 'drizzle-orm/sqlite-core';
import { sql } from 'drizzle-orm';

// ============================================================================
// CORE ENTITIES
// ============================================================================

/**
 * Workspaces - Multi-tenant isolation
 * Each workspace represents an organization using the platform
 */
export const workspaces = sqliteTable('workspaces', {
  id: text('id').primaryKey(),
  name: text('name').notNull(),
  subdomain: text('subdomain').notNull().unique(),

  // Metadata
  isActive: integer('is_active', { mode: 'boolean' }).notNull().default(true),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  subdomainIdx: index('idx_workspaces_subdomain').on(table.subdomain),
}));

/**
 * Agents - Internal staff/employees who handle tickets
 * Can belong to multiple workspaces
 */
export const agents = sqliteTable('agents', {
  id: text('id').primaryKey(),
  email: text('email').notNull().unique(),
  displayName: text('display_name').notNull(),
  passwordHash: text('password_hash'), // Null if using only Microsoft auth

  // Microsoft OAuth
  microsoftId: text('microsoft_id').unique(),

  // Profile
  avatarUrl: text('avatar_url'),
  role: text('role').notNull().default('agent'), // admin, manager, agent

  // Auth method
  authMethod: text('auth_method').notNull().default('password'), // password, microsoft, both

  // Status
  isActive: integer('is_active', { mode: 'boolean' }).notNull().default(true),
  lastLoginAt: integer('last_login_at', { mode: 'timestamp' }),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  emailIdx: index('idx_agents_email').on(table.email),
  microsoftIdIdx: index('idx_agents_microsoft_id').on(table.microsoftId),
}));

/**
 * Agent Workspace Access - Many-to-many relationship
 * Defines which workspaces an agent can access
 */
export const agentWorkspaces = sqliteTable('agent_workspaces', {
  id: text('id').primaryKey(),
  agentId: text('agent_id').notNull().references(() => agents.id, { onDelete: 'cascade' }),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  // Role within this specific workspace
  role: text('role').notNull().default('agent'), // admin, manager, agent

  // Metadata
  joinedAt: integer('joined_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  agentWorkspaceIdx: index('idx_agent_workspaces_agent_workspace').on(table.agentId, table.workspaceId),
}));

/**
 * Users - External customers who submit tickets
 */
export const users = sqliteTable('users', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  email: text('email').notNull(),
  name: text('name').notNull(),

  // Company association
  companyId: text('company_id').references(() => companies.id, { onDelete: 'set null' }),

  // Profile
  avatarUrl: text('avatar_url'),
  phone: text('phone'),
  timezone: text('timezone'),
  language: text('language').default('en'),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceEmailIdx: index('idx_users_workspace_email').on(table.workspaceId, table.email),
  companyIdx: index('idx_users_company').on(table.companyId),
}));

/**
 * Companies - Customer organizations
 */
export const companies = sqliteTable('companies', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  name: text('name').notNull(),
  domain: text('domain'), // Email domain for auto-association

  // Contact info
  website: text('website'),
  phone: text('phone'),

  // Metadata
  notes: text('notes'),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_companies_workspace').on(table.workspaceId),
  domainIdx: index('idx_companies_domain').on(table.domain),
}));

/**
 * Teams - Groups of agents
 */
export const teams = sqliteTable('teams', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  name: text('name').notNull(),
  description: text('description'),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_teams_workspace').on(table.workspaceId),
}));

/**
 * Team Members - Many-to-many relationship between agents and teams
 */
export const teamMembers = sqliteTable('team_members', {
  id: text('id').primaryKey(),
  teamId: text('team_id').notNull().references(() => teams.id, { onDelete: 'cascade' }),
  agentId: text('agent_id').notNull().references(() => agents.id, { onDelete: 'cascade' }),

  // Role within team
  isLead: integer('is_lead', { mode: 'boolean' }).notNull().default(false),

  // Metadata
  joinedAt: integer('joined_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  teamAgentIdx: index('idx_team_members_team_agent').on(table.teamId, table.agentId),
}));

// ============================================================================
// TICKETING SYSTEM
// ============================================================================

/**
 * Categories - Ticket categorization
 */
export const categories = sqliteTable('categories', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  name: text('name').notNull(),
  color: text('color').default('#3b82f6'), // Hex color

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_categories_workspace').on(table.workspaceId),
}));

/**
 * Tickets (Tasks) - Main ticket/support request entity
 */
export const tickets = sqliteTable('tickets', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  // Email integration
  conversationId: text('conversation_id'), // Email thread ID
  messageId: text('message_id').unique(), // Unique message ID from email

  // Ticket info
  subject: text('subject').notNull(),
  bodyPreview: text('body_preview'), // Short preview
  priority: text('priority').notNull().default('Medium'), // Low, Medium, High, Critical
  status: text('status').notNull().default('Unread'), // Unread, Open, In Progress, Pending, Resolved, Closed

  // Customer info
  fromEmail: text('from_email').notNull(),
  fromName: text('from_name').notNull(),
  userId: text('user_id').references(() => users.id, { onDelete: 'set null' }),

  // Assignment
  assignedToId: text('assigned_to_id').references(() => agents.id, { onDelete: 'set null' }),
  teamId: text('team_id').references(() => teams.id, { onDelete: 'set null' }),
  categoryId: text('category_id').references(() => categories.id, { onDelete: 'set null' }),

  // Email recipients (stored as JSON)
  toEmails: text('to_emails', { mode: 'json' }).$type<string[]>(),
  ccEmails: text('cc_emails', { mode: 'json' }).$type<string[]>(),

  // Flags
  hasAttachments: integer('has_attachments', { mode: 'boolean' }).notNull().default(false),
  isRead: integer('is_read', { mode: 'boolean' }).notNull().default(false),
  importance: text('importance').default('normal'), // low, normal, high

  // Tags (stored as JSON array)
  tags: text('tags', { mode: 'json' }).$type<string[]>().default(sql`'[]'`),

  // Timestamps
  receivedDateTime: integer('received_date_time', { mode: 'timestamp' }),
  firstResponseAt: integer('first_response_at', { mode: 'timestamp' }),
  resolvedAt: integer('resolved_at', { mode: 'timestamp' }),
  closedAt: integer('closed_at', { mode: 'timestamp' }),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_tickets_workspace').on(table.workspaceId),
  statusIdx: index('idx_tickets_status').on(table.status),
  assignedToIdx: index('idx_tickets_assigned_to').on(table.assignedToId),
  messageIdIdx: index('idx_tickets_message_id').on(table.messageId),
  conversationIdx: index('idx_tickets_conversation').on(table.conversationId),
  fromEmailIdx: index('idx_tickets_from_email').on(table.fromEmail),
  userIdx: index('idx_tickets_user').on(table.userId),
}));

/**
 * Ticket Bodies - Separate table for large email bodies
 * Keeps main tickets table lean
 */
export const ticketBodies = sqliteTable('ticket_bodies', {
  id: text('id').primaryKey(),
  ticketId: text('ticket_id').notNull().references(() => tickets.id, { onDelete: 'cascade' }).unique(),

  // Full email body (can be large HTML)
  bodyHtml: text('body_html'),
  bodyText: text('body_text'),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  ticketIdx: index('idx_ticket_bodies_ticket').on(table.ticketId),
}));

/**
 * Comments - Public responses on tickets (visible to customers)
 */
export const comments = sqliteTable('comments', {
  id: text('id').primaryKey(),
  ticketId: text('ticket_id').notNull().references(() => tickets.id, { onDelete: 'cascade' }),

  // Author
  agentId: text('agent_id').references(() => agents.id, { onDelete: 'set null' }),
  authorName: text('author_name').notNull(), // Cached name
  authorEmail: text('author_email'), // Cached email

  // Content
  content: text('content').notNull(),
  contentType: text('content_type').notNull().default('text'), // text, html

  // Email integration
  isSentViaEmail: integer('is_sent_via_email', { mode: 'boolean' }).notNull().default(false),
  emailMessageId: text('email_message_id'), // Microsoft Graph message ID

  // Visibility
  isInternal: integer('is_internal', { mode: 'boolean' }).notNull().default(false), // Internal notes vs public comments

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  ticketIdx: index('idx_comments_ticket').on(table.ticketId),
  agentIdx: index('idx_comments_agent').on(table.agentId),
  internalIdx: index('idx_comments_internal').on(table.isInternal),
}));

/**
 * Scheduled Comments - Comments scheduled to be sent at a future time
 */
export const scheduledComments = sqliteTable('scheduled_comments', {
  id: text('id').primaryKey(),
  ticketId: text('ticket_id').notNull().references(() => tickets.id, { onDelete: 'cascade' }),
  agentId: text('agent_id').notNull().references(() => agents.id, { onDelete: 'cascade' }),

  // Content
  content: text('content').notNull(),

  // Scheduling
  scheduledFor: integer('scheduled_for', { mode: 'timestamp' }).notNull(),
  isSent: integer('is_sent', { mode: 'boolean' }).notNull().default(false),
  sentAt: integer('sent_at', { mode: 'timestamp' }),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  ticketIdx: index('idx_scheduled_comments_ticket').on(table.ticketId),
  scheduledForIdx: index('idx_scheduled_comments_scheduled_for').on(table.scheduledFor),
  isSentIdx: index('idx_scheduled_comments_is_sent').on(table.isSent),
}));

/**
 * Ticket Attachments - Files attached to tickets
 */
export const ticketAttachments = sqliteTable('ticket_attachments', {
  id: text('id').primaryKey(),
  ticketId: text('ticket_id').notNull().references(() => tickets.id, { onDelete: 'cascade' }),

  // File info
  filename: text('filename').notNull(),
  contentType: text('content_type'),
  size: integer('size'), // Bytes

  // Storage (R2)
  r2Key: text('r2_key').notNull(), // Key in R2 bucket
  r2Url: text('r2_url'), // Public URL if available

  // Microsoft Graph reference (if synced from email)
  graphAttachmentId: text('graph_attachment_id'),

  // Metadata
  uploadedBy: text('uploaded_by').references(() => agents.id, { onDelete: 'set null' }),
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  ticketIdx: index('idx_attachments_ticket').on(table.ticketId),
}));

// ============================================================================
// MICROSOFT INTEGRATION
// ============================================================================

/**
 * Microsoft Integrations - OAuth app configurations per workspace
 */
export const microsoftIntegrations = sqliteTable('microsoft_integrations', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  // OAuth app credentials
  clientId: text('client_id').notNull(),
  clientSecret: text('client_secret').notNull(), // Encrypted
  tenantId: text('tenant_id').notNull(),

  // Configuration
  isActive: integer('is_active', { mode: 'boolean' }).notNull().default(true),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_microsoft_integrations_workspace').on(table.workspaceId),
}));

/**
 * Mailbox Connections - Connected mailboxes for email sync
 */
export const mailboxConnections = sqliteTable('mailbox_connections', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),
  agentId: text('agent_id').references(() => agents.id, { onDelete: 'set null' }),

  // Mailbox info
  email: text('email').notNull(),
  displayName: text('display_name'),
  mailboxType: text('mailbox_type').notNull().default('user'), // user, shared

  // Sync status
  isActive: integer('is_active', { mode: 'boolean' }).notNull().default(true),
  lastSyncAt: integer('last_sync_at', { mode: 'timestamp' }),
  lastSyncStatus: text('last_sync_status'), // success, error
  lastSyncError: text('last_sync_error'),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_mailbox_connections_workspace').on(table.workspaceId),
  emailIdx: index('idx_mailbox_connections_email').on(table.email),
}));

/**
 * Microsoft Tokens - OAuth tokens for accessing Microsoft Graph API
 */
export const microsoftTokens = sqliteTable('microsoft_tokens', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),
  agentId: text('agent_id').references(() => agents.id, { onDelete: 'cascade' }),
  mailboxConnectionId: text('mailbox_connection_id').references(() => mailboxConnections.id, { onDelete: 'cascade' }),

  // Tokens (encrypted)
  accessToken: text('access_token').notNull(),
  refreshToken: text('refresh_token'),
  idToken: text('id_token'),

  // Token metadata
  tokenType: text('token_type').default('Bearer'),
  scope: text('scope'),
  expiresAt: integer('expires_at', { mode: 'timestamp' }),

  // Microsoft user info
  microsoftUserId: text('microsoft_user_id'),
  userEmail: text('user_email'),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceAgentIdx: index('idx_microsoft_tokens_workspace_agent').on(table.workspaceId, table.agentId),
  mailboxIdx: index('idx_microsoft_tokens_mailbox').on(table.mailboxConnectionId),
}));

/**
 * Email Ticket Mapping - Maps email message IDs to tickets
 */
export const emailTicketMappings = sqliteTable('email_ticket_mappings', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  // Email info
  messageId: text('message_id').notNull().unique(),
  conversationId: text('conversation_id'),

  // Ticket reference
  ticketId: text('ticket_id').notNull().references(() => tickets.id, { onDelete: 'cascade' }),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  messageIdIdx: index('idx_email_ticket_mappings_message_id').on(table.messageId),
  ticketIdx: index('idx_email_ticket_mappings_ticket').on(table.ticketId),
}));

/**
 * Email Sync Config - Configuration for email sync per mailbox
 */
export const emailSyncConfigs = sqliteTable('email_sync_configs', {
  id: text('id').primaryKey(),
  mailboxConnectionId: text('mailbox_connection_id').notNull().references(() => mailboxConnections.id, { onDelete: 'cascade' }).unique(),

  // Sync settings
  syncFolder: text('sync_folder').notNull().default('Inbox'),
  syncEnabled: integer('sync_enabled', { mode: 'boolean' }).notNull().default(true),
  defaultPriority: text('default_priority').default('Medium'),
  defaultCategoryId: text('default_category_id').references(() => categories.id, { onDelete: 'set null' }),
  autoAssignToTeamId: text('auto_assign_to_team_id').references(() => teams.id, { onDelete: 'set null' }),

  // Advanced settings
  skipInternalEmails: integer('skip_internal_emails', { mode: 'boolean' }).notNull().default(false),
  markAsRead: integer('mark_as_read', { mode: 'boolean' }).notNull().default(false),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  mailboxIdx: index('idx_email_sync_configs_mailbox').on(table.mailboxConnectionId),
}));

// ============================================================================
// AUTOMATION & WORKFLOWS
// ============================================================================

/**
 * Workflows - Custom workflow definitions
 */
export const workflows = sqliteTable('workflows', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  name: text('name').notNull(),
  description: text('description'),

  // Trigger configuration (JSON)
  triggerType: text('trigger_type').notNull(), // ticket_created, ticket_updated, email_received, etc.
  triggerConfig: text('trigger_config', { mode: 'json' }).$type<Record<string, any>>(),

  // Actions (JSON array)
  actions: text('actions', { mode: 'json' }).$type<any[]>().notNull(),

  // Status
  isActive: integer('is_active', { mode: 'boolean' }).notNull().default(true),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_workflows_workspace').on(table.workspaceId),
}));

/**
 * Automations - Automation rules
 */
export const automations = sqliteTable('automations', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  name: text('name').notNull(),
  description: text('description'),

  // Trigger event
  triggerEvent: text('trigger_event').notNull(), // ticket_created, status_changed, etc.

  // Execution order
  priority: integer('priority').notNull().default(0),

  // Status
  isActive: integer('is_active', { mode: 'boolean' }).notNull().default(true),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_automations_workspace').on(table.workspaceId),
}));

/**
 * Automation Conditions - Conditions that must be met for automation to run
 */
export const automationConditions = sqliteTable('automation_conditions', {
  id: text('id').primaryKey(),
  automationId: text('automation_id').notNull().references(() => automations.id, { onDelete: 'cascade' }),

  // Condition definition
  field: text('field').notNull(), // status, priority, assignee, etc.
  operator: text('operator').notNull(), // equals, contains, greater_than, etc.
  value: text('value').notNull(),

  // Logic
  logicalOperator: text('logical_operator').default('AND'), // AND, OR

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  automationIdx: index('idx_automation_conditions_automation').on(table.automationId),
}));

/**
 * Automation Actions - Actions to execute when conditions are met
 */
export const automationActions = sqliteTable('automation_actions', {
  id: text('id').primaryKey(),
  automationId: text('automation_id').notNull().references(() => automations.id, { onDelete: 'cascade' }),

  // Action definition
  actionType: text('action_type').notNull(), // assign, set_status, send_email, add_tag, etc.
  actionConfig: text('action_config', { mode: 'json' }).$type<Record<string, any>>().notNull(),

  // Execution order
  executionOrder: integer('execution_order').notNull().default(0),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  automationIdx: index('idx_automation_actions_automation').on(table.automationId),
}));

/**
 * Canned Replies - Pre-defined response templates
 */
export const cannedReplies = sqliteTable('canned_replies', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  // Template info
  title: text('title').notNull(),
  content: text('content').notNull(),
  shortcut: text('shortcut'), // Quick access shortcut (e.g., "/greeting")

  // Categorization
  categoryId: text('category_id').references(() => categories.id, { onDelete: 'set null' }),

  // Visibility
  isPublic: integer('is_public', { mode: 'boolean' }).notNull().default(true), // Available to all vs agent-specific
  createdBy: text('created_by').references(() => agents.id, { onDelete: 'set null' }),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_canned_replies_workspace').on(table.workspaceId),
  shortcutIdx: index('idx_canned_replies_shortcut').on(table.shortcut),
}));

// ============================================================================
// NOTIFICATIONS & SETTINGS
// ============================================================================

/**
 * Notification Templates - Email/notification templates
 */
export const notificationTemplates = sqliteTable('notification_templates', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  // Template info
  name: text('name').notNull(),
  type: text('type').notNull(), // ticket_assigned, ticket_comment, etc.

  // Content
  subject: text('subject').notNull(),
  bodyHtml: text('body_html').notNull(),
  bodyText: text('body_text'),

  // Status
  isActive: integer('is_active', { mode: 'boolean' }).notNull().default(true),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceTypeIdx: index('idx_notification_templates_workspace_type').on(table.workspaceId, table.type),
}));

/**
 * Notification Settings - User notification preferences
 */
export const notificationSettings = sqliteTable('notification_settings', {
  id: text('id').primaryKey(),
  agentId: text('agent_id').notNull().references(() => agents.id, { onDelete: 'cascade' }).unique(),

  // Preferences (JSON)
  emailNotifications: integer('email_notifications', { mode: 'boolean' }).notNull().default(true),
  pushNotifications: integer('push_notifications', { mode: 'boolean' }).notNull().default(true),

  // Specific notification types (JSON)
  preferences: text('preferences', { mode: 'json' }).$type<Record<string, boolean>>().default(sql`'{}'`),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  agentIdx: index('idx_notification_settings_agent').on(table.agentId),
}));

/**
 * Global Signatures - Email signatures
 */
export const globalSignatures = sqliteTable('global_signatures', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  name: text('name').notNull(),
  content: text('content').notNull(), // HTML content

  // Usage
  isDefault: integer('is_default', { mode: 'boolean' }).notNull().default(false),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
  updatedAt: integer('updated_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_global_signatures_workspace').on(table.workspaceId),
}));

// ============================================================================
// ACTIVITY & AUDIT
// ============================================================================

/**
 * Activities - Audit trail of actions
 */
export const activities = sqliteTable('activities', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  // Actor
  agentId: text('agent_id').references(() => agents.id, { onDelete: 'set null' }),
  agentName: text('agent_name'), // Cached for deleted agents

  // Action
  action: text('action').notNull(), // created, updated, deleted, assigned, etc.
  entityType: text('entity_type').notNull(), // ticket, comment, user, etc.
  entityId: text('entity_id'),

  // Details (JSON)
  details: text('details', { mode: 'json' }).$type<Record<string, any>>(),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  workspaceIdx: index('idx_activities_workspace').on(table.workspaceId),
  entityIdx: index('idx_activities_entity').on(table.entityType, table.entityId),
  createdAtIdx: index('idx_activities_created_at').on(table.createdAt),
}));

// ============================================================================
// AGENT INVITATIONS
// ============================================================================

/**
 * Agent Invitations - Pending agent invitations
 */
export const agentInvitations = sqliteTable('agent_invitations', {
  id: text('id').primaryKey(),
  workspaceId: text('workspace_id').notNull().references(() => workspaces.id, { onDelete: 'cascade' }),

  // Invitation details
  email: text('email').notNull(),
  role: text('role').notNull().default('agent'),
  token: text('token').notNull().unique(),

  // Status
  status: text('status').notNull().default('pending'), // pending, accepted, expired

  // Invited by
  invitedBy: text('invited_by').references(() => agents.id, { onDelete: 'set null' }),

  // Expiration
  expiresAt: integer('expires_at', { mode: 'timestamp' }).notNull(),
  acceptedAt: integer('accepted_at', { mode: 'timestamp' }),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  tokenIdx: index('idx_agent_invitations_token').on(table.token),
  emailIdx: index('idx_agent_invitations_email').on(table.email),
}));

// ============================================================================
// PASSWORD RESET
// ============================================================================

/**
 * Password Reset Tokens - Temporary tokens for password resets
 */
export const passwordResetTokens = sqliteTable('password_reset_tokens', {
  id: text('id').primaryKey(),
  agentId: text('agent_id').notNull().references(() => agents.id, { onDelete: 'cascade' }),

  token: text('token').notNull().unique(),
  expiresAt: integer('expires_at', { mode: 'timestamp' }).notNull(),

  // Status
  isUsed: integer('is_used', { mode: 'boolean' }).notNull().default(false),
  usedAt: integer('used_at', { mode: 'timestamp' }),

  // Metadata
  createdAt: integer('created_at', { mode: 'timestamp' }).notNull().default(sql`(unixepoch())`),
}, (table) => ({
  tokenIdx: index('idx_password_reset_tokens_token').on(table.token),
}));
