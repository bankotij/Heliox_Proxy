'use client'

import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { adminApi, BlockRule } from '@/lib/api'
import DataTable from '@/components/DataTable'
import Badge from '@/components/Badge'
import { format } from 'date-fns'
import { Unlock, Shield } from 'lucide-react'

export default function AbusePage() {
  const queryClient = useQueryClient()
  
  const { data: blockedKeys = [], isLoading } = useQuery({
    queryKey: ['blocked-keys'],
    queryFn: adminApi.getBlockedKeys,
    refetchInterval: 30000,
  })
  
  const unblockMutation = useMutation({
    mutationFn: ({ apiKeyId, reason }: { apiKeyId: string; reason: string }) =>
      adminApi.unblockKey(apiKeyId, reason),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['blocked-keys'] })
    },
  })
  
  const getReasonBadge = (reason: string) => {
    switch (reason) {
      case 'rate_spike':
        return <Badge variant="error">Rate Spike</Badge>
      case 'error_rate_spike':
        return <Badge variant="warning">Error Rate</Badge>
      case 'manual':
        return <Badge variant="info">Manual</Badge>
      default:
        return <Badge>{reason}</Badge>
    }
  }
  
  const columns = [
    {
      key: 'api_key_id',
      header: 'API Key ID',
      render: (rule: BlockRule) => (
        <span className="font-mono text-sm">{rule.api_key_id.slice(0, 8)}...</span>
      ),
    },
    {
      key: 'reason',
      header: 'Reason',
      render: (rule: BlockRule) => (
        <div>
          {getReasonBadge(rule.reason)}
          {rule.reason_detail && (
            <p className="text-xs text-gray-500 mt-1">{rule.reason_detail}</p>
          )}
        </div>
      ),
    },
    {
      key: 'anomaly_score',
      header: 'Score',
      render: (rule: BlockRule) => (
        rule.anomaly_score ? rule.anomaly_score.toFixed(2) : '-'
      ),
    },
    {
      key: 'blocked_at',
      header: 'Blocked At',
      render: (rule: BlockRule) => format(new Date(rule.blocked_at), 'MMM d, HH:mm'),
    },
    {
      key: 'blocked_until',
      header: 'Expires',
      render: (rule: BlockRule) => (
        rule.blocked_until
          ? format(new Date(rule.blocked_until), 'MMM d, HH:mm')
          : <Badge variant="error">Permanent</Badge>
      ),
    },
    {
      key: 'is_active',
      header: 'Status',
      render: (rule: BlockRule) => (
        <Badge variant={rule.is_active ? 'error' : 'success'}>
          {rule.is_active ? 'Blocked' : 'Resolved'}
        </Badge>
      ),
    },
    {
      key: 'actions',
      header: '',
      render: (rule: BlockRule) => (
        rule.is_active && (
          <button
            onClick={() => {
              const reason = prompt('Reason for unblocking:')
              if (reason) {
                unblockMutation.mutate({ apiKeyId: rule.api_key_id, reason })
              }
            }}
            className="btn-secondary text-sm flex items-center space-x-1"
            disabled={unblockMutation.isPending}
          >
            <Unlock className="w-3 h-3" />
            <span>Unblock</span>
          </button>
        )
      ),
    },
  ]
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Abuse Detection</h1>
          <p className="text-gray-500 mt-1">Monitor and manage blocked API keys</p>
        </div>
      </div>
      
      {/* Info Card */}
      <div className="card bg-blue-50 border-blue-200">
        <div className="flex items-start space-x-3">
          <Shield className="w-5 h-5 text-blue-600 mt-0.5" />
          <div>
            <h3 className="font-medium text-blue-900">How Abuse Detection Works</h3>
            <p className="text-sm text-blue-700 mt-1">
              The gateway monitors request patterns using EWMA (Exponentially Weighted Moving Average) 
              and Z-score anomaly detection. When traffic spikes significantly above normal levels, 
              the API key is temporarily soft-blocked to protect upstream services.
            </p>
          </div>
        </div>
      </div>
      
      <DataTable
        columns={columns}
        data={blockedKeys}
        keyField="id"
        isLoading={isLoading}
        emptyMessage="No blocked API keys. All keys are operating normally."
      />
    </div>
  )
}
