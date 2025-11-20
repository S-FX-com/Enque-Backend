import { useEffect } from 'react';
import { useAuthStore } from '../stores/authStore';
import { useNavigate } from 'react-router-dom';
import { LogOut, Inbox, Users, Settings } from 'lucide-react';

export function DashboardPage() {
  const navigate = useNavigate();
  const { agent, logout, fetchCurrentAgent } = useAuthStore();

  useEffect(() => {
    fetchCurrentAgent();
  }, [fetchCurrentAgent]);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  if (!agent) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary-600"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white shadow-sm border-b border-gray-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Enque</h1>
            <p className="text-sm text-gray-600">Customer Service Platform</p>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right">
              <p className="text-sm font-medium text-gray-900">{agent.displayName}</p>
              <p className="text-xs text-gray-600">{agent.email}</p>
            </div>
            <button
              onClick={handleLogout}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100 rounded-lg transition"
            >
              <LogOut className="w-4 h-4" />
              Logout
            </button>
          </div>
        </div>
      </header>

      {/* Main Content */}
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="mb-8">
          <h2 className="text-3xl font-bold text-gray-900">Welcome back, {agent.displayName}!</h2>
          <p className="text-gray-600 mt-2">Here's what's happening with your support tickets today.</p>
        </div>

        {/* Stats Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Open Tickets</p>
                <p className="text-3xl font-bold text-gray-900 mt-2">0</p>
              </div>
              <div className="p-3 bg-primary-100 rounded-full">
                <Inbox className="w-6 h-6 text-primary-600" />
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Customers</p>
                <p className="text-3xl font-bold text-gray-900 mt-2">0</p>
              </div>
              <div className="p-3 bg-green-100 rounded-full">
                <Users className="w-6 h-6 text-green-600" />
              </div>
            </div>
          </div>

          <div className="bg-white rounded-lg shadow p-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-gray-600">Workspaces</p>
                <p className="text-3xl font-bold text-gray-900 mt-2">{agent.workspaces?.length || 0}</p>
              </div>
              <div className="p-3 bg-purple-100 rounded-full">
                <Settings className="w-6 h-6 text-purple-600" />
              </div>
            </div>
          </div>
        </div>

        {/* Workspaces */}
        {agent.workspaces && agent.workspaces.length > 0 && (
          <div className="bg-white rounded-lg shadow p-6">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Your Workspaces</h3>
            <div className="space-y-3">
              {agent.workspaces.map((workspace) => (
                <div
                  key={workspace.id}
                  className="flex items-center justify-between p-4 border border-gray-200 rounded-lg hover:bg-gray-50 transition"
                >
                  <div>
                    <p className="font-medium text-gray-900">{workspace.name}</p>
                    <p className="text-sm text-gray-600">{workspace.subdomain}.enque.cc</p>
                  </div>
                  <span className="px-3 py-1 text-xs font-medium bg-primary-100 text-primary-700 rounded-full">
                    {workspace.role}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Getting Started */}
        <div className="mt-8 bg-gradient-to-r from-primary-500 to-primary-600 rounded-lg shadow-lg p-8 text-white">
          <h3 className="text-2xl font-bold mb-4">🎉 Welcome to Enque!</h3>
          <p className="text-primary-100 mb-6">
            Your customer service platform is ready. The remaining features are being built and will be available soon.
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="bg-white/10 rounded-lg p-4">
              <h4 className="font-semibold mb-2">✅ Authentication</h4>
              <p className="text-sm text-primary-100">Login, register, and Microsoft OAuth are working</p>
            </div>
            <div className="bg-white/10 rounded-lg p-4">
              <h4 className="font-semibold mb-2">🚧 Coming Soon</h4>
              <p className="text-sm text-primary-100">Tickets, customers, teams, and more features</p>
            </div>
          </div>
        </div>
      </main>
    </div>
  );
}
