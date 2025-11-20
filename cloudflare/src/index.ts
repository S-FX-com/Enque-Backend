import { Hono } from "hono";
import { Env, Context } from "./types/env";
import { corsMiddleware } from "./middleware/cors";
import { errorMiddleware } from "./middleware/error";
import { loggingMiddleware } from "./middleware/logging";

// Import routes
import auth from "./routes/auth";
// Additional routes will be imported as they're created
// import workspaces from './routes/workspaces';
// import tickets from './routes/tickets';
// import users from './routes/users';
// import agents from './routes/agents';
// import teams from './routes/teams';
// import companies from './routes/companies';
// import categories from './routes/categories';
// import comments from './routes/comments';
// import automations from './routes/automations';
// import cannedReplies from './routes/canned-replies';
// import attachments from './routes/attachments';

const app = new Hono<{ Bindings: Env; Variables: Context }>();

// Global middleware
app.use("*", errorMiddleware);
app.use("*", loggingMiddleware);
app.use("*", corsMiddleware());

// Health check
app.get("/health", (c) => {
	return c.json({
		status: "healthy",
		timestamp: Date.now(),
		environment: c.env.ENVIRONMENT,
	});
});

// API v1 routes
const v1 = app.basePath("/v1");

v1.route("/auth", auth);
// v1.route('/workspaces', workspaces);
// v1.route('/tickets', tickets);
// v1.route('/users', users);
// v1.route('/agents', agents);
// v1.route('/teams', teams);
// v1.route('/companies', companies);
// v1.route('/categories', categories);
// v1.route('/comments', comments);
// v1.route('/automations', automations);
// v1.route('/canned-replies', cannedReplies);
// v1.route('/attachments', attachments);

// Root route
app.get("/", (c) => {
	return c.json({
		name: "Enque API",
		version: "1.0.0",
		environment: c.env.ENVIRONMENT,
		message: "Welcome to Enque customer service platform API",
	});
});

// 404 handler
app.notFound((c) => {
	return c.json(
		{
			success: false,
			error: {
				code: "NOT_FOUND",
				message: "Route not found",
			},
		},
		404
	);
});

export default app;

// Durable Object for real-time WebSocket connections
export { RealtimeHandler } from "./durable-objects/realtime";

// Scheduled event handler for email sync
export async function scheduled(event: ScheduledEvent, env: Env, ctx: ExecutionContext) {
	// Email sync logic will be implemented here
	console.log("Email sync triggered at:", new Date(event.scheduledTime).toISOString());

	// This will call the email sync service
	// await syncEmails(env);
}
