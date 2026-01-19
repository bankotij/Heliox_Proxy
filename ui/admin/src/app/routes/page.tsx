'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi, Route, CachePolicy } from '@/lib/api'
import DataTable from '@/components/DataTable'
import Modal from '@/components/Modal'
import Badge from '@/components/Badge'
import { Plus, Edit2, Trash2 } from 'lucide-react'

export default function RoutesPage() {
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [editingRoute, setEditingRoute] = useState<Route | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    path_pattern: '/*',
    methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
    upstream_base_url: '',
    timeout_ms: 30000,
    policy_id: '',
  })
  
  const queryClient = useQueryClient()
  
  const { data: routes = [], isLoading } = useQuery({
    queryKey: ['routes'],
    queryFn: () => adminApi.getRoutes(),
  })
  
  const { data: policies = [] } = useQuery({
    queryKey: ['policies'],
    queryFn: adminApi.getPolicies,
  })
  
  const createMutation = useMutation({
    mutationFn: adminApi.createRoute,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['routes'] })
      setIsCreateOpen(false)
      resetForm()
    },
  })
  
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Route> }) =>
      adminApi.updateRoute(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['routes'] })
      setEditingRoute(null)
    },
  })
  
  const deleteMutation = useMutation({
    mutationFn: adminApi.deleteRoute,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['routes'] })
    },
  })
  
  const resetForm = () => {
    setFormData({
      name: '',
      path_pattern: '/*',
      methods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE'],
      upstream_base_url: '',
      timeout_ms: 30000,
      policy_id: '',
    })
  }
  
  const getPolicyName = (policyId: string | null) => {
    if (!policyId) return 'None'
    const policy = policies.find(p => p.id === policyId)
    return policy?.name || 'Unknown'
  }
  
  const columns = [
    {
      key: 'name',
      header: 'Name',
      render: (route: Route) => (
        <div>
          <p className="font-medium text-gray-900">{route.name}</p>
          <p className="text-sm text-gray-500 font-mono">{route.path_pattern}</p>
        </div>
      ),
    },
    {
      key: 'upstream_base_url',
      header: 'Upstream',
      render: (route: Route) => (
        <span className="text-sm font-mono truncate max-w-xs block">
          {route.upstream_base_url}
        </span>
      ),
    },
    {
      key: 'methods',
      header: 'Methods',
      render: (route: Route) => (
        <div className="flex flex-wrap gap-1">
          {route.methods.slice(0, 3).map(m => (
            <Badge key={m} variant="info" size="sm">{m}</Badge>
          ))}
          {route.methods.length > 3 && (
            <Badge variant="default" size="sm">+{route.methods.length - 3}</Badge>
          )}
        </div>
      ),
    },
    {
      key: 'policy_id',
      header: 'Cache Policy',
      render: (route: Route) => getPolicyName(route.policy_id),
    },
    {
      key: 'is_active',
      header: 'Status',
      render: (route: Route) => (
        <Badge variant={route.is_active ? 'success' : 'error'}>
          {route.is_active ? 'Active' : 'Inactive'}
        </Badge>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (route: Route) => (
        <div className="flex items-center space-x-2">
          <button
            onClick={(e) => {
              e.stopPropagation()
              setEditingRoute(route)
              setFormData({
                name: route.name,
                path_pattern: route.path_pattern,
                methods: route.methods,
                upstream_base_url: route.upstream_base_url,
                timeout_ms: route.timeout_ms,
                policy_id: route.policy_id || '',
              })
            }}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <Edit2 className="w-4 h-4 text-gray-500" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (confirm('Delete this route?')) {
                deleteMutation.mutate(route.id)
              }
            }}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
          >
            <Trash2 className="w-4 h-4 text-red-500" />
          </button>
        </div>
      ),
    },
  ]
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    const data = {
      ...formData,
      policy_id: formData.policy_id || null,
    }
    if (editingRoute) {
      updateMutation.mutate({ id: editingRoute.id, data })
    } else {
      createMutation.mutate(data)
    }
  }
  
  const toggleMethod = (method: string) => {
    if (formData.methods.includes(method)) {
      setFormData({
        ...formData,
        methods: formData.methods.filter(m => m !== method),
      })
    } else {
      setFormData({
        ...formData,
        methods: [...formData.methods, method],
      })
    }
  }
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Routes</h1>
          <p className="text-gray-500 mt-1">Configure upstream routing</p>
        </div>
        <button
          onClick={() => {
            resetForm()
            setIsCreateOpen(true)
          }}
          className="btn-primary flex items-center space-x-2"
        >
          <Plus className="w-4 h-4" />
          <span>Add Route</span>
        </button>
      </div>
      
      <DataTable
        columns={columns}
        data={routes}
        keyField="id"
        isLoading={isLoading}
        emptyMessage="No routes found. Create one to get started."
      />
      
      {/* Create/Edit Modal */}
      <Modal
        isOpen={isCreateOpen || !!editingRoute}
        onClose={() => {
          setIsCreateOpen(false)
          setEditingRoute(null)
        }}
        title={editingRoute ? 'Edit Route' : 'Create Route'}
        footer={
          <div className="flex justify-end space-x-3">
            <button
              onClick={() => {
                setIsCreateOpen(false)
                setEditingRoute(null)
              }}
              className="btn-secondary"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!formData.name || !formData.upstream_base_url || createMutation.isPending}
              className="btn-primary"
            >
              {createMutation.isPending || updateMutation.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        }
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="label">Route Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="input"
              placeholder="api-v1"
              required
            />
            <p className="text-xs text-gray-500 mt-1">
              Used in URL: /g/{formData.name || 'route-name'}/...
            </p>
          </div>
          
          <div>
            <label className="label">Upstream Base URL</label>
            <input
              type="url"
              value={formData.upstream_base_url}
              onChange={(e) => setFormData({ ...formData, upstream_base_url: e.target.value })}
              className="input"
              placeholder="http://backend:8001"
              required
            />
          </div>
          
          <div>
            <label className="label">Path Pattern</label>
            <input
              type="text"
              value={formData.path_pattern}
              onChange={(e) => setFormData({ ...formData, path_pattern: e.target.value })}
              className="input"
              placeholder="/*"
            />
          </div>
          
          <div>
            <label className="label">HTTP Methods</label>
            <div className="flex flex-wrap gap-2 mt-2">
              {['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'HEAD', 'OPTIONS'].map(method => (
                <button
                  key={method}
                  type="button"
                  onClick={() => toggleMethod(method)}
                  className={`px-3 py-1 rounded-lg text-sm font-medium transition-colors ${
                    formData.methods.includes(method)
                      ? 'bg-primary-100 text-primary-700 border border-primary-300'
                      : 'bg-gray-100 text-gray-600 border border-gray-200'
                  }`}
                >
                  {method}
                </button>
              ))}
            </div>
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">Timeout (ms)</label>
              <input
                type="number"
                value={formData.timeout_ms}
                onChange={(e) => setFormData({ ...formData, timeout_ms: parseInt(e.target.value) || 30000 })}
                className="input"
                min="100"
                max="300000"
              />
            </div>
            <div>
              <label className="label">Cache Policy</label>
              <select
                value={formData.policy_id}
                onChange={(e) => setFormData({ ...formData, policy_id: e.target.value })}
                className="input"
              >
                <option value="">No caching</option>
                {policies.map((policy) => (
                  <option key={policy.id} value={policy.id}>
                    {policy.name} ({policy.ttl_seconds}s TTL)
                  </option>
                ))}
              </select>
            </div>
          </div>
        </form>
      </Modal>
    </div>
  )
}
