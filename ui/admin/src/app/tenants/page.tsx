'use client'

import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi, Tenant } from '@/lib/api'
import DataTable from '@/components/DataTable'
import Modal from '@/components/Modal'
import Badge from '@/components/Badge'
import { Plus, Edit2 } from 'lucide-react'
import { format } from 'date-fns'

export default function TenantsPage() {
  const [isCreateOpen, setIsCreateOpen] = useState(false)
  const [editingTenant, setEditingTenant] = useState<Tenant | null>(null)
  const [formData, setFormData] = useState({ name: '', description: '' })
  
  const queryClient = useQueryClient()
  
  const { data: tenants = [], isLoading } = useQuery({
    queryKey: ['tenants'],
    queryFn: adminApi.getTenants,
  })
  
  const createMutation = useMutation({
    mutationFn: adminApi.createTenant,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tenants'] })
      setIsCreateOpen(false)
      setFormData({ name: '', description: '' })
    },
  })
  
  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Tenant> }) =>
      adminApi.updateTenant(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tenants'] })
      setEditingTenant(null)
    },
  })
  
  const columns = [
    {
      key: 'name',
      header: 'Name',
      render: (tenant: Tenant) => (
        <div>
          <p className="font-medium text-gray-900">{tenant.name}</p>
          {tenant.description && (
            <p className="text-sm text-gray-500 truncate max-w-xs">{tenant.description}</p>
          )}
        </div>
      ),
    },
    {
      key: 'is_active',
      header: 'Status',
      render: (tenant: Tenant) => (
        <Badge variant={tenant.is_active ? 'success' : 'error'}>
          {tenant.is_active ? 'Active' : 'Inactive'}
        </Badge>
      ),
    },
    {
      key: 'api_key_count',
      header: 'API Keys',
      render: (tenant: Tenant) => tenant.api_key_count,
    },
    {
      key: 'route_count',
      header: 'Routes',
      render: (tenant: Tenant) => tenant.route_count,
    },
    {
      key: 'created_at',
      header: 'Created',
      render: (tenant: Tenant) => format(new Date(tenant.created_at), 'MMM d, yyyy'),
    },
    {
      key: 'actions',
      header: '',
      render: (tenant: Tenant) => (
        <button
          onClick={(e) => {
            e.stopPropagation()
            setEditingTenant(tenant)
            setFormData({ name: tenant.name, description: tenant.description || '' })
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
    if (editingTenant) {
      updateMutation.mutate({ id: editingTenant.id, data: formData })
    } else {
      createMutation.mutate(formData)
    }
  }
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Tenants</h1>
          <p className="text-gray-500 mt-1">Manage customer organizations</p>
        </div>
        <button
          onClick={() => {
            setFormData({ name: '', description: '' })
            setIsCreateOpen(true)
          }}
          className="btn-primary flex items-center space-x-2"
        >
          <Plus className="w-4 h-4" />
          <span>Add Tenant</span>
        </button>
      </div>
      
      <DataTable
        columns={columns}
        data={tenants}
        keyField="id"
        isLoading={isLoading}
        emptyMessage="No tenants found. Create one to get started."
      />
      
      {/* Create/Edit Modal */}
      <Modal
        isOpen={isCreateOpen || !!editingTenant}
        onClose={() => {
          setIsCreateOpen(false)
          setEditingTenant(null)
        }}
        title={editingTenant ? 'Edit Tenant' : 'Create Tenant'}
        footer={
          <div className="flex justify-end space-x-3">
            <button
              onClick={() => {
                setIsCreateOpen(false)
                setEditingTenant(null)
              }}
              className="btn-secondary"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!formData.name || createMutation.isPending || updateMutation.isPending}
              className="btn-primary"
            >
              {createMutation.isPending || updateMutation.isPending ? 'Saving...' : 'Save'}
            </button>
          </div>
        }
      >
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="label">Name</label>
            <input
              type="text"
              value={formData.name}
              onChange={(e) => setFormData({ ...formData, name: e.target.value })}
              className="input"
              placeholder="Acme Corp"
              required
            />
          </div>
          <div>
            <label className="label">Description</label>
            <textarea
              value={formData.description}
              onChange={(e) => setFormData({ ...formData, description: e.target.value })}
              className="input"
              rows={3}
              placeholder="Optional description..."
            />
          </div>
          {editingTenant && (
            <div>
              <label className="label">Status</label>
              <select
                value={editingTenant.is_active ? 'active' : 'inactive'}
                onChange={(e) => setEditingTenant({
                  ...editingTenant,
                  is_active: e.target.value === 'active',
                })}
                className="input"
              >
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
              </select>
            </div>
          )}
        </form>
      </Modal>
    </div>
  )
}
