import { useState } from 'react';
import { api } from '../api';
import { usePolling, formatPrice, formatNumber, formatTime, cn } from '../hooks';

export default function Trades() {
  const [tab, setTab] = useState<'history' | 'signals'>('history');
  const history = usePolling(() => api.history(100), 15000);
  const signals = usePolling(() => api.signals(100), 15000);

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <h2 className="text-xl font-semibold">Trades</h2>
        <div className="flex gap-2">
          {(['history', 'signals'] as const).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                'px-3 py-1.5 rounded text-sm capitalize',
                tab === t
                  ? 'bg-[var(--blue)] text-white'
                  : 'bg-[var(--bg-card)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]',
              )}
            >
              {t}
            </button>
          ))}
        </div>
      </div>

      {tab === 'history' ? (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg overflow-hidden">
          {history.loading ? (
            <p className="p-4 text-sm text-[var(--text-secondary)]">Loading...</p>
          ) : !history.data?.length ? (
            <p className="p-4 text-sm text-[var(--text-secondary)]">No trade history</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[var(--text-secondary)] text-xs border-b border-[var(--border)]">
                  <th className="text-left px-3 py-2">Symbol</th>
                  <th className="text-left px-3 py-2">Signal</th>
                  <th className="text-left px-3 py-2">Strategy</th>
                  <th className="text-right px-3 py-2">Entry</th>
                  <th className="text-right px-3 py-2">Exit</th>
                  <th className="text-right px-3 py-2">PnL</th>
                  <th className="text-right px-3 py-2">Opened</th>
                  <th className="text-right px-3 py-2">Closed</th>
                </tr>
              </thead>
              <tbody>
                {history.data.map((t) => (
                  <tr key={t.id} className="border-b border-[var(--border)] hover:bg-white/[0.02]">
                    <td className="px-3 py-2 font-medium">{t.symbol}</td>
                    <td className={cn('px-3 py-2', t.signal.includes('LONG') ? 'text-[var(--green)]' : 'text-[var(--red)]')}>
                      {t.signal}
                    </td>
                    <td className="px-3 py-2 text-[var(--text-secondary)]">{t.strategy}</td>
                    <td className="px-3 py-2 text-right">{formatPrice(t.entry_price)}</td>
                    <td className="px-3 py-2 text-right">{t.exit_price ? formatPrice(t.exit_price) : '-'}</td>
                    <td className={cn('px-3 py-2 text-right font-medium', pnlColor(t.pnl))}>
                      {t.pnl != null ? `$${formatNumber(t.pnl)}` : '-'}
                    </td>
                    <td className="px-3 py-2 text-right text-[var(--text-secondary)]">{formatTime(t.opened_at)}</td>
                    <td className="px-3 py-2 text-right text-[var(--text-secondary)]">{t.closed_at ? formatTime(t.closed_at) : '-'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      ) : (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg overflow-hidden">
          {signals.loading ? (
            <p className="p-4 text-sm text-[var(--text-secondary)]">Loading...</p>
          ) : !signals.data?.length ? (
            <p className="p-4 text-sm text-[var(--text-secondary)]">No signals</p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[var(--text-secondary)] text-xs border-b border-[var(--border)]">
                  <th className="text-left px-3 py-2">Symbol</th>
                  <th className="text-left px-3 py-2">Strategy</th>
                  <th className="text-left px-3 py-2">Signal</th>
                  <th className="text-right px-3 py-2">Confidence</th>
                  <th className="text-right px-3 py-2">Entry</th>
                  <th className="text-center px-3 py-2">AI</th>
                  <th className="text-center px-3 py-2">Executed</th>
                  <th className="text-right px-3 py-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {signals.data.map((s) => (
                  <tr key={s.id} className="border-b border-[var(--border)] hover:bg-white/[0.02]">
                    <td className="px-3 py-2 font-medium">{s.symbol}</td>
                    <td className="px-3 py-2 text-[var(--text-secondary)]">{s.strategy}</td>
                    <td className={cn('px-3 py-2', s.signal.includes('LONG') ? 'text-[var(--green)]' : 'text-[var(--red)]')}>
                      {s.signal}
                    </td>
                    <td className="px-3 py-2 text-right">{(s.confidence * 100).toFixed(0)}%</td>
                    <td className="px-3 py-2 text-right">{formatPrice(s.entry_price)}</td>
                    <td className="px-3 py-2 text-center">
                      {s.ai_approved == null ? (
                        <span className="text-[var(--text-secondary)]">-</span>
                      ) : s.ai_approved ? (
                        <span className="text-[var(--green)]">Yes</span>
                      ) : (
                        <span className="text-[var(--red)]">No</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-center">
                      {s.executed ? (
                        <span className="text-[var(--green)]">Yes</span>
                      ) : (
                        <span className="text-[var(--text-secondary)]">No</span>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right text-[var(--text-secondary)]">{formatTime(s.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </div>
  );
}

function pnlColor(pnl: number | null): string {
  if (pnl == null) return '';
  return pnl >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]';
}
