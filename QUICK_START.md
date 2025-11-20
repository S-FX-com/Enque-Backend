# 🚀 Enque - Quick Start Guide

Complete setup guide for deploying Enque customer service platform on Cloudflare.

## 📦 What You Have

✅ **Backend** - Cloudflare Workers API (TypeScript + Hono)
✅ **Frontend** - React app (TypeScript + Vite + Tailwind)
✅ **Database** - D1 (serverless SQLite)
✅ **Storage** - R2 (file attachments)
✅ **Cache** - KV (rate limiting, sessions)
✅ **Real-time** - Durable Objects (WebSockets)

---

## 🎯 Quick Deploy (5 Minutes)

### Step 1: Install Dependencies

```bash
# Frontend
cd frontend
npm install
cd ..

# Note: Backend dependencies will be installed by Wrangler during deployment
```

### Step 2: Deploy Backend (Staging)

```bash
cd cloudflare

# Login to Cloudflare
wrangler login

# Create D1 database
wrangler d1 create enque-db-staging
# Copy the database_id and update wrangler.staging.toml

# Create R2 bucket
wrangler r2 bucket create enque-storage-staging

# Create KV namespace
wrangler kv:namespace create "CACHE"
# Copy the id and update wrangler.staging.toml

# Set secrets
wrangler secret put JWT_SECRET
# Generate one: openssl rand -base64 32

wrangler secret put MICROSOFT_CLIENT_ID
wrangler secret put MICROSOFT_CLIENT_SECRET
wrangler secret put MICROSOFT_TENANT_ID
wrangler secret put DATABASE_ENCRYPTION_KEY
# Generate one: openssl rand -base64 32

# Generate and apply database migration
npm install
npm run db:generate
wrangler d1 execute enque-db-staging --file=./migrations/0001_initial.sql

# Deploy!
npm run deploy:staging
```

### Step 3: Deploy Frontend (Staging)

```bash
cd ../frontend

# Create .env
cp .env.example .env
# Edit .env and set VITE_API_URL=https://stg.enque.cc

# Build and deploy
npm run deploy:staging
```

### Step 4: Configure DNS

In Cloudflare Dashboard:

1. Go to DNS settings
2. Add CNAME records:
   - `stg` → `<your-worker-url>.workers.dev` (backend)
   - `app-stg` or configure Pages custom domain (frontend)

### Step 5: Test It!

```bash
# Test backend
curl https://stg.enque.cc/health

# Test frontend
open https://<your-pages-url>.pages.dev
```

---

## 📖 Detailed Setup

### Backend Deployment

```bash
cd cloudflare

# 1. Create all Cloudflare resources
wrangler d1 create enque-db-staging
wrangler r2 bucket create enque-storage-staging
wrangler kv:namespace create "CACHE"

# 2. Update wrangler.staging.toml with IDs from above

# 3. Set all required secrets
wrangler secret put JWT_SECRET
wrangler secret put MICROSOFT_CLIENT_ID
wrangler secret put MICROSOFT_CLIENT_SECRET
wrangler secret put MICROSOFT_TENANT_ID
wrangler secret put DATABASE_ENCRYPTION_KEY

# 4. Install dependencies
npm install

# 5. Generate database migration
npm run db:generate

# 6. Apply migration to D1
wrangler d1 execute enque-db-staging --file=./migrations/0001_initial.sql

# 7. Deploy
npm run deploy:staging

# 8. Check logs
wrangler tail
```

### Frontend Deployment

```bash
cd frontend

# 1. Install dependencies
npm install

# 2. Set up environment
cp .env.example .env
# Edit .env:
# VITE_API_URL=https://stg.enque.cc (your backend URL)

# 3. Build
npm run build

# 4. Deploy to Cloudflare Pages
npm run deploy:staging

# Or use Cloudflare Dashboard:
# - Go to Pages
# - Create new project
# - Connect GitHub repo
# - Build command: npm run build
# - Build output: dist
# - Root directory: frontend
```

---

## 🌍 Custom Domains

### Backend (stg.enque.cc)

1. Go to Cloudflare Dashboard → Workers & Pages
2. Select your worker (`enque-api-staging`)
3. Go to "Triggers" → "Custom Domains"
4. Add `stg.enque.cc`
5. Cloudflare will automatically configure DNS

### Frontend (app-stg.enque.cc or app.stg.enque.cc)

1. Go to Cloudflare Dashboard → Pages
2. Select your Pages project
3. Go to "Custom domains"
4. Add your domain
5. DNS configured automatically

---

## 🔐 Microsoft 365 Setup

### Create Azure AD App

