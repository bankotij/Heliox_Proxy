'use client'

import { useQuery } from '@tanstack/react-query'
import { adminApi } from '@/lib/api'
import StatsCard from '@/components/StatsCard'
import {
  Activity,
  Zap,
  Database,
  AlertTriangle,
  Clock,
  TrendingUp,
} from 'lucide-react'
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  AreaChart,
  Area,
} from 'recharts'

export default function DashboardPage() {
  const { data: summary, isLoading } = useQuery({
    queryKey: ['analytics-summary'],
    queryFn: () => adminApi.getSummary(24),
    refetchInterval: 30000, // Refresh every 30s
  })

  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: adminApi.getHealth,
    refetchInterval: 10000,
  })

  if (isLoading) {
    return (
      <div className="animate-pulse space-y-6">
        <div className="h-8 bg-gray-200 rounded w-48" />
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-32 bg-gray-200 rounded-xl" />
          ))}
        </div>
      </div>
    )
  }

  const hitRate = summary ? (summary.cache_hit_rate * 100).toFixed(1) : '0'
  const errorRate = summary ? (summary.error_rate * 100).toFixed(2) : '0'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Dashboard</h1>
          <p className="text-gray-500 mt-1">Gateway performance overview (last 24 hours)</p>
        </div>
        <div className="flex items-center space-x-2">
          <span className={`w-2 h-2 rounded-full ${health?.status === 'healthy' ? 'bg-green-500' : 'bg-yellow-500'}`} />
          <span className="text-sm text-gray-600">
            {health?.status === 'healthy' ? 'All systems operational' : 'Degraded'}
          </span>
        </div>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatsCard
          title="Total Requests"
          value={summary?.total_requests.toLocaleString() || '0'}
          subtitle={`${summary?.requests_per_minute.toFixed(1) || 0} req/min`}
          icon={Activity}
          color="blue"
        />
        <StatsCard
          title="Cache Hit Rate"
          value={`${hitRate}%`}
          subtitle={`${summary?.cache_hits || 0} hits / ${summary?.cache_misses || 0} misses`}
          icon={Zap}
          color="green"
        />
        <StatsCard
          title="Avg Latency"
          value={`${summary?.avg_latency_ms.toFixed(0) || 0}ms`}
          subtitle="Response time"
          icon={Clock}
          color="purple"
        />
        <StatsCard
          title="Error Rate"
          value={`${errorRate}%`}
          subtitle={`${summary?.error_count || 0} errors`}
          icon={AlertTriangle}
          color={parseFloat(errorRate) > 5 ? 'red' : 'yellow'}
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Cache Performance */}
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Cache Performance</h3>
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={[
                  { name: 'Hits', value: summary?.cache_hits || 0, fill: '#22c55e' },
                  { name: 'Stale', value: summary?.cache_stale || 0, fill: '#eab308' },
                  { name: 'Misses', value: summary?.cache_misses || 0, fill: '#ef4444' },
                ]}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="name" stroke="#6b7280" fontSize={12} />
                <YAxis stroke="#6b7280" fontSize={12} />
                <Tooltip />
                <Area
                  type="monotone"
                  dataKey="value"
                  stroke="#0ea5e9"
                  fill="#0ea5e9"
                  fillOpacity={0.2}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Quick Stats */}
        <div className="card">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">Quick Stats</h3>
          <div className="space-y-4">
            <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
              <div>
                <p className="text-sm text-gray-500">Active API Keys</p>
                <p className="text-2xl font-semibold text-gray-900">{summary?.unique_keys || 0}</p>
              </div>
              <Database className="w-8 h-8 text-primary-500" />
            </div>
            <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
              <div>
                <p className="text-sm text-gray-500">Active Routes</p>
                <p className="text-2xl font-semibold text-gray-900">{summary?.unique_routes || 0}</p>
              </div>
              <TrendingUp className="w-8 h-8 text-green-500" />
            </div>
            <div className="flex items-center justify-between p-4 bg-gray-50 rounded-lg">
              <div>
                <p className="text-sm text-gray-500">SWR Refreshes</p>
                <p className="text-2xl font-semibold text-gray-900">{summary?.cache_stale || 0}</p>
              </div>
              <Zap className="w-8 h-8 text-yellow-500" />
            </div>
          </div>
        </div>
      </div>

      {/* Gateway Info */}
      <div className="card">
        <h3 className="text-lg font-semibold text-gray-900 mb-4">System Status</h3>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {health?.components && Object.entries(health.components).map(([name, status]: [string, any]) => (
            <div key={name} className="flex items-center space-x-3 p-3 bg-gray-50 rounded-lg">
              <span className={`w-3 h-3 rounded-full ${
                status.status === 'healthy' ? 'bg-green-500' :
                status.status === 'demo_mode' ? 'bg-yellow-500' : 'bg-red-500'
              }`} />
              <div>
                <p className="font-medium text-gray-900 capitalize">{name}</p>
                <p className="text-sm text-gray-500">{status.status}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
