/**
 * API client for Heliox Admin
 */

const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

// Get admin key from localStorage (client-side only)
function getAdminKey(): string {
  if (typeof window === 'undefined') return ''
  return localStorage.getItem('adminKey') || ''
}

async function fetchApi<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const adminKey = getAdminKey()
  
  const response = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      'X-Admin-Key': adminKey,
      ...options.headers,
    },
  })

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Unknown error' }))
    throw new Error(error.detail || `HTTP ${response.status}`)
  }

  return response.json()
}

// Types
export interface Tenant {
  id: string
  name: string
  description: string
  is_active: boolean
  created_at: string
  updated_at: string
  api_key_count?: number
  route_count?: number
}

export interface ApiKey {
  id: string
  tenant_id: string
  name: string
  key_prefix: string
  key?: string // Only returned on creation
  is_active: boolean
  rate_limit_rps: number
  rate_limit_burst: number
  daily_quota: number
  monthly_quota: number
  daily_usage?: number
  monthly_usage?: number
  created_at: string
  last_used_at?: string
}

export interface Route {
  id: string
  tenant_id?: string
  policy_id: string
  name: string
  description: string
  path_pattern: string
  methods: string[]
  upstream_base_url: string
  is_active: boolean
  timeout_ms: number
  priority: number
  created_at: string
  updated_at: string
}

export interface CachePolicy {
  id: string
  name: string
  description: string
  ttl_seconds: number
  stale_seconds: number
  vary_headers_json: string[]
  cacheable_methods: string[]
  cacheable_statuses_json: number[]
  created_at: string
}

export interface AnalyticsSummary {
  total_requests: number
  cache_hits: number
  cache_misses: number
  cache_stale: number
  cache_hit_rate: number
  error_count: number
  error_rate: number
  avg_latency_ms: number
  requests_per_minute: number
  unique_keys: number
  unique_routes: number
}

export interface HealthStatus {
  status: string
  version: string
  timestamp: string
  components: Record<string, { status: string }>
}

export interface BlockedKey {
  api_key_id: string
  reason: string
  score: number
  blocked_at: string
  blocked_until: string
}

export interface RequestLog {
  id: string
  api_key_id: string
  route_id: string
  method: string
  path: string
  status_code: number
  latency_ms: number
  cache_status: string
  created_at: string
}

// Admin API
export const adminApi = {
  // Health
  getHealth: async (): Promise<HealthStatus> => {
    const response = await fetch(`${API_URL}/health`)
    return response.json()
  },

  // Analytics
  getSummary: async (hours: number = 24): Promise<AnalyticsSummary> => {
    return fetchApi(`/admin/analytics/summary?hours=${hours}`)
  },

  getTopKeys: async (limit: number = 10): Promise<any[]> => {
    return fetchApi(`/admin/analytics/top-keys?limit=${limit}`)
  },

  getTopRoutes: async (limit: number = 10): Promise<any[]> => {
    return fetchApi(`/admin/analytics/top-routes?limit=${limit}`)
  },

  getCacheHitRate: async (hours: number = 24): Promise<any> => {
    return fetchApi(`/admin/analytics/cache-hit-rate?hours=${hours}`)
  },

  getLogs: async (limit: number = 100, offset: number = 0): Promise<RequestLog[]> => {
    return fetchApi(`/admin/analytics/logs?limit=${limit}&offset=${offset}`)
  },

  // Tenants
  getTenants: async (): Promise<Tenant[]> => {
    return fetchApi('/admin/tenants')
  },

  getTenant: async (id: string): Promise<Tenant> => {
    return fetchApi(`/admin/tenants/${id}`)
  },

  createTenant: async (data: Partial<Tenant>): Promise<Tenant> => {
    return fetchApi('/admin/tenants', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  updateTenant: async (id: string, data: Partial<Tenant>): Promise<Tenant> => {
    return fetchApi(`/admin/tenants/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    })
  },

  // API Keys
  getKeys: async (): Promise<ApiKey[]> => {
    return fetchApi('/admin/keys')
  },

  getKey: async (id: string): Promise<ApiKey> => {
    return fetchApi(`/admin/keys/${id}`)
  },

  createKey: async (data: Partial<ApiKey>): Promise<ApiKey> => {
    return fetchApi('/admin/keys', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  updateKey: async (id: string, data: Partial<ApiKey>): Promise<ApiKey> => {
    return fetchApi(`/admin/keys/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    })
  },

  deleteKey: async (id: string): Promise<void> => {
    return fetchApi(`/admin/keys/${id}`, {
      method: 'DELETE',
    })
  },

  rotateKey: async (id: string): Promise<ApiKey> => {
    return fetchApi(`/admin/keys/${id}/rotate`, {
      method: 'POST',
    })
  },

  // Routes
  getRoutes: async (): Promise<Route[]> => {
    return fetchApi('/admin/routes')
  },

  getRoute: async (id: string): Promise<Route> => {
    return fetchApi(`/admin/routes/${id}`)
  },

  createRoute: async (data: Partial<Route>): Promise<Route> => {
    return fetchApi('/admin/routes', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  updateRoute: async (id: string, data: Partial<Route>): Promise<Route> => {
    return fetchApi(`/admin/routes/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    })
  },

  deleteRoute: async (id: string): Promise<void> => {
    return fetchApi(`/admin/routes/${id}`, {
      method: 'DELETE',
    })
  },

  // Cache Policies
  getPolicies: async (): Promise<CachePolicy[]> => {
    return fetchApi('/admin/policies')
  },

  getPolicy: async (id: string): Promise<CachePolicy> => {
    return fetchApi(`/admin/policies/${id}`)
  },

  createPolicy: async (data: Partial<CachePolicy>): Promise<CachePolicy> => {
    return fetchApi('/admin/policies', {
      method: 'POST',
      body: JSON.stringify(data),
    })
  },

  updatePolicy: async (id: string, data: Partial<CachePolicy>): Promise<CachePolicy> => {
    return fetchApi(`/admin/policies/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    })
  },

  // Cache Management
  purgeCache: async (pattern?: string): Promise<{ deleted: number }> => {
    return fetchApi('/admin/cache/purge', {
      method: 'POST',
      body: JSON.stringify({ pattern }),
    })
  },

  // Abuse Management
  getBlockedKeys: async (): Promise<BlockedKey[]> => {
    return fetchApi('/admin/abuse/blocked')
  },

  unblockKey: async (keyId: string): Promise<void> => {
    return fetchApi(`/admin/abuse/unblock/${keyId}`, {
      method: 'POST',
    })
  },

  // Metrics
  getMetrics: async (): Promise<any> => {
    const response = await fetch(`${API_URL}/metrics`)
    return response.json()
  },
}

export default adminApi
