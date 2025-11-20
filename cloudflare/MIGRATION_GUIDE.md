# Migration Guide: Python (FastAPI) → TypeScript (Cloudflare Workers)

This guide explains the migration from the Python FastAPI backend to the new Cloudflare Workers implementation.

## 🎯 Overview

| Aspect | Python (Old) | TypeScript (New) |
|--------|-------------|------------------|
| **Runtime** | Python 3.9+ | Cloudflare Workers (V8) |
| **Framework** | FastAPI | Hono |
| **Database** | MySQL (Railway) | Cloudflare D1 (SQLite) |
| **ORM** | SQLAlchemy | Drizzle ORM |
| **Storage** | AWS S3 | Cloudflare R2 |
| **Cache** | In-memory (cachetools) | Cloudflare KV |
| **WebSockets** | Socket.IO | Durable Objects |
| **Deployment** | Railway/Heroku | Wrangler CLI |
| **Cost Model** | $50-500/month (24/7) | $5-50/month (pay-per-use) |

## 📋 Migration Checklist

### Phase 1: Setup (Week 1)

- [ ] Create Cloudflare account
- [ ] Install Wrangler CLI
- [ ] Set up D1 databases (staging + production)
- [ ] Set up R2 buckets (staging + production)
- [ ] Set up KV namespaces
- [ ] Configure secrets
- [ ] Update Microsoft 365 app redirect URIs

### Phase 2: Data Migration (Week 1-2)

- [ ] Export data from MySQL
- [ ] Transform data for SQLite
- [ ] Import into D1 staging
- [ ] Verify data integrity
- [ ] Migrate file attachments from S3 to R2

### Phase 3: Testing (Week 2-3)

- [ ] Deploy to staging environment
- [ ] Test authentication flows
- [ ] Test Microsoft OAuth
- [ ] Test email sync
- [ ] Test file uploads/downloads
- [ ] Test WebSocket connections
- [ ] Load testing
- [ ] Security audit

### Phase 4: Production Deployment (Week 3-4)

- [ ] Set up custom domains
- [ ] Configure DNS (CNAME for stg.enque.cc)
- [ ] Deploy to production
- [ ] Migrate production data
- [ ] Monitor for issues
- [ ] Gradual traffic migration (if possible)

### Phase 5: Cleanup (Week 4+)

- [ ] Decommission Railway services
- [ ] Remove Python codebase
- [ ] Update documentation
- [ ] Train team on new stack

## 🔄 Data Migration

### Export from MySQL

```bash
# Connect to Railway MySQL
mysql -h <railway_host> -u <user> -p <database> > backup.sql
```

### Transform for SQLite

Key differences to handle:

1. **Data Types**:
   - MySQL `LONGTEXT` → SQLite `TEXT`
   - MySQL `DATETIME` → SQLite `INTEGER` (Unix timestamp)
   - MySQL `JSON` → SQLite `TEXT` (JSON string)
   - MySQL `BOOLEAN` → SQLite `INTEGER` (0/1)

2. **Auto-increment**:
   - MySQL `AUTO_INCREMENT` → SQLite uses custom ID generation

3. **Foreign Keys**:
   - SQLite requires `PRAGMA foreign_keys = ON`

### Import to D1

```bash
# Import via Wrangler
wrangler d1 execute enque-db-staging --file=transformed_data.sql

# Or use D1 API
wrangler d1 execute enque-db-staging --command="INSERT INTO ..."
```

### Migrate S3 to R2

```bash
# Install rclone
brew install rclone

# Configure S3
rclone config

# Configure R2
rclone config

# Copy files
rclone copy s3:enque-attachments/ r2:enque-storage/
```

## 🔀 Code Migration Patterns

### Authentication

**Python (FastAPI)**:
```python
from fastapi import Depends
from app.core.security import get_current_agent

@app.get("/tickets")
def get_tickets(agent = Depends(get_current_agent)):
    return db.query(Ticket).filter_by(workspace_id=agent.workspace_id).all()
```

**TypeScript (Hono)**:
```typescript
import { authMiddleware } from './middleware/auth';

app.get('/tickets', authMiddleware, async (c) => {
  const agent = c.get('agent');
  const db = createDb(c.env.DB);

  return c.json(await db.select().from(tickets)
    .where(eq(tickets.workspaceId, agent.workspaceId)));
});
```

### Database Queries

**Python (SQLAlchemy)**:
```python
tickets = db.query(Ticket)\
    .filter(Ticket.status == 'Open')\
    .filter(Ticket.workspace_id == workspace_id)\
    .order_by(Ticket.created_at.desc())\
    .limit(50)\
    .all()
```

**TypeScript (Drizzle)**:
```typescript
const ticketsList = await db.select()
  .from(tickets)
  .where(
    and(
      eq(tickets.status, 'Open'),
      eq(tickets.workspaceId, workspaceId)
    )
  )
  .orderBy(desc(tickets.createdAt))
  .limit(50);
```

### File Upload