1. Go to [Azure Portal](https://portal.azure.com)
2. Azure Active Directory → App registrations → New registration
3. Name: "Enque Staging"
4. Redirect URI: `https://stg.enque.cc/v1/auth/microsoft/callback`
5. Save **Application (client) ID** → Use for `MICROSOFT_CLIENT_ID`
6. Save **Directory (tenant) ID** → Use for `MICROSOFT_TENANT_ID`

### Create Client Secret

1. Certificates & secrets → New client secret
2. Description: "Enque Staging Secret"
3. Expires: 24 months
4. Copy the **Value** → Use for `MICROSOFT_CLIENT_SECRET`

### Configure API Permissions

1. API permissions → Add a permission → Microsoft Graph
2. Delegated permissions:
   - `offline_access`
   - `Mail.Read`
   - `Mail.ReadWrite`
   - `Mail.Send`
   - `User.Read`
3. Grant admin consent

---

## 🧪 Testing

### Backend API

```bash
# Health check
curl https://stg.enque.cc/health

# Get Microsoft OAuth URL
curl https://stg.enque.cc/v1/auth/microsoft

# Register a user
curl -X POST https://stg.enque.cc/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "displayName": "Admin User",
    "password": "SecurePass123",
    "workspaceName": "My Workspace",
    "workspaceSubdomain": "myworkspace"
  }'

# Login
curl -X POST https://stg.enque.cc/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "email": "admin@example.com",
    "password": "SecurePass123"
  }'

# Get current user (with token)
curl https://stg.enque.cc/v1/auth/me \
  -H "Authorization: Bearer <your-jwt-token>"
```

### Frontend

1. Open `https://<your-pages-url>.pages.dev`
2. Click "Sign up" → Create account
3. Login with credentials
4. Should see dashboard

---

## 📊 Monitoring

### Backend Logs

```bash
# Stream logs in real-time
wrangler tail

# Filter by status
wrangler tail --status error

# Filter by method
wrangler tail --method POST
```

### Frontend Logs

- Cloudflare Dashboard → Pages → Your project → "Logs"
- Or check browser console (F12)

### Database

```bash
# Check D1 database
wrangler d1 execute enque-db-staging --command "SELECT COUNT(*) FROM agents"

# List tables
wrangler d1 execute enque-db-staging --command "SELECT name FROM sqlite_master WHERE type='table'"
```

---

## 🔄 Updates

### Update Backend

```bash
cd cloudflare

# Make changes to code
# ...

# Deploy
npm run deploy:staging
```

### Update Frontend

```bash
cd frontend

# Make changes to code
# ...

# Build and deploy
npm run deploy:staging
```

### Update Database Schema

```bash
cd cloudflare

# 1. Update src/db/schema.ts
# 2. Generate migration
npm run db:generate

# 3. Review migration in migrations/
# 4. Apply migration
wrangler d1 execute enque-db-staging --file=./migrations/<new-migration>.sql
```

---

## 🆘 Troubleshooting

### Backend Won't Deploy

```bash
# Check wrangler.toml configuration
cat wrangler.staging.toml

# Verify secrets are set
wrangler secret list

# Check for TypeScript errors
cd cloudflare && npm run type-check
```

### Frontend Won't Build

```bash
cd frontend

# Clear and reinstall
rm -rf node_modules package-lock.json
npm install

# Check for errors
npm run type-check
npm run build
```

### Database Errors

```bash
# Check database exists
wrangler d1 list

# Check tables exist
wrangler d1 execute enque-db-staging --command "SELECT name FROM sqlite_master WHERE type='table'"

# Re-run migration
wrangler d1 execute enque-db-staging --file=./migrations/0001_initial.sql
```

### CORS Errors

- Check backend CORS middleware in `cloudflare/src/middleware/cors.ts`
- Verify frontend URL is allowed
- Check browser console for specific error

---

## 📚 What's Next?

1. ✅ **You're deployed!** Backend + Frontend on Cloudflare
2. 🎨 **Customize** - Update branding, colors, logos
3. 🔨 **Build Features** - Add remaining API routes (tickets, users, teams, etc.)
4. 📧 **Email Integration** - Connect Microsoft 365 mailboxes
5. 🧪 **Test** - Load testing, security audit
6. 🚀 **Production** - Deploy to production environment

---

## 💰 Cost Estimate

**For 10,000 users (typical small business):**

| Service | Usage | Cost |
|---------|-------|------|
| Workers | 10M requests/month | $5 |
| D1 | 50M reads, 5M writes | Included |
| R2 | 100GB storage, 1TB egress | $1.50 |
| KV | 10M reads, 1M writes | Included |
| Pages | Unlimited bandwidth | Free |
| **Total** | | **~$6.50/month** |

Compare to Railway/Heroku: $50-200/month 🎉

---

## 🎓 Resources

- **Backend README**: `cloudflare/README.md`
- **Frontend README**: `frontend/README.md`
- **Migration Guide**: `cloudflare/MIGRATION_GUIDE.md`
- **Deployment Checklist**: `cloudflare/DEPLOY.md`
- **Cloudflare Docs**: https://developers.cloudflare.com/

---

**You're all set! 🎉**

Your Enque platform is now running on Cloudflare's global network with sub-100ms response times worldwide.

Questions? Check the documentation or deploy logs.
