import { Hono } from "hono";
import { zValidator } from "@hono/zod-validator";
import { eq, and } from "drizzle-orm";
import { Env } from "../types/env";
import { createDb, agents, agentWorkspaces, workspaces, microsoftTokens } from "../db";
import { LoginSchema, RegisterSchema, MicrosoftCallbackSchema } from "@/types";
import { generateId, hashPassword, verifyPassword } from "../utils/crypto";
import { createToken } from "../utils/jwt";
import { success, error, created, unauthorized } from "../utils/response";
import { MicrosoftGraphService } from "../services/microsoft-graph";
import { authMiddleware } from "../middleware/auth";
import { rateLimitMiddleware, RateLimits } from "../middleware/rate-limit";

const auth = new Hono<{ Bindings: Env }>();

/**
 * POST /auth/register
 * Register a new agent and create workspace
 */
auth.post("/register", rateLimitMiddleware(RateLimits.auth), zValidator("json", RegisterSchema), async (c) => {
	const body = c.req.valid("json");
	const db = createDb(c.env.DB);

	// Check if agent already exists
	const existingAgent = await db.select().from(agents).where(eq(agents.email, body.email)).get();

	if (existingAgent) {
		return error("Email already registered", "EMAIL_EXISTS", 409);
	}

	// Hash password
	const passwordHash = await hashPassword(body.password);

	// Create agent
	const agentId = generateId("agent");
	const newAgent = await db
		.insert(agents)
		.values({
			id: agentId,
			email: body.email,
			displayName: body.displayName,
			passwordHash,
			role: "admin", // First user is admin
			authMethod: "password",
			isActive: true,
		})
		.returning()
		.get();

	// Create workspace if provided
	let workspaceId: string | undefined;

	if (body.workspaceName && body.workspaceSubdomain) {
		// Check if subdomain is available
		const existingWorkspace = await db.select().from(workspaces).where(eq(workspaces.subdomain, body.workspaceSubdomain)).get();

		if (existingWorkspace) {
			return error("Subdomain already taken", "SUBDOMAIN_EXISTS", 409);
		}

		workspaceId = generateId("workspace");

		await db
			.insert(workspaces)
			.values({
				id: workspaceId,
				name: body.workspaceName,
				subdomain: body.workspaceSubdomain,
				isActive: true,
			})
			.run();

		// Link agent to workspace
		await db
			.insert(agentWorkspaces)
			.values({
				id: generateId("aw"),
				agentId,
				workspaceId,
				role: "admin",
			})
			.run();
	}

	// Create JWT token
	const token = await createToken(
		{
			sub: newAgent.id,
			email: newAgent.email,
			role: newAgent.role,
			workspaceId,
		},
		c.env.JWT_SECRET
	);

	return created({
		token,
		agent: {
			id: newAgent.id,
			email: newAgent.email,
			displayName: newAgent.displayName,
			role: newAgent.role,
		},
		workspaceId,
	});
});

/**
 * POST /auth/login
 * Login with email and password
 */
auth.post("/login", rateLimitMiddleware(RateLimits.auth), zValidator("json", LoginSchema), async (c) => {
	const { email, password } = c.req.valid("json");
	const db = createDb(c.env.DB);

	// Find agent
	const agent = await db.select().from(agents).where(eq(agents.email, email)).get();

	if (!agent || !agent.passwordHash) {
		return unauthorized("Invalid credentials");
	}

	// Verify password
	const isValidPassword = await verifyPassword(password, agent.passwordHash);

	if (!isValidPassword) {
		return unauthorized("Invalid credentials");
	}

	// Check if agent is active
	if (!agent.isActive) {
		return unauthorized("Account is disabled");
	}

	// Get agent's workspaces
	const agentWorkspacesList = await db
		.select({
			workspaceId: agentWorkspaces.workspaceId,
			role: agentWorkspaces.role,
		})
		.from(agentWorkspaces)
		.where(eq(agentWorkspaces.agentId, agent.id))
		.all();

	// Use first workspace as default
	const defaultWorkspace = agentWorkspacesList[0];

	// Create JWT token
	const token = await createToken(
		{
			sub: agent.id,
			email: agent.email,
			role: agent.role,
			workspaceId: defaultWorkspace?.workspaceId,
		},
		c.env.JWT_SECRET
	);

	// Update last login
	await db.update(agents).set({ lastLoginAt: new Date() }).where(eq(agents.id, agent.id)).run();

	return success({
		token,
		agent: {
			id: agent.id,
			email: agent.email,
			displayName: agent.displayName,
			role: agent.role,
			avatarUrl: agent.avatarUrl,
		},
		workspaces: agentWorkspacesList,
	});
});

/**
 * GET /auth/me
 * Get current authenticated agent
 */
