'use client'

import { useState, useEffect } from 'react'
import { setAdminKey, adminApi } from '@/lib/api'
import { Key, Save, Check } from 'lucide-react'

export default function SettingsPage() {
  const [adminKey, setAdminKeyState] = useState('')
  const [saved, setSaved] = useState(false)
  
  useEffect(() => {
    const storedKey = localStorage.getItem('adminKey')
    if (storedKey) {
      setAdminKeyState(storedKey)
    }
  }, [])
  
  const handleSave = () => {
    localStorage.setItem('adminKey', adminKey)
    setAdminKey(adminKey)
    setSaved(true)
    setTimeout(() => setSaved(false), 2000)
  }
  
  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-gray-500 mt-1">Configure admin access</p>
      </div>
      
      <div className="card">
        <h3 className="font-semibold text-gray-900 mb-4 flex items-center space-x-2">
          <Key className="w-5 h-5" />
          <span>Admin API Key</span>
        </h3>
        <p className="text-sm text-gray-600 mb-4">
          Enter your admin API key to access admin endpoints. This is set via the 
          ADMIN_API_KEY environment variable on the gateway.
        </p>
        <div className="flex space-x-3">
          <input
            type="password"
            value={adminKey}
            onChange={(e) => setAdminKeyState(e.target.value)}
            className="input flex-1"
            placeholder="Enter admin API key"
          />
          <button
            onClick={handleSave}
            className="btn-primary flex items-center space-x-2"
          >
            {saved ? (
              <>
                <Check className="w-4 h-4" />
                <span>Saved!</span>
              </>
            ) : (
              <>
                <Save className="w-4 h-4" />
                <span>Save</span>
              </>
            )}
          </button>
        </div>
      </div>
      
      <div className="card">
        <h3 className="font-semibold text-gray-900 mb-4">API Configuration</h3>
        <div className="space-y-3">
          <div className="flex justify-between py-2 border-b border-gray-100">
            <span className="text-gray-600">API URL</span>
            <span className="font-mono text-sm">{process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}</span>
          </div>
          <p className="text-sm text-gray-500">
            Set NEXT_PUBLIC_API_URL environment variable to change the gateway API URL.
          </p>
        </div>
      </div>
    </div>
  )
}