**Python (S3)**:
```python
import boto3

s3_client = boto3.client('s3')
s3_client.upload_fileobj(file, 'bucket-name', key)
```

**TypeScript (R2)**:
```typescript
import { StorageService } from './services/storage';

const storage = new StorageService(env);
const result = await storage.uploadFile(file, filename);
```

### Background Jobs

**Python (Scheduler)**:
```python
import schedule

def sync_emails():
    # Sync logic
    pass

schedule.every(3).minutes.do(sync_emails)
```

**TypeScript (Cron Triggers)**:
```typescript
// In wrangler.toml
[triggers.crons]
crons = ["*/3 * * * *"]

// In index.ts
export async function scheduled(event, env, ctx) {
  await syncEmails(env);
}
```

### Real-time Updates

**Python (Socket.IO)**:
```python
from app.core.socketio import sio

@sio.on('join_workspace')
def handle_join(sid, data):
    sio.enter_room(sid, data['workspace_id'])
    sio.emit('ticket_updated', data, room=data['workspace_id'])
```

**TypeScript (Durable Objects)**:
```typescript
// Connect WebSocket
const ws = new WebSocket('wss://api.enque.cc/realtime?workspaceId=...');

// Broadcast to workspace
await durableObject.notifyClients(workspaceId, {
  type: 'ticket_updated',
  payload: ticketData
});
```

## 🔧 Environment Variables

Update Microsoft 365 app registration:

**Old URLs**:
- `https://enque-backend-production.up.railway.app/v1/microsoft/auth/callback`

**New URLs**:
- Staging: `https://stg.enque.cc/v1/auth/microsoft/callback`
- Production: `https://api.enque.cc/v1/auth/microsoft/callback`

## 📊 Performance Comparison

| Metric | Python (Railway) | TypeScript (Cloudflare) |
|--------|-----------------|------------------------|
| **Cold Start** | 2-5 seconds | < 1ms |
| **Response Time (Global avg)** | 200-500ms | 50-100ms |
| **Concurrent Requests** | ~100 (limited by RAM) | Unlimited |
| **Monthly Cost (10K users)** | $200-500 | $20-50 |
| **Geographic Coverage** | 1 region | 300+ locations |

## 🚨 Breaking Changes

### API Changes

1. **Response Format**: All responses now follow standard format:
   ```json
   {
     "success": true,
     "data": { ... },
     "meta": { ... }
   }
   ```

2. **Error Codes**: Standardized error codes (see README)

3. **Date Format**: Unix timestamps instead of ISO strings

4. **ID Format**: Changed from numeric to string UUIDs

### Frontend Updates Required

1. Update API base URL to `https://api.enque.cc` or `https://stg.enque.cc`
2. Update WebSocket connection URL
3. Handle new response format
4. Update date parsing logic
5. Update ID types from `number` to `string`

## 🔍 Testing Migration

### 1. Unit Tests

```bash
npm test
```

### 2. Integration Tests

Test each endpoint:
```bash
# Get auth token
TOKEN=$(curl -X POST https://stg.enque.cc/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"password"}' \
  | jq -r '.data.token')

# Test API
curl -H "Authorization: Bearer $TOKEN" \
  https://stg.enque.cc/v1/tickets
```

### 3. Load Testing

```bash
# Using artillery
npm install -g artillery
artillery quick --count 100 --num 10 https://stg.enque.cc/v1/tickets
```

### 4. Email Sync Testing

```bash
# Trigger manual sync
curl -X POST https://stg.enque.cc/v1/admin/sync-emails \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

## 📝 Rollback Plan

If issues arise:

1. **DNS Rollback**: Point domain back to Railway
2. **Data Sync**: Keep Railway DB running for 2 weeks during migration
3. **Gradual Migration**: Use load balancer to split traffic

## 🎓 Team Training

### New Skills Required

- TypeScript fundamentals
- Cloudflare Workers concepts
- Drizzle ORM patterns
- Wrangler CLI usage
- D1 database management

### Resources

- [ ] Share Cloudflare Workers documentation
- [ ] Hono framework tutorial
- [ ] Drizzle ORM examples
- [ ] Internal training sessions

## ✅ Post-Migration Validation

- [ ] All features working in staging
- [ ] Performance metrics acceptable
- [ ] Email sync functioning
- [ ] Real-time updates working
- [ ] File uploads/downloads working
- [ ] Microsoft OAuth working
- [ ] Rate limiting functioning
- [ ] Error handling proper
- [ ] Logs accessible
- [ ] Monitoring in place

## 🎉 Success Criteria

- ✅ 99.9% uptime
- ✅ < 100ms global response time
- ✅ Zero data loss
- ✅ All features migrated
- ✅ Cost reduction of 50%+
- ✅ Team trained and comfortable

## 📞 Support

For migration issues, contact:
- Technical Lead: [Contact Info]
- Cloudflare Support: https://dash.cloudflare.com/

---

**Migration Timeline: 3-4 weeks**
**Estimated Cost Savings: 60-80%**
**Performance Improvement: 3-5x faster**
