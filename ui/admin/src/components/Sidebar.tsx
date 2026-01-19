'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { clsx } from 'clsx'
import {
  LayoutDashboard,
  Users,
  Key,
  Route,
  Database,
  Activity,
  Shield,
  BookOpen,
  Settings,
} from 'lucide-react'

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Tenants', href: '/tenants', icon: Users },
  { name: 'API Keys', href: '/keys', icon: Key },
  { name: 'Routes', href: '/routes', icon: Route },
  { name: 'Cache Policies', href: '/policies', icon: Database },
  { name: 'Logs', href: '/logs', icon: Activity },
  { name: 'Abuse', href: '/abuse', icon: Shield },
  { name: 'Demo', href: '/demo', icon: BookOpen },
]

export default function Sidebar() {
  const pathname = usePathname()

  return (
    <aside className="fixed inset-y-0 left-0 w-64 bg-white border-r border-gray-200">
      <div className="flex flex-col h-full">
        {/* Logo */}
        <div className="flex items-center h-16 px-6 border-b border-gray-200">
          <div className="flex items-center space-x-2">
            <div className="w-8 h-8 bg-primary-600 rounded-lg flex items-center justify-center">
              <span className="text-white font-bold text-lg">H</span>
            </div>
            <span className="font-semibold text-xl text-gray-900">Heliox</span>
          </div>
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-4 py-4 space-y-1 overflow-y-auto">
          {navigation.map((item) => {
            const isActive = pathname === item.href
            return (
              <Link
                key={item.name}
                href={item.href}
                className={clsx(
                  'flex items-center px-3 py-2 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary-50 text-primary-700'
                    : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                )}
              >
                <item.icon className={clsx(
                  'w-5 h-5 mr-3',
                  isActive ? 'text-primary-600' : 'text-gray-400'
                )} />
                {item.name}
              </Link>
            )
          })}
        </nav>

        {/* Settings */}
        <div className="p-4 border-t border-gray-200">
          <Link
            href="/settings"
            className="flex items-center px-3 py-2 rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-50 hover:text-gray-900 transition-colors"
          >
            <Settings className="w-5 h-5 mr-3 text-gray-400" />
            Settings
          </Link>
        </div>
      </div>
    </aside>
  )
}