auth.get("/me", authMiddleware, async (c) => {
	const agentContext = c.get("agent");
	const db = createDb(c.env.DB);

	if (!agentContext) {
		return unauthorized();
	}

	// Get full agent details
	const agent = await db.select().from(agents).where(eq(agents.id, agentContext.id)).get();

	if (!agent) {
		return unauthorized();
	}

	// Get agent's workspaces
	const agentWorkspacesList = await db
		.select({
			id: workspaces.id,
			name: workspaces.name,
			subdomain: workspaces.subdomain,
			role: agentWorkspaces.role,
		})
		.from(agentWorkspaces)
		.innerJoin(workspaces, eq(agentWorkspaces.workspaceId, workspaces.id))
		.where(eq(agentWorkspaces.agentId, agent.id))
		.all();

	return success({
		id: agent.id,
		email: agent.email,
		displayName: agent.displayName,
		role: agent.role,
		avatarUrl: agent.avatarUrl,
		authMethod: agent.authMethod,
		isActive: agent.isActive,
		workspaces: agentWorkspacesList,
	});
});

/**
 * GET /auth/microsoft
 * Get Microsoft OAuth authorization URL
 */
auth.get("/microsoft", async (c) => {
	const graphService = new MicrosoftGraphService(c.env);
	const state = generateId(); // Used to prevent CSRF

	// Store state in KV for validation
	await c.env.CACHE.put(`oauth_state:${state}`, "valid", { expirationTtl: 600 }); // 10 minutes

	const authUrl = graphService.getAuthorizationUrl(state);

	return success({ authUrl, state });
});

/**
 * GET /auth/microsoft/callback
 * Handle Microsoft OAuth callback
 */
auth.get("/microsoft/callback", zValidator("query", MicrosoftCallbackSchema), async (c) => {
	const { code, state } = c.req.valid("query");
	const db = createDb(c.env.DB);
	const graphService = new MicrosoftGraphService(c.env);

	// Validate state (CSRF protection)
	if (state) {
		const storedState = await c.env.CACHE.get(`oauth_state:${state}`);
		if (!storedState) {
			return error("Invalid state parameter", "INVALID_STATE", 400);
		}

		// Delete used state
		await c.env.CACHE.delete(`oauth_state:${state}`);
	}

	// Exchange code for token
	const tokenResponse = await graphService.getTokenFromCode(code);

	// Get user info from Microsoft
	const microsoftUser = await graphService.getCurrentUser(tokenResponse.access_token);

	// Check if agent exists
	let agent = await db.select().from(agents).where(eq(agents.microsoftId, microsoftUser.id)).get();

	let isNewAgent = false;

	// Create agent if doesn't exist
	if (!agent) {
		const agentId = generateId("agent");

		agent = await db
			.insert(agents)
			.values({
				id: agentId,
				email: microsoftUser.mail || microsoftUser.userPrincipalName,
				displayName: microsoftUser.displayName,
				microsoftId: microsoftUser.id,
				authMethod: "microsoft",
				role: "agent",
				isActive: true,
			})
			.returning()
			.get();

		isNewAgent = true;
	}

	// Store Microsoft tokens
	const encryptedTokens = await graphService.encryptTokens(tokenResponse);

	await db
		.insert(microsoftTokens)
		.values({
			id: generateId("token"),
			workspaceId: null as any, // Will be set when agent joins workspace
			agentId: agent.id,
			mailboxConnectionId: null as any,
			accessToken: encryptedTokens.accessToken,
			refreshToken: encryptedTokens.refreshToken || "",
			idToken: encryptedTokens.idToken,
			tokenType: tokenResponse.token_type,
			scope: tokenResponse.scope,
			expiresAt: new Date(Date.now() + tokenResponse.expires_in * 1000),
			microsoftUserId: microsoftUser.id,
			userEmail: microsoftUser.mail || microsoftUser.userPrincipalName,
		})
		.run();

	// Create JWT
	const jwtToken = await createToken(
		{
			sub: agent.id,
			email: agent.email,
			role: agent.role,
		},
		c.env.JWT_SECRET
	);

	// Update last login
	await db.update(agents).set({ lastLoginAt: new Date() }).where(eq(agents.id, agent.id)).run();

	return success({
		token: jwtToken,
		agent: {
			id: agent.id,
			email: agent.email,
			displayName: agent.displayName,
			role: agent.role,
		},
		isNewAgent,
	});
});

/**
 * POST /auth/logout
 * Logout (client-side token removal, server-side cleanup if needed)
 */
auth.post("/logout", authMiddleware, async (c) => {
	// In a stateless JWT system, logout is primarily client-side
	// But we can add server-side token blacklisting if needed using KV

	const agentContext = c.get("agent");

	if (agentContext) {
		// Optional: Add token to blacklist in KV
		// This prevents the token from being used until it expires
		const token = c.req.header("Authorization")?.substring(7);
		if (token) {
			await c.env.CACHE.put(`blacklist:${token}`, "true", { expirationTtl: 7 * 24 * 3600 }); // 7 days
		}
	}

	return success({ message: "Logged out successfully" });
});

export default auth;
