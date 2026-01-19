'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi, CachePolicy } from '@/lib/api'
import DataTable from '@/components/DataTable'
import Modal from '@/components/Modal'
import Badge from '@/components/Badge'
import { Plus, Edit2 } from 'lucide-react'

export default function PoliciesPage() {
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [editingPolicy, setEditingPolicy] = useState<CachePolicy | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    description: '',
    ttl_seconds: 300,
    stale_seconds: 60,
    vary_headers_json: [] as string[],
    cacheable_statuses_json: [200, 201, 204, 301, 304],
    max_body_bytes: 10485760,
    cache_no_store: false,
  })
  
  const queryClient = useQueryClient()
  
  const { data: policies = [], isLoading } = useQuery({
    queryKey: ['policies'],
    queryFn: adminApi.getPolicies,
  })
  
  const createMutation = useMutation({
    mutationFn: adminApi.createPolicy,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['policies'] })
      setIsCreateOpen(false)
      resetForm()
    },
  })
  
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<CachePolicy> }) =>
      adminApi.updatePolicy(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['policies'] })
      setEditingPolicy(null)
    },
  })
  
  const resetForm = () => {
    setFormData({
      name: '',
      description: '',
      ttl_seconds: 300,
      stale_seconds: 60,
      vary_headers_json: [],
      cacheable_statuses_json: [200, 201, 204, 301, 304],
      max_body_bytes: 10485760,
      cache_no_store: false,
    })
  }
  
  const columns = [
    {
      key: 'name',
      header: 'Name',
      render: (policy: CachePolicy) => (
        <div>
          <p className="font-medium text-gray-900">{policy.name}</p>
          {policy.description && (
            <p className="text-sm text-gray-500 truncate max-w-xs">{policy.description}</p>
          )}
        </div>
      ),
    },
    {
      key: 'ttl_seconds',
      header: 'TTL',
      render: (policy: CachePolicy) => (
        <span className="font-mono">{policy.ttl_seconds}s</span>
      ),
    },
    {
      key: 'stale_seconds',
      header: 'SWR Window',
      render: (policy: CachePolicy) => (
        <span className="font-mono">{policy.stale_seconds}s</span>
      ),
    },
    {
      key: 'vary_headers_json',
      header: 'Vary Headers',
      render: (policy: CachePolicy) => (
        <div className="flex flex-wrap gap-1">
          {policy.vary_headers_json.length === 0 ? (
            <span className="text-gray-400">None</span>
          ) : (
            policy.vary_headers_json.slice(0, 2).map(h => (
              <Badge key={h} size="sm">{h}</Badge>
            ))
          )}
          {policy.vary_headers_json.length > 2 && (
            <Badge size="sm">+{policy.vary_headers_json.length - 2}</Badge>
          )}
        </div>
      ),
    },
    {
      key: 'route_count',
      header: 'Routes',
      render: (policy: CachePolicy) => policy.route_count,
    },
    {
      key: 'cache_no_store',
      header: 'Status',
      render: (policy: CachePolicy) => (
        <Badge variant={policy.cache_no_store ? 'warning' : 'success'}>
          {policy.cache_no_store ? 'Bypass' : 'Active'}
        </Badge>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (policy: CachePolicy) => (
        <button
          onClick={(e) => {
            e.stopPropagation()
            setEditingPolicy(policy)
            setFormData({
              name: policy.name,
              description: policy.description || '',
              ttl_seconds: policy.ttl_seconds,
              stale_seconds: policy.stale_seconds,
              vary_headers_json: policy.vary_headers_json,
              cacheable_statuses_json: policy.cacheable_statuses_json,
              max_body_bytes: policy.max_body_bytes,
              cache_no_store: policy.cache_no_store,
            })
          }}
          className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
        >
          <Edit2 className="w-4 h-4 text-gray-500" />
        </button>
      ),
    },
  ]
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingPolicy) {
      updateMutation.mutate({ id: editingPolicy.id, data: formData })
    } else {
      createMutation.mutate(formData)
    }
  }
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Cache Policies</h1>
          <p className="text-gray-500 mt-1">Configure caching behavior</p>
        </div>
        <button
          onClick={() => {
            resetForm()
            setIsCreateOpen(true)
          }}
          className="btn-primary flex items-center space-x-2"
        >
          <Plus className="w-4 h-4" />
          <span>Add Policy</span>
        </button>
      </div>
      
      <DataTable
        columns={columns}
        data={policies}
        keyField="id"
        isLoading={isLoading}
        emptyMessage="No cache policies found. Create one to enable caching."
      />
      
      {/* Create/Edit Modal */}
      <Modal
        isOpen={isCreateOpen || !!editingPolicy}
        onClose={() => {
          setIsCreateOpen(false)
          setEditingPolicy(null)
        }}
        title={editingPolicy ? 'Edit Cache Policy' : 'Create Cache Policy'}
        footer={
          <div className="flex justify-end space-x-3">
            <button
              onClick={() => {
                setIsCreateOpen(false)
                setEditingPolicy(null)
              }}
              className="btn-secondary"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!formData.name || createMutation.isPending}
              className="btn-primary"
            >
              {createMutation.isPending || updateMutation.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        }
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="label">Policy Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="input"
              placeholder="default-cache"
              required
            />
          </div>
          
          <div>
            <label className="label">Description</label>
            <input
              type="text"
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="input"
              placeholder="Optional description"
            />
          </div>
          
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="label">TTL (seconds)</label>
              <input
                type="number"
                value={formData.ttl_seconds}
                onChange={(e) => setFormData({ ...formData, ttl_seconds: parseInt(e.target.value) || 0 })}
                className="input"
                min="0"
                max="604800"
              />
              <p className="text-xs text-gray-500 mt-1">How long to cache fresh responses</p>
            </div>
            <div>
              <label className="label">SWR Window (seconds)</label>
              <input
                type="number"
                value={formData.stale_seconds}
                onChange={(e) => setFormData({ ...formData, stale_seconds: parseInt(e.target.value) || 0 })}
                className="input"
                min="0"
                max="86400"
              />
              <p className="text-xs text-gray-500 mt-1">Serve stale while refreshing</p>
            </div>
          </div>
          
          <div>
            <label className="label">Max Body Size</label>
            <select
              value={formData.max_body_bytes}
              onChange={(e) => setFormData({ ...formData, max_body_bytes: parseInt(e.target.value) })}
              className="input"
            >
              <option value={1048576}>1 MB</option>
              <option value={5242880}>5 MB</option>
              <option value={10485760}>10 MB</option>
              <option value={52428800}>50 MB</option>
              <option value={104857600}>100 MB</option>
            </select>
          </div>
          
          <div>
            <label className="flex items-center space-x-2">
              <input
                type="checkbox"
                checked={formData.cache_no_store}
                onChange={(e) => setFormData({ ...formData, cache_no_store: e.target.checked })}
                className="rounded border-gray-300"
              />
              <span className="text-sm text-gray-700">Bypass cache (no-store)</span>
            </label>
          </div>
        </form>
      </Modal>
    </div>
  )
}
