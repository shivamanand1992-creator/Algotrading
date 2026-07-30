import React, { useState, useEffect } from 'react';
import { AlertCircle, Plus, Trash2, Save, RefreshCw } from 'lucide-react';

interface WatchlistItem {
  symbol: string;
  sector: string;
}

interface Config {
  watchlist: Record<string, string>;
  telegram_ids: number[];
  watchlist_count: number;
  telegram_count: number;
}

export function IntradayAlertsConfig() {
  const [config, setConfig] = useState<Config | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<'watchlist' | 'telegram'>('watchlist');

  // Watchlist state
  const [watchlist, setWatchlist] = useState<WatchlistItem[]>([]);
  const [newSymbol, setNewSymbol] = useState('');
  const [newSector, setNewSector] = useState('');
  const [savingWatchlist, setSavingWatchlist] = useState(false);

  // Telegram state
  const [newChatId, setNewChatId] = useState('');
  const [telegramUsers, setTelegramUsers] = useState<number[]>([]);
  const [addingUser, setAddingUser] = useState(false);
  const [removingUser, setRemovingUser] = useState<number | null>(null);

  // Load initial config
  useEffect(() => {
    loadConfig();
  }, []);

  const loadConfig = async () => {
    try {
      setLoading(true);
      const response = await fetch('/api/growsect/intraday-config');
      if (!response.ok) throw new Error('Failed to load config');
      const data: Config = await response.json();
      setConfig(data);
      setWatchlist(
        Object.entries(data.watchlist).map(([symbol, sector]) => ({
          symbol,
          sector,
        }))
      );
      setTelegramUsers(data.telegram_ids);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setLoading(false);
    }
  };

  // Save watchlist
  const handleSaveWatchlist = async () => {
    try {
      setSavingWatchlist(true);
      const watchlistObj = watchlist.reduce(
        (acc, item) => {
          acc[item.symbol] = item.sector;
          return acc;
        },
        {} as Record<string, string>
      );

      const response = await fetch('/api/growsect/intraday-config/watchlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(watchlistObj),
      });

      if (!response.ok) throw new Error('Failed to save watchlist');
      await loadConfig();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setSavingWatchlist(false);
    }
  };

  // Add watchlist item
  const handleAddWatchlistItem = () => {
    if (!newSymbol.trim() || !newSector.trim()) return;
    if (watchlist.some(w => w.symbol === newSymbol.toUpperCase())) {
      setError('Symbol already in watchlist');
      return;
    }
    setWatchlist([...watchlist, { symbol: newSymbol.toUpperCase(), sector: newSector }]);
    setNewSymbol('');
    setNewSector('');
    setError(null);
  };

  // Remove watchlist item
  const handleRemoveWatchlistItem = (symbol: string) => {
    setWatchlist(watchlist.filter(w => w.symbol !== symbol));
  };

  // Add telegram user
  const handleAddTelegramUser = async () => {
    try {
      if (!newChatId.trim()) return;
      const chatId = parseInt(newChatId, 10);
      if (isNaN(chatId)) {
        setError('Invalid chat ID (must be a number)');
        return;
      }

      setAddingUser(true);
      const response = await fetch(
        `/api/growsect/intraday-config/telegram-users?chat_id=${chatId}`,
        { method: 'POST' }
      );

      if (!response.ok) throw new Error('Failed to add user');
      const data = await response.json();
      setTelegramUsers(data.all_users);
      setNewChatId('');
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setAddingUser(false);
    }
  };

  // Remove telegram user
  const handleRemoveTelegramUser = async (chatId: number) => {
    try {
      setRemovingUser(chatId);
      const response = await fetch(
        `/api/growsect/intraday-config/telegram-users/${chatId}`,
        { method: 'DELETE' }
      );

      if (!response.ok) throw new Error('Failed to remove user');
      const data = await response.json();
      setTelegramUsers(data.all_users);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unknown error');
    } finally {
      setRemovingUser(null);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <div className="animate-spin mb-4">⟳</div>
          <p className="text-jarvis-primary/60">Loading configuration...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-white mb-2">📈 Intraday Alerts Config</h1>
        <p className="text-jarvis-primary/60">Manage GROWSECT15 watchlist & Telegram users for 9:30 AM alerts</p>
      </div>

      {/* Error Alert */}
      {error && (
        <div className="mb-6 p-4 rounded-lg bg-red-500/20 border border-red-500/50 flex items-start gap-3">
          <AlertCircle className="w-5 h-5 text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="text-red-400 font-medium">Error</p>
            <p className="text-red-300/80 text-sm">{error}</p>
          </div>
        </div>
      )}

      {/* Tab Navigation */}
      <div className="flex gap-2 mb-6 border-b border-jarvis-primary/20">
        <button
          onClick={() => setActiveTab('watchlist')}
          className={`px-4 py-3 font-medium transition-colors ${
            activeTab === 'watchlist'
              ? 'text-jarvis-primary border-b-2 border-jarvis-primary'
              : 'text-jarvis-primary/50 hover:text-jarvis-primary/75'
          }`}
        >
          📊 Watchlist ({watchlist.length})
        </button>
        <button
          onClick={() => setActiveTab('telegram')}
          className={`px-4 py-3 font-medium transition-colors ${
            activeTab === 'telegram'
              ? 'text-jarvis-primary border-b-2 border-jarvis-primary'
              : 'text-jarvis-primary/50 hover:text-jarvis-primary/75'
          }`}
        >
          📱 Telegram Users ({telegramUsers.length})
        </button>
      </div>

      {/* Content */}
      {activeTab === 'watchlist' ? (
        /* Watchlist Tab */
        <div className="space-y-6">
          {/* Add New Stock */}
          <div className="bg-jarvis-bg/50 border border-jarvis-primary/20 rounded-lg p-6">
            <h2 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
              <Plus className="w-5 h-5" />
              Add Stock to Watchlist
            </h2>
            <div className="flex gap-3">
              <input
                type="text"
                placeholder="Symbol (e.g., INFY)"
                value={newSymbol}
                onChange={(e) => setNewSymbol(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleAddWatchlistItem()}
                className="flex-1 px-4 py-2 bg-jarvis-bg/80 border border-jarvis-primary/30 rounded-lg text-white placeholder-jarvis-primary/40 focus:outline-none focus:border-jarvis-primary/60"
              />
              <input
                type="text"
                placeholder="Sector (e.g., IT)"
                value={newSector}
                onChange={(e) => setNewSector(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleAddWatchlistItem()}
                className="flex-1 px-4 py-2 bg-jarvis-bg/80 border border-jarvis-primary/30 rounded-lg text-white placeholder-jarvis-primary/40 focus:outline-none focus:border-jarvis-primary/60"
              />
              <button
                onClick={handleAddWatchlistItem}
                className="px-6 py-2 bg-jarvis-primary/20 hover:bg-jarvis-primary/30 border border-jarvis-primary/50 rounded-lg text-jarvis-primary font-medium transition-colors"
              >
                Add
              </button>
            </div>
          </div>

          {/* Current Watchlist */}
          <div className="bg-jarvis-bg/50 border border-jarvis-primary/20 rounded-lg p-6">
            <h2 className="text-lg font-bold text-white mb-4">Current Watchlist</h2>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mb-6">
              {watchlist.map((item) => (
                <div
                  key={item.symbol}
                  className="flex items-center justify-between p-3 bg-jarvis-bg/80 border border-jarvis-primary/30 rounded-lg"
                >
                  <div>
                    <p className="text-white font-bold">{item.symbol}</p>
                    <p className="text-jarvis-primary/60 text-sm">{item.sector}</p>
                  </div>
                  <button
                    onClick={() => handleRemoveWatchlistItem(item.symbol)}
                    className="p-2 hover:bg-red-500/20 rounded-lg text-red-400 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>

            {/* Save Button */}
            <button
              onClick={handleSaveWatchlist}
              disabled={savingWatchlist}
              className="w-full flex items-center justify-center gap-2 px-4 py-3 bg-green-500/20 hover:bg-green-500/30 border border-green-500/50 rounded-lg text-green-400 font-bold transition-colors disabled:opacity-50"
            >
              <Save className="w-5 h-5" />
              {savingWatchlist ? 'Saving...' : 'Save Watchlist'}
            </button>
          </div>
        </div>
      ) : (
        /* Telegram Tab */
        <div className="space-y-6">
          {/* Add New User */}
          <div className="bg-jarvis-bg/50 border border-jarvis-primary/20 rounded-lg p-6">
            <h2 className="text-lg font-bold text-white mb-4 flex items-center gap-2">
              <Plus className="w-5 h-5" />
              Add Telegram User
            </h2>
            <p className="text-jarvis-primary/60 text-sm mb-4">
              Get chat ID by messaging @userinfobot on Telegram
            </p>
            <div className="flex gap-3">
              <input
                type="text"
                placeholder="Telegram Chat ID (e.g., 8274242401)"
                value={newChatId}
                onChange={(e) => setNewChatId(e.target.value)}
                onKeyPress={(e) => e.key === 'Enter' && handleAddTelegramUser()}
                className="flex-1 px-4 py-2 bg-jarvis-bg/80 border border-jarvis-primary/30 rounded-lg text-white placeholder-jarvis-primary/40 focus:outline-none focus:border-jarvis-primary/60"
              />
              <button
                onClick={handleAddTelegramUser}
                disabled={addingUser}
                className="px-6 py-2 bg-jarvis-primary/20 hover:bg-jarvis-primary/30 border border-jarvis-primary/50 rounded-lg text-jarvis-primary font-medium transition-colors disabled:opacity-50"
              >
                {addingUser ? 'Adding...' : 'Add'}
              </button>
            </div>
          </div>

          {/* Current Users */}
          <div className="bg-jarvis-bg/50 border border-jarvis-primary/20 rounded-lg p-6">
            <h2 className="text-lg font-bold text-white mb-4">Registered Users</h2>
            <div className="space-y-2">
              {telegramUsers.map((chatId) => (
                <div
                  key={chatId}
                  className="flex items-center justify-between p-4 bg-jarvis-bg/80 border border-jarvis-primary/30 rounded-lg"
                >
                  <div>
                    <p className="text-white font-mono font-bold">{chatId}</p>
                    <p className="text-jarvis-primary/60 text-sm">
                      {chatId === 8274242401 && '👤 Shivam'}
                      {chatId === 1619146075 && '👤 Gaurav'}
                    </p>
                  </div>
                  <button
                    onClick={() => handleRemoveTelegramUser(chatId)}
                    disabled={removingUser === chatId}
                    className="p-2 hover:bg-red-500/20 rounded-lg text-red-400 transition-colors disabled:opacity-50"
                  >
                    {removingUser === chatId ? (
                      <RefreshCw className="w-4 h-4 animate-spin" />
                    ) : (
                      <Trash2 className="w-4 h-4" />
                    )}
                  </button>
                </div>
              ))}
            </div>
            {telegramUsers.length === 0 && (
              <p className="text-jarvis-primary/40 text-center py-8">No users configured yet</p>
            )}
          </div>

          {/* Test Alert Button */}
          <div className="bg-jarvis-bg/50 border border-jarvis-primary/20 rounded-lg p-6">
            <h2 className="text-lg font-bold text-white mb-4">🧪 Test Alert</h2>
            <p className="text-jarvis-primary/60 text-sm mb-4">
              Send a test message to all registered Telegram users with mock data
            </p>
            <button
              onClick={async () => {
                try {
                  const response = await fetch('/api/growsect/intraday-alerts/test-telegram', {
                    method: 'POST',
                  });
                  if (!response.ok) throw new Error('Test failed');
                  const data = await response.json();
                  alert(`✅ Test alert sent to ${data.all_users?.length || 'all'} users!`);
                } catch (err) {
                  alert(`❌ Error: ${err instanceof Error ? err.message : 'Unknown error'}`);
                }
              }}
              className="w-full px-4 py-3 bg-blue-500/20 hover:bg-blue-500/30 border border-blue-500/50 rounded-lg text-blue-400 font-bold transition-colors"
            >
              Send Test Message Now
            </button>
          </div>
        </div>
      )}

      {/* Info Panel */}
      <div className="mt-8 bg-jarvis-bg/30 border border-jarvis-primary/20 rounded-lg p-6">
        <h3 className="text-white font-bold mb-3">📋 About Intraday Alerts</h3>
        <ul className="space-y-2 text-jarvis-primary/70 text-sm">
          <li>✅ Runs automatically at <span className="text-jarvis-primary">9:30 AM IST</span> on weekdays</li>
          <li>✅ Sends stocks where <span className="text-jarvis-primary">both stock AND sector are up</span></li>
          <li>✅ Ranked by <span className="text-jarvis-primary">% gain</span> for optimal entry</li>
          <li>✅ Sent to all <span className="text-jarvis-primary">{telegramUsers.length} registered Telegram users</span></li>
          <li>✅ Update watchlist anytime (index reshuffle, preference change)</li>
        </ul>
      </div>
    </div>
  );
}
