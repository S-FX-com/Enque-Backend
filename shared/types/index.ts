import { z } from 'zod';

// ============================================================================
// COMMON TYPES
// ============================================================================

export const TicketStatus = z.enum([
  'Unread',
  'Open',
  'In Progress',
  'Pending',
  'Resolved',
  'Closed'
]);

export const TicketPriority = z.enum([
  'Low',
  'Medium',
  'High',
  'Critical'
]);

export const AgentRole = z.enum([
  'agent',
  'manager',
  'admin'
]);

export const AuthMethod = z.enum([
  'password',
  'microsoft',
  'both'
]);

// ============================================================================
// REQUEST/RESPONSE SCHEMAS
// ============================================================================

// Auth
export const LoginSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8),
});

export const RegisterSchema = z.object({
  email: z.string().email(),
  displayName: z.string().min(2),
  password: z.string().min(8),
  workspaceName: z.string().min(2).optional(),
  workspaceSubdomain: z.string().min(2).optional(),
});

export const MicrosoftCallbackSchema = z.object({
  code: z.string(),
  state: z.string().optional(),
});

// Workspace
export const CreateWorkspaceSchema = z.object({
  name: z.string().min(2),
  subdomain: z.string()
    .min(2)
    .regex(/^[a-z0-9-]+$/, 'Subdomain must be lowercase alphanumeric with hyphens'),
});

export const UpdateWorkspaceSchema = z.object({
  name: z.string().min(2).optional(),
  isActive: z.boolean().optional(),
});

// Ticket
export const CreateTicketSchema = z.object({
  subject: z.string().min(1),
  fromEmail: z.string().email(),
  fromName: z.string().min(1),
  bodyHtml: z.string().optional(),
  bodyText: z.string().optional(),
  priority: TicketPriority.optional(),
  categoryId: z.string().optional(),
  assignedToId: z.string().optional(),
  teamId: z.string().optional(),
  tags: z.array(z.string()).optional(),
});

export const UpdateTicketSchema = z.object({
  subject: z.string().min(1).optional(),
  status: TicketStatus.optional(),
  priority: TicketPriority.optional(),
  assignedToId: z.string().nullable().optional(),
  teamId: z.string().nullable().optional(),
  categoryId: z.string().nullable().optional(),
  tags: z.array(z.string()).optional(),
  isRead: z.boolean().optional(),
});

export const ReplyToTicketSchema = z.object({
  content: z.string().min(1),
  isInternal: z.boolean().default(false),
  sendViaEmail: z.boolean().default(false),
  toEmails: z.array(z.string().email()).optional(),
  ccEmails: z.array(z.string().email()).optional(),
});

// Comment
export const CreateCommentSchema = z.object({
  content: z.string().min(1),
  isInternal: z.boolean().default(false),
});

// User
export const CreateUserSchema = z.object({
  email: z.string().email(),
  name: z.string().min(2),
  companyId: z.string().optional(),
  phone: z.string().optional(),
  timezone: z.string().optional(),
  language: z.string().optional(),
});

export const UpdateUserSchema = z.object({
  name: z.string().min(2).optional(),
  companyId: z.string().nullable().optional(),
  phone: z.string().optional(),
  timezone: z.string().optional(),
  language: z.string().optional(),
  avatarUrl: z.string().url().optional(),
});

// Agent
export const CreateAgentSchema = z.object({
  email: z.string().email(),
  displayName: z.string().min(2),
  password: z.string().min(8).optional(),
  role: AgentRole.default('agent'),
  authMethod: AuthMethod.default('password'),
});

export const UpdateAgentSchema = z.object({
  displayName: z.string().min(2).optional(),
  role: AgentRole.optional(),
  isActive: z.boolean().optional(),
  avatarUrl: z.string().url().optional(),
});

export const InviteAgentSchema = z.object({
  email: z.string().email(),
  role: AgentRole.default('agent'),
});

// Team
export const CreateTeamSchema = z.object({
  name: z.string().min(2),
  description: z.string().optional(),
});

export const UpdateTeamSchema = z.object({
  name: z.string().min(2).optional(),
  description: z.string().optional(),
});

export const AddTeamMemberSchema = z.object({
  agentId: z.string(),
  isLead: z.boolean().default(false),
});

// Company
export const CreateCompanySchema = z.object({
  name: z.string().min(2),
  domain: z.string().optional(),
  website: z.string().url().optional(),
  phone: z.string().optional(),
  notes: z.string().optional(),
});

