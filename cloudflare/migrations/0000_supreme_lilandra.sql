CREATE TABLE `activities` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`agent_id` text,
	`agent_name` text,
	`action` text NOT NULL,
	`entity_type` text NOT NULL,
	`entity_id` text,
	`details` text,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`agent_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `agent_invitations` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`email` text NOT NULL,
	`role` text DEFAULT 'agent' NOT NULL,
	`token` text NOT NULL,
	`status` text DEFAULT 'pending' NOT NULL,
	`invited_by` text,
	`expires_at` integer NOT NULL,
	`accepted_at` integer,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`invited_by`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `agent_workspaces` (
	`id` text PRIMARY KEY NOT NULL,
	`agent_id` text NOT NULL,
	`workspace_id` text NOT NULL,
	`role` text DEFAULT 'agent' NOT NULL,
	`joined_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`agent_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `agents` (
	`id` text PRIMARY KEY NOT NULL,
	`email` text NOT NULL,
	`display_name` text NOT NULL,
	`password_hash` text,
	`microsoft_id` text,
	`avatar_url` text,
	`role` text DEFAULT 'agent' NOT NULL,
	`auth_method` text DEFAULT 'password' NOT NULL,
	`is_active` integer DEFAULT true NOT NULL,
	`last_login_at` integer,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL
);
--> statement-breakpoint
CREATE TABLE `automation_actions` (
	`id` text PRIMARY KEY NOT NULL,
	`automation_id` text NOT NULL,
	`action_type` text NOT NULL,
	`action_config` text NOT NULL,
	`execution_order` integer DEFAULT 0 NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`automation_id`) REFERENCES `automations`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `automation_conditions` (
	`id` text PRIMARY KEY NOT NULL,
	`automation_id` text NOT NULL,
	`field` text NOT NULL,
	`operator` text NOT NULL,
	`value` text NOT NULL,
	`logical_operator` text DEFAULT 'AND',
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`automation_id`) REFERENCES `automations`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `automations` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`name` text NOT NULL,
	`description` text,
	`trigger_event` text NOT NULL,
	`priority` integer DEFAULT 0 NOT NULL,
	`is_active` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `canned_replies` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`title` text NOT NULL,
	`content` text NOT NULL,
	`shortcut` text,
	`category_id` text,
	`is_public` integer DEFAULT true NOT NULL,
	`created_by` text,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`category_id`) REFERENCES `categories`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`created_by`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `categories` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`name` text NOT NULL,
	`color` text DEFAULT '#3b82f6',
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `comments` (
	`id` text PRIMARY KEY NOT NULL,
	`ticket_id` text NOT NULL,
	`agent_id` text,
	`author_name` text NOT NULL,
	`author_email` text,
	`content` text NOT NULL,
	`content_type` text DEFAULT 'text' NOT NULL,
	`is_sent_via_email` integer DEFAULT false NOT NULL,
	`email_message_id` text,
	`is_internal` integer DEFAULT false NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`ticket_id`) REFERENCES `tickets`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`agent_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `companies` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`name` text NOT NULL,
	`domain` text,
	`website` text,
	`phone` text,
	`notes` text,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `email_sync_configs` (
	`id` text PRIMARY KEY NOT NULL,
	`mailbox_connection_id` text NOT NULL,
	`sync_folder` text DEFAULT 'Inbox' NOT NULL,
	`sync_enabled` integer DEFAULT true NOT NULL,
	`default_priority` text DEFAULT 'Medium',
	`default_category_id` text,
	`auto_assign_to_team_id` text,
	`skip_internal_emails` integer DEFAULT false NOT NULL,
	`mark_as_read` integer DEFAULT false NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`mailbox_connection_id`) REFERENCES `mailbox_connections`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`default_category_id`) REFERENCES `categories`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`auto_assign_to_team_id`) REFERENCES `teams`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `email_ticket_mappings` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`message_id` text NOT NULL,
	`conversation_id` text,
	`ticket_id` text NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`ticket_id`) REFERENCES `tickets`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `global_signatures` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`name` text NOT NULL,
	`content` text NOT NULL,
	`is_default` integer DEFAULT false NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `mailbox_connections` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`agent_id` text,
	`email` text NOT NULL,
	`display_name` text,
	`mailbox_type` text DEFAULT 'user' NOT NULL,
	`is_active` integer DEFAULT true NOT NULL,
	`last_sync_at` integer,
	`last_sync_status` text,
	`last_sync_error` text,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`agent_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `microsoft_integrations` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`client_id` text NOT NULL,
	`client_secret` text NOT NULL,
	`tenant_id` text NOT NULL,
	`is_active` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `microsoft_tokens` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`agent_id` text,
	`mailbox_connection_id` text,
	`access_token` text NOT NULL,
	`refresh_token` text,
	`id_token` text,
	`token_type` text DEFAULT 'Bearer',
	`scope` text,
	`expires_at` integer,
	`microsoft_user_id` text,
	`user_email` text,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`agent_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`mailbox_connection_id`) REFERENCES `mailbox_connections`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `notification_settings` (
	`id` text PRIMARY KEY NOT NULL,
	`agent_id` text NOT NULL,
	`email_notifications` integer DEFAULT true NOT NULL,
	`push_notifications` integer DEFAULT true NOT NULL,
	`preferences` text DEFAULT '{}',
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`agent_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `notification_templates` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`name` text NOT NULL,
	`type` text NOT NULL,
	`subject` text NOT NULL,
	`body_html` text NOT NULL,
	`body_text` text,
	`is_active` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `password_reset_tokens` (
	`id` text PRIMARY KEY NOT NULL,
	`agent_id` text NOT NULL,
	`token` text NOT NULL,
	`expires_at` integer NOT NULL,
	`is_used` integer DEFAULT false NOT NULL,
	`used_at` integer,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`agent_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `scheduled_comments` (
	`id` text PRIMARY KEY NOT NULL,
	`ticket_id` text NOT NULL,
	`agent_id` text NOT NULL,
	`content` text NOT NULL,
	`scheduled_for` integer NOT NULL,
	`is_sent` integer DEFAULT false NOT NULL,
	`sent_at` integer,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`ticket_id`) REFERENCES `tickets`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`agent_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `team_members` (
	`id` text PRIMARY KEY NOT NULL,
	`team_id` text NOT NULL,
	`agent_id` text NOT NULL,
	`is_lead` integer DEFAULT false NOT NULL,
	`joined_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`team_id`) REFERENCES `teams`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`agent_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `teams` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`name` text NOT NULL,
	`description` text,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `ticket_attachments` (
	`id` text PRIMARY KEY NOT NULL,
	`ticket_id` text NOT NULL,
	`filename` text NOT NULL,
	`content_type` text,
	`size` integer,
	`r2_key` text NOT NULL,
	`r2_url` text,
	`graph_attachment_id` text,
	`uploaded_by` text,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`ticket_id`) REFERENCES `tickets`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`uploaded_by`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `ticket_bodies` (
	`id` text PRIMARY KEY NOT NULL,
	`ticket_id` text NOT NULL,
	`body_html` text,
	`body_text` text,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`ticket_id`) REFERENCES `tickets`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `tickets` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`conversation_id` text,
	`message_id` text,
	`subject` text NOT NULL,
	`body_preview` text,
	`priority` text DEFAULT 'Medium' NOT NULL,
	`status` text DEFAULT 'Unread' NOT NULL,
	`from_email` text NOT NULL,
	`from_name` text NOT NULL,
	`user_id` text,
	`assigned_to_id` text,
	`team_id` text,
	`category_id` text,
	`to_emails` text,
	`cc_emails` text,
	`has_attachments` integer DEFAULT false NOT NULL,
	`is_read` integer DEFAULT false NOT NULL,
	`importance` text DEFAULT 'normal',
	`tags` text DEFAULT '[]',
	`received_date_time` integer,
	`first_response_at` integer,
	`resolved_at` integer,
	`closed_at` integer,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`user_id`) REFERENCES `users`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`assigned_to_id`) REFERENCES `agents`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`team_id`) REFERENCES `teams`(`id`) ON UPDATE no action ON DELETE set null,
	FOREIGN KEY (`category_id`) REFERENCES `categories`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `users` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`email` text NOT NULL,
	`name` text NOT NULL,
	`company_id` text,
	`avatar_url` text,
	`phone` text,
	`timezone` text,
	`language` text DEFAULT 'en',
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade,
	FOREIGN KEY (`company_id`) REFERENCES `companies`(`id`) ON UPDATE no action ON DELETE set null
);
--> statement-breakpoint
CREATE TABLE `workflows` (
	`id` text PRIMARY KEY NOT NULL,
	`workspace_id` text NOT NULL,
	`name` text NOT NULL,
	`description` text,
	`trigger_type` text NOT NULL,
	`trigger_config` text,
	`actions` text NOT NULL,
	`is_active` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL,
	FOREIGN KEY (`workspace_id`) REFERENCES `workspaces`(`id`) ON UPDATE no action ON DELETE cascade
);
--> statement-breakpoint
CREATE TABLE `workspaces` (
	`id` text PRIMARY KEY NOT NULL,
	`name` text NOT NULL,
	`subdomain` text NOT NULL,
	`is_active` integer DEFAULT true NOT NULL,
	`created_at` integer DEFAULT (unixepoch()) NOT NULL,
	`updated_at` integer DEFAULT (unixepoch()) NOT NULL
);
--> statement-breakpoint
CREATE INDEX `idx_activities_workspace` ON `activities` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_activities_entity` ON `activities` (`entity_type`,`entity_id`);--> statement-breakpoint
CREATE INDEX `idx_activities_created_at` ON `activities` (`created_at`);--> statement-breakpoint
CREATE UNIQUE INDEX `agent_invitations_token_unique` ON `agent_invitations` (`token`);--> statement-breakpoint
CREATE INDEX `idx_agent_invitations_token` ON `agent_invitations` (`token`);--> statement-breakpoint
CREATE INDEX `idx_agent_invitations_email` ON `agent_invitations` (`email`);--> statement-breakpoint
CREATE INDEX `idx_agent_workspaces_agent_workspace` ON `agent_workspaces` (`agent_id`,`workspace_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `agents_email_unique` ON `agents` (`email`);--> statement-breakpoint
CREATE UNIQUE INDEX `agents_microsoft_id_unique` ON `agents` (`microsoft_id`);--> statement-breakpoint
CREATE INDEX `idx_agents_email` ON `agents` (`email`);--> statement-breakpoint
CREATE INDEX `idx_agents_microsoft_id` ON `agents` (`microsoft_id`);--> statement-breakpoint
CREATE INDEX `idx_automation_actions_automation` ON `automation_actions` (`automation_id`);--> statement-breakpoint
CREATE INDEX `idx_automation_conditions_automation` ON `automation_conditions` (`automation_id`);--> statement-breakpoint
CREATE INDEX `idx_automations_workspace` ON `automations` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_canned_replies_workspace` ON `canned_replies` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_canned_replies_shortcut` ON `canned_replies` (`shortcut`);--> statement-breakpoint
CREATE INDEX `idx_categories_workspace` ON `categories` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_comments_ticket` ON `comments` (`ticket_id`);--> statement-breakpoint
CREATE INDEX `idx_comments_agent` ON `comments` (`agent_id`);--> statement-breakpoint
CREATE INDEX `idx_comments_internal` ON `comments` (`is_internal`);--> statement-breakpoint
CREATE INDEX `idx_companies_workspace` ON `companies` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_companies_domain` ON `companies` (`domain`);--> statement-breakpoint
CREATE UNIQUE INDEX `email_sync_configs_mailbox_connection_id_unique` ON `email_sync_configs` (`mailbox_connection_id`);--> statement-breakpoint
CREATE INDEX `idx_email_sync_configs_mailbox` ON `email_sync_configs` (`mailbox_connection_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `email_ticket_mappings_message_id_unique` ON `email_ticket_mappings` (`message_id`);--> statement-breakpoint
CREATE INDEX `idx_email_ticket_mappings_message_id` ON `email_ticket_mappings` (`message_id`);--> statement-breakpoint
CREATE INDEX `idx_email_ticket_mappings_ticket` ON `email_ticket_mappings` (`ticket_id`);--> statement-breakpoint
CREATE INDEX `idx_global_signatures_workspace` ON `global_signatures` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_mailbox_connections_workspace` ON `mailbox_connections` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_mailbox_connections_email` ON `mailbox_connections` (`email`);--> statement-breakpoint
CREATE INDEX `idx_microsoft_integrations_workspace` ON `microsoft_integrations` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_microsoft_tokens_workspace_agent` ON `microsoft_tokens` (`workspace_id`,`agent_id`);--> statement-breakpoint
CREATE INDEX `idx_microsoft_tokens_mailbox` ON `microsoft_tokens` (`mailbox_connection_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `notification_settings_agent_id_unique` ON `notification_settings` (`agent_id`);--> statement-breakpoint
CREATE INDEX `idx_notification_settings_agent` ON `notification_settings` (`agent_id`);--> statement-breakpoint
CREATE INDEX `idx_notification_templates_workspace_type` ON `notification_templates` (`workspace_id`,`type`);--> statement-breakpoint
CREATE UNIQUE INDEX `password_reset_tokens_token_unique` ON `password_reset_tokens` (`token`);--> statement-breakpoint
CREATE INDEX `idx_password_reset_tokens_token` ON `password_reset_tokens` (`token`);--> statement-breakpoint
CREATE INDEX `idx_scheduled_comments_ticket` ON `scheduled_comments` (`ticket_id`);--> statement-breakpoint
CREATE INDEX `idx_scheduled_comments_scheduled_for` ON `scheduled_comments` (`scheduled_for`);--> statement-breakpoint
CREATE INDEX `idx_scheduled_comments_is_sent` ON `scheduled_comments` (`is_sent`);--> statement-breakpoint
CREATE INDEX `idx_team_members_team_agent` ON `team_members` (`team_id`,`agent_id`);--> statement-breakpoint
CREATE INDEX `idx_teams_workspace` ON `teams` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_attachments_ticket` ON `ticket_attachments` (`ticket_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `ticket_bodies_ticket_id_unique` ON `ticket_bodies` (`ticket_id`);--> statement-breakpoint
CREATE INDEX `idx_ticket_bodies_ticket` ON `ticket_bodies` (`ticket_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `tickets_message_id_unique` ON `tickets` (`message_id`);--> statement-breakpoint
CREATE INDEX `idx_tickets_workspace` ON `tickets` (`workspace_id`);--> statement-breakpoint
CREATE INDEX `idx_tickets_status` ON `tickets` (`status`);--> statement-breakpoint
CREATE INDEX `idx_tickets_assigned_to` ON `tickets` (`assigned_to_id`);--> statement-breakpoint
CREATE INDEX `idx_tickets_message_id` ON `tickets` (`message_id`);--> statement-breakpoint
CREATE INDEX `idx_tickets_conversation` ON `tickets` (`conversation_id`);--> statement-breakpoint
CREATE INDEX `idx_tickets_from_email` ON `tickets` (`from_email`);--> statement-breakpoint
CREATE INDEX `idx_tickets_user` ON `tickets` (`user_id`);--> statement-breakpoint
CREATE INDEX `idx_users_workspace_email` ON `users` (`workspace_id`,`email`);--> statement-breakpoint
CREATE INDEX `idx_users_company` ON `users` (`company_id`);--> statement-breakpoint
CREATE INDEX `idx_workflows_workspace` ON `workflows` (`workspace_id`);--> statement-breakpoint
CREATE UNIQUE INDEX `workspaces_subdomain_unique` ON `workspaces` (`subdomain`);--> statement-breakpoint
CREATE INDEX `idx_workspaces_subdomain` ON `workspaces` (`subdomain`);