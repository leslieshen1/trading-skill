import { useState } from 'react';
import { api } from './api';
import { usePolling, cn } from './hooks';
import Dashboard from './pages/Dashboard';
import Market from './pages/Market';
import Trades from './pages/Trades';
import Strategies from './pages/Strategies';

const TABS = ['Dashboard', 'Market', 'Trades', 'Strategies'] as const;
type Tab = (typeof TABS)[number];

function App() {
  const [tab, setTab] = useState<Tab>('Dashboard');
  const health = usePolling(() => api.health(), 15000);
  const ok = health.data?.status === 'ok';

  const Page = { Dashboard, Market, Trades, Strategies }[tab];

  return (
    <div className="flex h-screen">
      {/* Sidebar */}
      <aside className="w-56 shrink-0 bg-[var(--bg-secondary)] border-r border-[var(--border)] flex flex-col">
        <div className="p-4 border-b border-[var(--border)]">
          <h1 className="text-lg font-bold tracking-tight">
            <span className="text-[var(--blue)]">Crypto</span> Bot
          </h1>
          <p className="text-xs text-[var(--text-secondary)] mt-0.5">AI Trading Dashboard</p>
        </div>
        <nav className="flex-1 p-2 space-y-1">
          {TABS.map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                'w-full text-left px-3 py-2 rounded-md text-sm transition-colors',
                tab === t
                  ? 'bg-[var(--blue)]/15 text-[var(--blue)] font-medium'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-white/5',
              )}
            >
              {t}
            </button>
          ))}
        </nav>
        <div className="p-3 border-t border-[var(--border)]">
          <div className="flex items-center gap-2 text-xs text-[var(--text-secondary)]">
            <span className={cn('w-2 h-2 rounded-full', ok ? 'bg-[var(--green)]' : 'bg-[var(--red)]')} />
            {ok ? 'Backend connected' : 'Disconnected'}
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto p-6">
        <Page />
      </main>
    </div>
  );
}

export default App;