export const UpdateCompanySchema = z.object({
  name: z.string().min(2).optional(),
  domain: z.string().optional(),
  website: z.string().url().optional(),
  phone: z.string().optional(),
  notes: z.string().optional(),
});

// Category
export const CreateCategorySchema = z.object({
  name: z.string().min(1),
  color: z.string().regex(/^#[0-9A-Fa-f]{6}$/).optional(),
});

export const UpdateCategorySchema = z.object({
  name: z.string().min(1).optional(),
  color: z.string().regex(/^#[0-9A-Fa-f]{6}$/).optional(),
});

// Canned Reply
export const CreateCannedReplySchema = z.object({
  title: z.string().min(1),
  content: z.string().min(1),
  shortcut: z.string().optional(),
  categoryId: z.string().optional(),
  isPublic: z.boolean().default(true),
});

export const UpdateCannedReplySchema = z.object({
  title: z.string().min(1).optional(),
  content: z.string().min(1).optional(),
  shortcut: z.string().optional(),
  categoryId: z.string().nullable().optional(),
  isPublic: z.boolean().optional(),
});

// Automation
export const CreateAutomationSchema = z.object({
  name: z.string().min(1),
  description: z.string().optional(),
  triggerEvent: z.string(),
  priority: z.number().int().default(0),
  isActive: z.boolean().default(true),
  conditions: z.array(z.object({
    field: z.string(),
    operator: z.string(),
    value: z.string(),
    logicalOperator: z.enum(['AND', 'OR']).default('AND'),
  })),
  actions: z.array(z.object({
    actionType: z.string(),
    actionConfig: z.record(z.any()),
    executionOrder: z.number().int().default(0),
  })),
});

export const UpdateAutomationSchema = z.object({
  name: z.string().min(1).optional(),
  description: z.string().optional(),
  isActive: z.boolean().optional(),
  priority: z.number().int().optional(),
});

// Mailbox Connection
export const CreateMailboxConnectionSchema = z.object({
  email: z.string().email(),
  displayName: z.string().optional(),
  mailboxType: z.enum(['user', 'shared']).default('user'),
});

export const UpdateMailboxConnectionSchema = z.object({
  displayName: z.string().optional(),
  isActive: z.boolean().optional(),
});

// ============================================================================
// TYPE EXPORTS
// ============================================================================

export type LoginInput = z.infer<typeof LoginSchema>;
export type RegisterInput = z.infer<typeof RegisterSchema>;
export type MicrosoftCallbackInput = z.infer<typeof MicrosoftCallbackSchema>;

export type CreateWorkspaceInput = z.infer<typeof CreateWorkspaceSchema>;
export type UpdateWorkspaceInput = z.infer<typeof UpdateWorkspaceSchema>;

export type CreateTicketInput = z.infer<typeof CreateTicketSchema>;
export type UpdateTicketInput = z.infer<typeof UpdateTicketSchema>;
export type ReplyToTicketInput = z.infer<typeof ReplyToTicketSchema>;

export type CreateCommentInput = z.infer<typeof CreateCommentSchema>;

export type CreateUserInput = z.infer<typeof CreateUserSchema>;
export type UpdateUserInput = z.infer<typeof UpdateUserSchema>;

export type CreateAgentInput = z.infer<typeof CreateAgentSchema>;
export type UpdateAgentInput = z.infer<typeof UpdateAgentSchema>;
export type InviteAgentInput = z.infer<typeof InviteAgentSchema>;

export type CreateTeamInput = z.infer<typeof CreateTeamSchema>;
export type UpdateTeamInput = z.infer<typeof UpdateTeamSchema>;
export type AddTeamMemberInput = z.infer<typeof AddTeamMemberSchema>;

export type CreateCompanyInput = z.infer<typeof CreateCompanySchema>;
export type UpdateCompanyInput = z.infer<typeof UpdateCompanySchema>;

export type CreateCategoryInput = z.infer<typeof CreateCategorySchema>;
export type UpdateCategoryInput = z.infer<typeof UpdateCategorySchema>;

export type CreateCannedReplyInput = z.infer<typeof CreateCannedReplySchema>;
export type UpdateCannedReplyInput = z.infer<typeof UpdateCannedReplySchema>;

export type CreateAutomationInput = z.infer<typeof CreateAutomationSchema>;
export type UpdateAutomationInput = z.infer<typeof UpdateAutomationSchema>;

export type CreateMailboxConnectionInput = z.infer<typeof CreateMailboxConnectionSchema>;
export type UpdateMailboxConnectionInput = z.infer<typeof UpdateMailboxConnectionSchema>;
