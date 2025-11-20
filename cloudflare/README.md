# Enque API - Cloudflare Workers Implementation

Modern, serverless customer service platform built with Hono + TypeScript on Cloudflare Workers.

## 🚀 Technology Stack

- **Runtime**: Cloudflare Workers (Edge compute)
- **Framework**: Hono (Ultra-fast web framework)
- **Database**: Cloudflare D1 (Serverless SQLite)
- **ORM**: Drizzle ORM
- **Storage**: Cloudflare R2 (S3-compatible)
- **Cache**: Cloudflare KV
- **WebSockets**: Durable Objects
- **Language**: TypeScript 5.x
- **Validation**: Zod
- **Auth**: JWT + Microsoft OAuth 2.0

## 📁 Project Structure

```
cloudflare/
├── src/
│   ├── db/
│   │   ├── schema.ts          # Drizzle ORM database schema
│   │   └── index.ts           # Database client
│   ├── durable-objects/
│   │   └── realtime.ts        # WebSocket handler
│   ├── middleware/
│   │   ├── auth.ts            # Authentication middleware
│   │   ├── cors.ts            # CORS configuration
│   │   ├── error.ts           # Error handling
│   │   ├── logging.ts         # Request logging
│   │   └── rate-limit.ts      # Rate limiting (KV-based)
│   ├── routes/
│   │   ├── auth.ts            # Authentication routes
│   │   ├── workspaces.ts      # Workspace management
│   │   ├── tickets.ts         # Ticket/task management
│   │   ├── users.ts           # Customer management
│   │   ├── agents.ts          # Agent management
│   │   ├── teams.ts           # Team management
│   │   └── ...                # Other routes
│   ├── services/
│   │   ├── microsoft-graph.ts # Microsoft Graph API
│   │   └── storage.ts         # R2 storage service
│   ├── types/
│   │   └── env.ts             # TypeScript types
│   ├── utils/
│   │   ├── crypto.ts          # Encryption & hashing
│   │   ├── jwt.ts             # JWT utilities
│   │   ├── logger.ts          # Logging utilities
│   │   └── response.ts        # API response helpers
│   └── index.ts               # Main application entry
├── migrations/                 # D1 database migrations
├── shared/
│   └── types/
│       └── index.ts           # Shared Zod schemas
├── wrangler.toml              # Production config
├── wrangler.staging.toml      # Staging config
├── package.json
├── tsconfig.json
└── drizzle.config.ts

```

## 🌟 Key Features

### Core Functionality
- ✅ Multi-tenant workspace system
- ✅ Ticket/Task management
- ✅ Microsoft 365 email integration
- ✅ Real-time updates via WebSockets
- ✅ File attachments (R2 storage)
- ✅ Automation & workflows
- ✅ Canned replies
- ✅ Teams & agent management
- ✅ Customer (user) management
- ✅ Analytics & reporting

### Cloudflare-Native Features
- ⚡ Global edge deployment (300+ locations)
- ⚡ Sub-1ms cold starts
- ⚡ Automatic scaling (0 to millions)
- ⚡ Built-in DDoS protection
- ⚡ KV-based caching
- ⚡ Rate limiting
- ⚡ Cron triggers for email sync

## 🛠️ Setup & Development

### Prerequisites

- Node.js 18+
- npm or pnpm
- Cloudflare account
- Wrangler CLI (`npm install -g wrangler`)

### Installation

```bash
cd cloudflare
npm install
```

### Configure Cloudflare Services

#### 1. Create D1 Database

```bash
# Create production database
wrangler d1 create enque-db

# Create staging database
wrangler d1 create enque-db-staging
```

Copy the `database_id` from the output and update `wrangler.toml` and `wrangler.staging.toml`.

#### 2. Create R2 Buckets

```bash
# Create production bucket
wrangler r2 bucket create enque-storage

# Create staging bucket
wrangler r2 bucket create enque-storage-staging
```

#### 3. Create KV Namespaces

```bash
# Create production KV
wrangler kv:namespace create "CACHE"

# Create staging KV
wrangler kv:namespace create "CACHE" --preview
```

Copy the `id` values and update your wrangler config files.

#### 4. Set Secrets

```bash
# Production secrets
wrangler secret put JWT_SECRET
wrangler secret put MICROSOFT_CLIENT_ID
wrangler secret put MICROSOFT_CLIENT_SECRET
wrangler secret put MICROSOFT_TENANT_ID
wrangler secret put DATABASE_ENCRYPTION_KEY

# Staging secrets (add --env staging)
wrangler secret put JWT_SECRET --env staging
wrangler secret put MICROSOFT_CLIENT_ID --env staging
wrangler secret put MICROSOFT_CLIENT_SECRET --env staging
wrangler secret put MICROSOFT_TENANT_ID --env staging
wrangler secret put DATABASE_ENCRYPTION_KEY --env staging
```

### Database Setup

#### Generate migration SQL

```bash
npm run db:generate
```

#### Apply migrations

```bash
# Production
npm run db:migrate

# Staging
npm run db:migrate:staging
```

#### View database

```bash
npm run db:studio
```

### Development

```bash
# Start local development server
npm run dev

# Start with staging config
npm run dev:staging
```

The API will be available at `http://localhost:8787`

### Deployment

```bash
# Deploy to production
npm run deploy

# Deploy to staging
npm run deploy:staging
```

## 🔐 Authentication

### JWT Authentication

All authenticated routes require a `Bearer` token:

```bash
Authorization: Bearer <jwt_token>
```

### Microsoft OAuth Flow

1. **Get authorization URL**:
   ```
   GET /v1/auth/microsoft
   ```

