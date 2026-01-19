'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi, ApiKey, Tenant } from '@/lib/api'
import DataTable from '@/components/DataTable'
import Modal from '@/components/Modal'
import Badge from '@/components/Badge'
import { Plus, Copy, RefreshCw, Trash2 } from 'lucide-react'
import { format } from 'date-fns'

export default function ApiKeysPage() {
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [createdKey, setCreatedKey] = useState<string | null>(null)
  const [formData, setFormData] = useState({
    tenant_id: '',
    name: '',
    quota_daily: 0,
    quota_monthly: 0,
  })
  
  const queryClient = useQueryClient()
  
  const { data: keys = [], isLoading } = useQuery({
    queryKey: ['api-keys'],
    queryFn: () => adminApi.getApiKeys(),
  })
  
  const { data: tenants = [] } = useQuery({
    queryKey: ['tenants'],
    queryFn: adminApi.getTenants,
  })
  
  const createMutation = useMutation({
    mutationFn: adminApi.createApiKey,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      setCreatedKey(data.key || null)
    },
  })
  
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<ApiKey> }) =>
      adminApi.updateApiKey(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })
  
  const deleteMutation = useMutation({
    mutationFn: adminApi.deleteApiKey,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
    },
  })
  
  const rotateMutation = useMutation({
    mutationFn: adminApi.rotateApiKey,
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['api-keys'] })
      setCreatedKey(data.key || null)
    },
  })
  
  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'active':
        return <Badge variant="success">Active</Badge>
      case 'disabled':
        return <Badge variant="warning">Disabled</Badge>
      case 'revoked':
        return <Badge variant="error">Revoked</Badge>
      default:
        return <Badge>{status}</Badge>
    }
  }
  
  const getTenantName = (tenantId: string) => {
    const tenant = tenants.find(t => t.id === tenantId)
    return tenant?.name || 'Unknown'
  }
  
  const columns = [
    {
      key: 'name',
      header: 'Name',
      render: (key: ApiKey) => (
        <div>
          <p className="font-medium text-gray-900">{key.name}</p>
          <p className="text-sm text-gray-500 font-mono">{key.key_prefix}...</p>
        </div>
      ),
    },
    {
      key: 'tenant_id',
      header: 'Tenant',
      render: (key: ApiKey) => getTenantName(key.tenant_id),
    },
    {
      key: 'status',
      header: 'Status',
      render: (key: ApiKey) => getStatusBadge(key.status),
    },
    {
      key: 'quotas',
      header: 'Quotas',
      render: (key: ApiKey) => (
        <div className="text-sm">
          <p>Daily: {key.quota_daily || '∞'}</p>
          <p>Monthly: {key.quota_monthly || '∞'}</p>
        </div>
      ),
    },
    {
      key: 'last_used_at',
      header: 'Last Used',
      render: (key: ApiKey) => 
        key.last_used_at 
          ? format(new Date(key.last_used_at), 'MMM d, HH:mm')
          : 'Never',
    },
    {
      key: 'actions',
      header: '',
      render: (key: ApiKey) => (
        <div className="flex items-center space-x-2">
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (key.status === 'active') {
                updateMutation.mutate({ id: key.id, data: { status: 'disabled' } })
              } else {
                updateMutation.mutate({ id: key.id, data: { status: 'active' } })
              }
            }}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors text-sm text-gray-600"
          >
            {key.status === 'active' ? 'Disable' : 'Enable'}
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (confirm('Rotate this API key? The old key will stop working.')) {
                rotateMutation.mutate(key.id)
              }
            }}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            title="Rotate Key"
          >
            <RefreshCw className="w-4 h-4 text-gray-500" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation()
              if (confirm('Delete this API key? This cannot be undone.')) {
                deleteMutation.mutate(key.id)
              }
            }}
            className="p-2 hover:bg-gray-100 rounded-lg transition-colors"
            title="Delete"
          >
            <Trash2 className="w-4 h-4 text-red-500" />
          </button>
        </div>
      ),
    },
  ]
  
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate(formData)
  }
  
  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
  }
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">API Keys</h1>
          <p className="text-gray-500 mt-1">Manage authentication keys</p>
        </div>
        <button
          onClick={() => {
            setFormData({ tenant_id: '', name: '', quota_daily: 0, quota_monthly: 0 })
            setCreatedKey(null)
            setIsCreateOpen(true)
          }}
          className="btn-primary flex items-center space-x-2"
        >
          <Plus className="w-4 h-4" />
          <span>Create Key</span>
        </button>
      </div>
      
      <DataTable
        columns={columns}
        data={keys}
        keyField="id"
        isLoading={isLoading}
        emptyMessage="No API keys found. Create one to get started."
      />
      
      {/* Create Modal */}
      <Modal
        isOpen={isCreateOpen}
        onClose={() => {
          setIsCreateOpen(false)
          setCreatedKey(null)
        }}
        title={createdKey ? 'API Key Created' : 'Create API Key'}
        footer={
          createdKey ? (
            <button onClick={() => { setIsCreateOpen(false); setCreatedKey(null) }} className="btn-primary">
              Done
            </button>
          ) : (
            <div className="flex justify-end space-x-3">
              <button onClick={() => setIsCreateOpen(false)} className="btn-secondary">
                Cancel
              </button>
              <button
                onClick={handleSubmit}
                disabled={!formData.tenant_id || !formData.name || createMutation.isPending}
                className="btn-primary"
              >
                {createMutation.isPending ? 'Creating...' : 'Create'}
              </button>
            </div>
          )
        }
      >
        {createdKey ? (
          <div className="space-y-4">
            <div className="bg-yellow-50 border border-yellow-200 rounded-lg p-4">
              <p className="text-sm text-yellow-800 font-medium">
                Save this key now! It won't be shown again.
              </p>
            </div>
            <div className="bg-gray-100 rounded-lg p-4 font-mono text-sm break-all">
              {createdKey}
            </div>
            <button
              onClick={() => copyToClipboard(createdKey)}
              className="btn-secondary flex items-center space-x-2 w-full justify-center"
            >
              <Copy className="w-4 h-4" />
              <span>Copy to Clipboard</span>
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="label">Tenant</label>
              <select
                value={formData.tenant_id}
                onChange={(e) => setFormData({ ...formData, tenant_id: e.target.value })}
                className="input"
                required
              >
                <option value="">Select a tenant...</option>
                {tenants.map((tenant) => (
                  <option key={tenant.id} value={tenant.id}>
                    {tenant.name}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="label">Name</label>
              <input
                type="text"
                value={formData.name}
                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                className="input"
                placeholder="Production Key"
                required
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="label">Daily Quota (0 = unlimited)</label>
                <input
                  type="number"
                  value={formData.quota_daily}
                  onChange={(e) => setFormData({ ...formData, quota_daily: parseInt(e.target.value) || 0 })}
                  className="input"
                  min="0"
                />
              </div>
              <div>
                <label className="label">Monthly Quota (0 = unlimited)</label>
                <input
                  type="number"
                  value={formData.quota_monthly}
                  onChange={(e) => setFormData({ ...formData, quota_monthly: parseInt(e.target.value) || 0 })}
                  className="input"
                  min="0"
                />
              </div>
            </div>
          </form>
        )}
      </Modal>
    </div>
  )
}
