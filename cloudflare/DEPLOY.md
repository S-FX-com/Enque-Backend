# Deployment Checklist

## 🚀 Staging Deployment

### Prerequisites

- [ ] Cloudflare account created
- [ ] Domain `stg.enque.cc` configured in Cloudflare DNS
- [ ] Wrangler CLI installed (`npm install -g wrangler`)
- [ ] Logged in to Wrangler (`wrangler login`)

### Step 1: Create Cloudflare Resources

```bash
cd cloudflare

# 1. Create staging D1 database
wrangler d1 create enque-db-staging
# Copy database_id and update wrangler.staging.toml

# 2. Create staging R2 bucket
wrangler r2 bucket create enque-storage-staging

# 3. Create staging KV namespace
wrangler kv:namespace create "CACHE"
# Copy id and update wrangler.staging.toml
```

### Step 2: Configure Secrets

```bash
# Set all secrets for staging
wrangler secret put JWT_SECRET
# Generate: openssl rand -base64 32

wrangler secret put MICROSOFT_CLIENT_ID
# From Azure AD app registration

wrangler secret put MICROSOFT_CLIENT_SECRET
# From Azure AD app registration

wrangler secret put MICROSOFT_TENANT_ID
# From Azure AD

wrangler secret put DATABASE_ENCRYPTION_KEY
# Generate: openssl rand -base64 32
```

### Step 3: Update Microsoft 365 App

- [ ] Go to Azure Portal → App Registrations
- [ ] Add redirect URI: `https://stg.enque.cc/v1/auth/microsoft/callback`
- [ ] Save changes

### Step 4: Initialize Database

```bash
# Generate initial migration
npm run db:generate

# Review migration file in migrations/

# Apply migration to staging D1
wrangler d1 execute enque-db-staging --file=./migrations/0001_initial.sql
```

### Step 5: Deploy to Staging

```bash
# Install dependencies
npm install

# Type check
npm run type-check

# Deploy
npm run deploy:staging
```

### Step 6: Verify Deployment

```bash
# Test health endpoint
curl https://stg.enque.cc/health

# Test auth endpoint
curl https://stg.enque.cc/v1/auth/microsoft

# Check logs
wrangler tail
```

### Step 7: DNS Configuration

In Cloudflare Dashboard:

1. Go to DNS settings
2. Add CNAME record:
   - Name: `stg`
   - Target: `<your-worker>.workers.dev`
   - Proxy: Enabled (orange cloud)

---

## 🌐 Production Deployment

### Prerequisites

- [ ] Staging fully tested and validated
- [ ] Domain `api.enque.cc` configured
- [ ] Production Microsoft 365 app configured
- [ ] Backup plan ready

### Step 1: Create Production Resources

```bash
# 1. Create production D1 database
wrangler d1 create enque-db
# Copy database_id and update wrangler.toml

# 2. Create production R2 bucket
wrangler r2 bucket create enque-storage

# 3. Create production KV namespace
wrangler kv:namespace create "CACHE" --env production
# Copy id and update wrangler.toml
```

### Step 2: Configure Production Secrets

```bash
# Use DIFFERENT secrets for production!
wrangler secret put JWT_SECRET --env production
wrangler secret put MICROSOFT_CLIENT_ID --env production
wrangler secret put MICROSOFT_CLIENT_SECRET --env production
wrangler secret put MICROSOFT_TENANT_ID --env production
wrangler secret put DATABASE_ENCRYPTION_KEY --env production
```

### Step 3: Update Microsoft 365 App

- [ ] Add production redirect URI: `https://api.enque.cc/v1/auth/microsoft/callback`

### Step 4: Database Migration

```bash
# Apply migrations to production
wrangler d1 execute enque-db --file=./migrations/0001_initial.sql --env production

# Import existing data (if migrating from MySQL)
wrangler d1 execute enque-db --file=./production_data.sql --env production
```

### Step 5: Deploy to Production

```bash
# Final type check
npm run type-check

# Deploy to production
npm run deploy
```

### Step 6: DNS Configuration

1. Add CNAME for `api.enque.cc`
2. Enable Cloudflare proxy (orange cloud)
3. Set SSL/TLS to "Full (strict)"

### Step 7: Post-Deployment Checks

- [ ] Health check passes
- [ ] Authentication working
- [ ] Microsoft OAuth working
- [ ] Database queries working
- [ ] File uploads working
- [ ] WebSockets working
- [ ] Email sync triggered
- [ ] Logs showing in dashboard
- [ ] Rate limiting active
- [ ] No errors in error tracking

---

## 🔍 Monitoring Setup

### Cloudflare Analytics

1. Enable Workers Analytics
2. Set up custom dashboards
3. Configure alerts for:
   - Error rate > 1%
   - Response time > 500ms
   - CPU time > 10ms average

### Logs

```bash
# Stream production logs
wrangler tail --env production

# Stream staging logs
wrangler tail
```

### Health Monitoring

Set up external monitoring:
- Uptime Robot (https://uptimerobot.com)
- Pingdom
- Or custom monitoring

Monitor:
- `https://api.enque.cc/health`
- `https://stg.enque.cc/health`

---

## 🚨 Rollback Procedure

If issues occur in production:

```bash
# 1. Get list of deployments
wrangler deployments list

# 2. Rollback to previous version
wrangler rollback <deployment-id>

# 3. Verify rollback
curl https://api.enque.cc/health
```

---

## 📊 Performance Checklist

After deployment, verify:

- [ ] Cold start < 10ms
- [ ] Average response time < 100ms
- [ ] P99 response time < 500ms
- [ ] Database queries < 50ms
- [ ] R2 upload time < 2s
- [ ] WebSocket connection < 100ms

---

## 🔐 Security Checklist

- [ ] All secrets properly set
- [ ] CORS configured correctly
- [ ] Rate limiting active
- [ ] JWT expiration set
- [ ] Tokens encrypted in database
- [ ] HTTPS enforced
- [ ] No sensitive data in logs

---

## 📝 Documentation

Update after deployment:

- [ ] API documentation
- [ ] Frontend environment variables
- [ ] Team wiki/knowledge base
- [ ] Runbook for incidents

---

## ✅ Success Criteria

Deployment is successful when:

- ✅ All health checks pass
- ✅ No errors in logs (first hour)
- ✅ Response times within SLA
- ✅ All features working
- ✅ Frontend connected successfully
- ✅ Email sync running
- ✅ Real-time updates working

---

## 🎉 Post-Deployment

- [ ] Announce to team
- [ ] Monitor for 24 hours
- [ ] Gather feedback
- [ ] Document any issues
- [ ] Plan next iteration

---

## 📞 Emergency Contacts

- **Cloudflare Support**: https://dash.cloudflare.com/support
- **On-call Engineer**: [Contact]
- **Tech Lead**: [Contact]

---

**Remember**: Always test in staging first! 🧪
