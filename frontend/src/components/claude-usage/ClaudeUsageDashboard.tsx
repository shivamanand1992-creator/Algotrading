import React, { useEffect, useState } from 'react';
import { Card } from '../ui/Card';
import { api } from '../../api/client';

interface UsageMetrics {
  total_tokens: number;
  total_cost: number;
  by_model: Record<string, {
    input_tokens: number;
    output_tokens: number;
    total_tokens: number;
    cost_usd: number;
    requests: number;
  }>;
  by_day: Array<{
    date: string;
    total_tokens: number;
    cost_usd: number;
  }>;
  top_consumer: string | null;
}

interface BillingInfo {
  credits_remaining?: number;
  credits_limit?: number;
  next_billing_date?: string;
}

interface UsageReport {
  usage: UsageMetrics;
  yesterday: UsageMetrics;
  billing: BillingInfo;
  generated_at: string;
  period: {
    start: string;
    end: string;
  };
}

export function ClaudeUsageDashboard() {
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sendingTelegram, setSendingTelegram] = useState(false);

  useEffect(() => {
    fetchUsageReport();
    // Refresh every 5 minutes
    const interval = setInterval(() => {
      fetchUsageReport();
    }, 5 * 60 * 1000);

    return () => clearInterval(interval);
  }, []);

  const fetchUsageReport = async () => {
    try {
      setLoading(true);
      const response = await api.get('/api/claude-usage/report');
      setReport(response.data);
      setError(null);
    } catch (err: any) {
      console.error('Failed to fetch Claude usage:', err);
      setError(err.response?.data?.detail || 'Failed to load usage data');
    } finally {
      setLoading(false);
    }
  };

  const sendTelegramReport = async () => {
    try {
      setSendingTelegram(true);
      await api.post('/api/claude-usage/send-telegram-report');
      alert('Usage report sent to Telegram!');
    } catch (err: any) {
      alert(`Failed to send: ${err.response?.data?.detail || 'Unknown error'}`);
    } finally {
      setSendingTelegram(false);
    }
  };

  if (loading && !report) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-gray-400">Loading Claude API usage...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="text-red-400">{error}</div>
      </div>
    );
  }

  if (!report) {
    return null;
  }

  const { usage, yesterday, billing, period } = report;
  const creditsUsed = billing.credits_limit && billing.credits_remaining
    ? billing.credits_limit - billing.credits_remaining
    : 0;
  const usagePercent = billing.credits_limit
    ? (creditsUsed / billing.credits_limit) * 100
    : 0;

  return (
    <div className="space-y-6 p-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-gray-100">
          🤖 Claude API Usage
        </h1>
        <div className="flex gap-3">
          <button
            onClick={fetchUsageReport}
            disabled={loading}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg disabled:opacity-50 transition-colors"
          >
            {loading ? 'Refreshing...' : '🔄 Refresh'}
          </button>
          <button
            onClick={sendTelegramReport}
            disabled={sendingTelegram}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 rounded-lg disabled:opacity-50 transition-colors"
          >
            {sendingTelegram ? 'Sending...' : '📱 Send to Telegram'}
          </button>
        </div>
      </div>

      {/* Account Balance */}
      {billing.credits_limit && (
        <Card>
          <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
            💳 Account Balance
          </h2>
          <div className="space-y-4">
            <div className="flex justify-between items-center">
              <span className="text-gray-400">Credits Used</span>
              <span className="text-2xl font-bold text-gray-100">
                ${creditsUsed.toFixed(2)} / ${billing.credits_limit.toFixed(2)}
              </span>
            </div>
            <div className="w-full bg-gray-700 rounded-full h-4 overflow-hidden">
              <div
                className={`h-full transition-all ${
                  usagePercent > 90 ? 'bg-red-500' :
                  usagePercent > 70 ? 'bg-yellow-500' :
                  'bg-green-500'
                }`}
                style={{ width: `${Math.min(usagePercent, 100)}%` }}
              />
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Remaining</span>
              <span className={`font-semibold ${
                usagePercent > 90 ? 'text-red-400' : 'text-green-400'
              }`}>
                ${billing.credits_remaining?.toFixed(2)} ({(100 - usagePercent).toFixed(1)}%)
              </span>
            </div>
          </div>
        </Card>
      )}

      {/* Usage Summary */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* Yesterday */}
        <Card>
          <h3 className="text-lg font-semibold mb-3 text-gray-300">📅 Yesterday</h3>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-gray-400">Tokens</span>
              <span className="font-mono text-gray-100">
                {yesterday.total_tokens.toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Cost</span>
              <span className="font-mono text-green-400">
                ${yesterday.total_cost.toFixed(2)}
              </span>
            </div>
          </div>
        </Card>

        {/* This Month */}
        <Card>
          <h3 className="text-lg font-semibold mb-3 text-gray-300">
            📊 This Month
          </h3>
          <div className="text-sm text-gray-500 mb-2">
            {period.start} to {period.end}
          </div>
          <div className="space-y-2">
            <div className="flex justify-between">
              <span className="text-gray-400">Tokens</span>
              <span className="font-mono text-gray-100">
                {usage.total_tokens.toLocaleString()}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-gray-400">Cost</span>
              <span className="font-mono text-green-400">
                ${usage.total_cost.toFixed(2)}
              </span>
            </div>
          </div>
        </Card>

        {/* Top Consumer */}
        <Card>
          <h3 className="text-lg font-semibold mb-3 text-gray-300">🏆 Top Model</h3>
          <div className="text-2xl font-bold text-blue-400">
            {usage.top_consumer || 'N/A'}
          </div>
        </Card>
      </div>

      {/* Usage by Model */}
      <Card>
        <h2 className="text-xl font-semibold mb-4">🔧 Usage by Model</h2>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="border-b border-gray-700">
                <th className="text-left py-3 px-4 text-gray-400">Model</th>
                <th className="text-right py-3 px-4 text-gray-400">Input Tokens</th>
                <th className="text-right py-3 px-4 text-gray-400">Output Tokens</th>
                <th className="text-right py-3 px-4 text-gray-400">Total Tokens</th>
                <th className="text-right py-3 px-4 text-gray-400">Requests</th>
                <th className="text-right py-3 px-4 text-gray-400">Cost</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(usage.by_model)
                .sort(([, a], [, b]) => b.total_tokens - a.total_tokens)
                .map(([model, stats]) => (
                  <tr key={model} className="border-b border-gray-800 hover:bg-gray-800/50">
                    <td className="py-3 px-4 font-mono text-sm text-gray-100">{model}</td>
                    <td className="py-3 px-4 text-right font-mono text-sm">
                      {stats.input_tokens.toLocaleString()}
                    </td>
                    <td className="py-3 px-4 text-right font-mono text-sm">
                      {stats.output_tokens.toLocaleString()}
                    </td>
                    <td className="py-3 px-4 text-right font-mono text-sm font-semibold">
                      {stats.total_tokens.toLocaleString()}
                    </td>
                    <td className="py-3 px-4 text-right font-mono text-sm">
                      {stats.requests.toLocaleString()}
                    </td>
                    <td className="py-3 px-4 text-right font-mono text-sm text-green-400">
                      ${stats.cost_usd.toFixed(2)}
                    </td>
                  </tr>
                ))}
            </tbody>
          </table>
        </div>
      </Card>

      {/* Daily Trend */}
      <Card>
        <h2 className="text-xl font-semibold mb-4">📈 Daily Trend (Last 7 Days)</h2>
        <div className="space-y-2">
          {usage.by_day.slice(-7).reverse().map((day) => (
            <div
              key={day.date}
              className="flex items-center justify-between p-3 bg-gray-800/50 rounded-lg"
            >
              <span className="font-mono text-sm text-gray-400">{day.date}</span>
              <div className="flex items-center gap-4">
                <span className="font-mono text-sm">
                  {day.total_tokens.toLocaleString()} tokens
                </span>
                <span className="font-mono text-sm text-green-400">
                  ${day.cost_usd.toFixed(2)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </Card>

      <div className="text-center text-sm text-gray-500">
        Last updated: {new Date(report.generated_at).toLocaleString()}
      </div>
    </div>
  );
}