2. **User authorizes** in Microsoft login page

3. **Handle callback**:
   ```
   GET /v1/auth/microsoft/callback?code=<code>&state=<state>
   ```

4. **Receive JWT token** for subsequent requests

## 📡 API Endpoints

### Authentication
- `POST /v1/auth/register` - Register new agent + workspace
- `POST /v1/auth/login` - Login with email/password
- `GET /v1/auth/microsoft` - Get OAuth URL
- `GET /v1/auth/microsoft/callback` - OAuth callback
- `GET /v1/auth/me` - Get current agent
- `POST /v1/auth/logout` - Logout

### Workspaces
- `GET /v1/workspaces` - List workspaces
- `POST /v1/workspaces` - Create workspace
- `GET /v1/workspaces/:id` - Get workspace
- `PATCH /v1/workspaces/:id` - Update workspace
- `DELETE /v1/workspaces/:id` - Delete workspace

### Tickets
- `GET /v1/tickets` - List tickets
- `POST /v1/tickets` - Create ticket
- `GET /v1/tickets/:id` - Get ticket
- `PATCH /v1/tickets/:id` - Update ticket
- `POST /v1/tickets/:id/reply` - Reply to ticket
- `POST /v1/tickets/:id/assign` - Assign ticket

### (Additional routes to be implemented...)

## 🔄 Real-Time WebSocket

Connect to WebSocket for real-time updates:

```javascript
const ws = new WebSocket(
  `wss://api.enque.cc/realtime?agentId=<id>&workspaceId=<id>`
);

ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  console.log('Real-time update:', data);
};

// Subscribe to ticket updates
ws.send(JSON.stringify({
  type: 'subscribe',
  payload: { channel: 'tickets' }
}));
```

## ⏰ Scheduled Jobs

Email sync runs automatically via Cron Triggers:

- **Production**: Every 3 minutes
- **Staging**: Every 5 minutes

Configure in `wrangler.toml`:

```toml
[triggers.crons]
crons = ["*/3 * * * *"]
```

## 🗄️ Database Schema

### Core Entities

- **Workspaces** - Multi-tenant organizations
- **Agents** - Internal staff
- **Users** - External customers
- **Teams** - Agent groups
- **Companies** - Customer organizations

### Ticketing

- **Tickets** - Support requests
- **TicketBodies** - Large email content
- **Comments** - Responses (public/internal)
- **ScheduledComments** - Scheduled responses
- **TicketAttachments** - Files
- **Categories** - Ticket categories

### Microsoft Integration

- **MicrosoftIntegrations** - OAuth apps
- **MailboxConnections** - Connected mailboxes
- **MicrosoftTokens** - Access tokens
- **EmailTicketMappings** - Email-to-ticket mapping
- **EmailSyncConfigs** - Sync settings

### Automation

- **Workflows** - Custom workflows
- **Automations** - Automation rules
- **AutomationConditions** - Rule conditions
- **AutomationActions** - Rule actions
- **CannedReplies** - Response templates

## 🚦 Rate Limiting

Built-in rate limiting using Cloudflare KV:

- **Auth endpoints**: 10 requests / 15 minutes
- **API endpoints**: 100 requests / minute
- **Read operations**: 200 requests / minute
- **Write operations**: 50 requests / minute

Headers included:
- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`
- `Retry-After` (when exceeded)

## 📊 Monitoring & Logging

- Request logging with unique request IDs
- Error tracking
- Performance metrics via Cloudflare Analytics
- Custom logging levels: `debug`, `info`, `warn`, `error`

## 🔒 Security

- JWT-based authentication
- Encrypted token storage (AES-256-GCM)
- Password hashing (bcrypt)
- CORS protection
- Rate limiting
- CSRF protection (OAuth state)
- Input validation (Zod schemas)

## 🌍 Environments

### Staging
- **URL**: `https://stg.enque.cc`
- **Database**: `enque-db-staging`
- **Storage**: `enque-storage-staging`
- **Logging**: `debug` level

### Production
- **URL**: `https://api.enque.cc`
- **Database**: `enque-db`
- **Storage**: `enque-storage`
- **Logging**: `info` level

## 📝 Development Guidelines

### Adding New Routes

1. Create route file in `src/routes/`
2. Import in `src/index.ts`
3. Add to v1 router
4. Add Zod schemas to `shared/types/index.ts`

### Database Migrations

1. Update `src/db/schema.ts`
2. Run `npm run db:generate`
3. Review generated SQL in `migrations/`
4. Apply with `npm run db:migrate`

### Testing

```bash
npm test
```

## 🐛 Troubleshooting

### Database connection issues
```bash
# Check D1 status
wrangler d1 list

# Execute test query
wrangler d1 execute enque-db --command "SELECT 1"
```

### Secret issues
```bash
# List secrets
wrangler secret list

# Re-set secret
wrangler secret put SECRET_NAME
```

### Deployment issues
```bash
# Check deployment status
wrangler deployments list

# View logs
wrangler tail
```

## 📚 Resources

- [Cloudflare Workers Docs](https://developers.cloudflare.com/workers/)
- [Hono Documentation](https://hono.dev/)
- [Drizzle ORM](https://orm.drizzle.team/)
- [D1 Database](https://developers.cloudflare.com/d1/)
- [R2 Storage](https://developers.cloudflare.com/r2/)
- [Durable Objects](https://developers.cloudflare.com/durable-objects/)

## 📄 License

Proprietary - Enque Platform

## 🤝 Contributing

Contact the development team for contribution guidelines.

---

**Built with ❤️ for the edge**
