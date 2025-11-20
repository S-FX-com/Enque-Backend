# Enque Frontend

Modern React frontend for the Enque customer service platform, built with TypeScript, Vite, and Tailwind CSS.

## 🚀 Technology Stack

- **React 18** - UI library
- **TypeScript** - Type safety
- **Vite** - Fast build tool
- **Tailwind CSS** - Utility-first CSS
- **React Router** - Client-side routing
- **TanStack Query** - Data fetching
- **Zustand** - State management
- **Axios** - HTTP client
- **Lucide React** - Icons
- **Cloudflare Pages** - Deployment

## 📁 Project Structure

```
frontend/
├── src/
│   ├── components/         # Reusable UI components
│   ├── pages/             # Page components
│   │   ├── LoginPage.tsx
│   │   ├── RegisterPage.tsx
│   │   └── DashboardPage.tsx
│   ├── services/          # API clients
│   │   ├── api.ts         # Base API client
│   │   └── auth.ts        # Auth service
│   ├── stores/            # Zustand stores
│   │   └── authStore.ts
│   ├── utils/             # Utility functions
│   ├── types/             # TypeScript types
│   ├── config.ts          # App configuration
│   ├── App.tsx            # Main app component
│   ├── main.tsx           # Entry point
│   └── index.css          # Global styles
├── public/                # Static assets
├── index.html             # HTML template
├── vite.config.ts         # Vite configuration
├── tailwind.config.js     # Tailwind configuration
├── wrangler.toml          # Cloudflare Pages config
└── package.json
```

## 🛠️ Development

### Prerequisites

- Node.js 18+
- npm or pnpm

### Installation

```bash
cd frontend
npm install
```

### Environment Setup

```bash
cp .env.example .env
```

Edit `.env`:
```env
VITE_API_URL=http://localhost:8787  # For local development
VITE_WS_URL=ws://localhost:8787
```

### Run Development Server

```bash
npm run dev
```

The app will be available at `http://localhost:3000`

### Build for Production

```bash
npm run build
```

Output will be in `dist/` directory.

### Preview Production Build

```bash
npm run preview
```

## 🌐 Deployment to Cloudflare Pages

### Option 1: Wrangler CLI

```bash
# Build and deploy to staging
npm run deploy:staging

# Build and deploy to production
npm run deploy
```

### Option 2: Cloudflare Dashboard

1. Go to Cloudflare Dashboard → Pages
2. Create a new project
3. Connect your GitHub repository
4. Configure build settings:
   - **Build command**: `npm run build`
   - **Build output directory**: `dist`
   - **Root directory**: `frontend`
5. Add environment variables:
   - `VITE_API_URL`: Your API URL
   - `VITE_WS_URL`: Your WebSocket URL
6. Deploy!

### Option 3: GitHub Actions (Recommended)

Create `.github/workflows/deploy-frontend.yml`:

```yaml
name: Deploy Frontend

on:
  push:
    branches: [main]
    paths:
      - 'frontend/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-node@v3
        with:
          node-version: '18'
      - run: cd frontend && npm ci
      - run: cd frontend && npm run build
      - uses: cloudflare/pages-action@v1
        with:
          apiToken: ${{ secrets.CLOUDFLARE_API_TOKEN }}
          accountId: ${{ secrets.CLOUDFLARE_ACCOUNT_ID }}
          projectName: enque-frontend
          directory: frontend/dist
```

## 🔐 Authentication

The frontend supports three authentication methods:

1. **Email/Password** - Standard login
2. **Microsoft OAuth** - Single Sign-On
3. **JWT Tokens** - Stored in localStorage

### Auth Flow

```
1. User logs in → API returns JWT token
2. Token stored in localStorage
3. API client adds token to all requests
4. Token validated on each request
5. On 401, user redirected to login
```

## 📱 Pages

### Public Pages

- `/login` - User login
- `/register` - New user registration

### Protected Pages

- `/dashboard` - Main dashboard (requires auth)

### Route Guards

- **PublicRoute** - Redirects to dashboard if authenticated
- **ProtectedRoute** - Redirects to login if not authenticated

## 🎨 Styling

Using Tailwind CSS utility classes:

```tsx
<button className="bg-primary-600 hover:bg-primary-700 text-white px-4 py-2 rounded-lg">
  Click Me
</button>
```

Custom utilities in `src/utils/cn.ts` for merging classes.

## 🔌 API Integration

### API Client

Base client in `src/services/api.ts`:

```typescript
import { api } from './services/api';

// GET request
const data = await api.get('/v1/tickets');

// POST request
const result = await api.post('/v1/tickets', { title: 'New Ticket' });
```

### Authentication Service

```typescript
import { authService } from './services/auth';

// Login
await authService.login({ email, password });

// Register
await authService.register({ email, displayName, password });

// Get current user
const agent = await authService.getCurrentAgent();

// Logout
await authService.logout();
```

## 🗄️ State Management

Using Zustand for global state:

```typescript
import { useAuthStore } from './stores/authStore';

function MyComponent() {
  const { agent, login, logout } = useAuthStore();

  return <div>{agent?.displayName}</div>;
}
```

## 🧪 Testing

```bash
# Run tests
npm test

# Type checking
npm run type-check
```

## 📦 Building

```bash
# Development build
npm run build

# Production build (with env vars)
VITE_API_URL=https://api.enque.cc npm run build
```

## 🚀 Performance

- **Code Splitting** - Automatic route-based splitting
- **Lazy Loading** - Components loaded on demand
- **Tree Shaking** - Unused code eliminated
- **Minification** - Production builds minified
- **Caching** - TanStack Query caches API responses

## 🔧 Configuration

### Vite (vite.config.ts)

- Path aliases (`@/` → `src/`)
- Shared types (`@shared/` → `../shared`)
- API proxy (development only)
- Build output to `dist/`

### Tailwind (tailwind.config.js)

- Custom color palette
- Extended theme
- Responsive breakpoints

## 📚 Additional Resources

- [React Documentation](https://react.dev/)
- [Vite Documentation](https://vitejs.dev/)
- [Tailwind CSS Documentation](https://tailwindcss.com/)
- [Cloudflare Pages Documentation](https://developers.cloudflare.com/pages/)

## 🐛 Troubleshooting

### CORS Issues

If you see CORS errors in development:

1. Check API is running: `http://localhost:8787`
2. Verify Vite proxy in `vite.config.ts`
3. Ensure API has CORS configured for your origin

### Build Errors

```bash
# Clear cache and rebuild
rm -rf node_modules dist
npm install
npm run build
```

### Authentication Not Working

1. Check API URL in `.env`
2. Verify JWT token in localStorage (DevTools → Application → Local Storage)
3. Check API logs for errors

## 📄 License

Proprietary - Enque Platform

---

**Built with ❤️ for customer service excellence**
