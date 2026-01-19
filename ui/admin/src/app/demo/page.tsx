'use client'

import { useState } from 'react'
import { Play, Copy, CheckCircle, XCircle, Clock, Zap, Shield, Database } from 'lucide-react'

export default function DemoPage() {
  const [results, setResults] = useState<Record<string, any>>({})
  const [loading, setLoading] = useState<string | null>(null)
  
  const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
  
  const demos = [
    {
      id: 'cache-miss',
      title: 'Cache Miss (First Request)',
      description: 'First request to a slow endpoint - no cache, full upstream latency',
      icon: Clock,
      curl: `curl -X GET "${apiUrl}/g/demo/slow?delay=2" \\
  -H "X-API-Key: YOUR_API_KEY"`,
      expected: 'Response takes ~2 seconds (upstream delay). X-Cache: MISS',
    },
    {
      id: 'cache-hit',
      title: 'Cache Hit (Second Request)',
      description: 'Same request again - served from cache instantly',
      icon: Zap,
      curl: `curl -X GET "${apiUrl}/g/demo/slow?delay=2" \\
  -H "X-API-Key: YOUR_API_KEY"`,
      expected: 'Response is instant (<50ms). X-Cache: HIT',
    },
    {
      id: 'swr',
      title: 'Stale-While-Revalidate',
      description: 'After TTL expires but within stale window - serve stale, refresh in background',
      icon: Database,
      curl: `# Wait for TTL to expire, then:
curl -X GET "${apiUrl}/g/demo/slow?delay=2" \\
  -H "X-API-Key: YOUR_API_KEY"`,
      expected: 'Response is instant with stale data. X-Cache: STALE. Next request gets fresh data.',
    },
    {
      id: 'rate-limit',
      title: 'Rate Limiting',
      description: 'Exceed rate limit to see 429 response',
      icon: Shield,
      curl: `# Run this in a loop:
for i in {1..200}; do
  curl -s -o /dev/null -w "%{http_code}\\n" \\
    "${apiUrl}/g/demo/items" \\
    -H "X-API-Key: YOUR_API_KEY"
done | sort | uniq -c`,
      expected: 'After burst limit, requests return 429 with Retry-After header',
    },
    {
      id: 'bloom-404',
      title: 'Bloom Filter (404 Optimization)',
      description: 'After a 404, bloom filter prevents repeated upstream calls',
      icon: Database,
      curl: `# First request - hits upstream, returns 404
curl -X GET "${apiUrl}/g/demo/items/999" \\
  -H "X-API-Key: YOUR_API_KEY"

# Second request - bloom filter short-circuits
curl -X GET "${apiUrl}/g/demo/items/999" \\
  -H "X-API-Key: YOUR_API_KEY"`,
      expected: 'Second 404 is instant - bloom filter prevents upstream call',
    },
    {
      id: 'coalescing',
      title: 'Request Coalescing',
      description: 'Multiple concurrent requests share a single upstream call',
      icon: Zap,
      curl: `# Run 10 concurrent requests:
for i in {1..10}; do
  curl -s "${apiUrl}/g/demo/slow?delay=1" \\
    -H "X-API-Key: YOUR_API_KEY" &
done
wait`,
      expected: 'All 10 requests complete together. Upstream /stats shows only 1 request.',
    },
  ]
  
  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text)
  }
  
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Demo Walkthrough</h1>
        <p className="text-gray-500 mt-1">
          Step-by-step demonstrations of gateway features
        </p>
      </div>
      
      {/* Setup Card */}
      <div className="card bg-yellow-50 border-yellow-200">
        <h3 className="font-semibold text-yellow-900 mb-2">Setup Required</h3>
        <p className="text-sm text-yellow-800 mb-4">
          Before running demos, ensure you have:
        </p>
        <ol className="text-sm text-yellow-800 space-y-2 list-decimal list-inside">
          <li>Created a tenant and API key in the Admin UI</li>
          <li>Created a route named "demo" pointing to the example upstream (http://upstream:8001)</li>
          <li>Assigned a cache policy to the route</li>
        </ol>
        <div className="mt-4 p-3 bg-yellow-100 rounded-lg">
          <p className="text-xs font-mono text-yellow-900">
            Replace YOUR_API_KEY in the commands below with your actual key
          </p>
        </div>
      </div>
      
      {/* Demo Cards */}
      <div className="space-y-4">
        {demos.map((demo) => (
          <div key={demo.id} className="card">
            <div className="flex items-start justify-between">
              <div className="flex items-start space-x-4">
                <div className="p-2 bg-primary-50 rounded-lg">
                  <demo.icon className="w-5 h-5 text-primary-600" />
                </div>
                <div>
                  <h3 className="font-semibold text-gray-900">{demo.title}</h3>
                  <p className="text-sm text-gray-500 mt-1">{demo.description}</p>
                </div>
              </div>
            </div>
            
            <div className="mt-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-700">Command</span>
                <button
                  onClick={() => copyToClipboard(demo.curl)}
                  className="text-sm text-primary-600 hover:text-primary-700 flex items-center space-x-1"
                >
                  <Copy className="w-3 h-3" />
                  <span>Copy</span>
                </button>
              </div>
              <pre className="bg-gray-900 text-gray-100 p-4 rounded-lg overflow-x-auto text-sm">
                {demo.curl}
              </pre>
            </div>
            
            <div className="mt-4 p-3 bg-green-50 rounded-lg">
              <p className="text-sm text-green-800">
                <span className="font-medium">Expected: </span>
                {demo.expected}
              </p>
            </div>
          </div>
        ))}
      </div>
      
      {/* Metrics Comparison */}
      <div className="card">
        <h3 className="font-semibold text-gray-900 mb-4">Verify with Upstream Stats</h3>
        <p className="text-sm text-gray-600 mb-4">
          Compare gateway requests vs upstream requests to verify caching effectiveness:
        </p>
        <div className="grid grid-cols-2 gap-4">
          <div className="p-4 bg-gray-50 rounded-lg">
            <h4 className="font-medium text-gray-900 mb-2">Gateway Metrics</h4>
            <pre className="text-sm bg-gray-900 text-gray-100 p-3 rounded">
              curl {apiUrl}/metrics
            </pre>
          </div>
          <div className="p-4 bg-gray-50 rounded-lg">
            <h4 className="font-medium text-gray-900 mb-2">Upstream Stats</h4>
            <pre className="text-sm bg-gray-900 text-gray-100 p-3 rounded">
              curl http://localhost:8001/stats
            </pre>
          </div>
        </div>
        <p className="text-sm text-gray-500 mt-4">
          With caching enabled, gateway requests should far exceed upstream requests.
        </p>
      </div>
    </div>
  )
}
