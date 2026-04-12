import { api } from '../api';
import { usePolling, formatNumber, formatPrice, cn } from '../hooks';

export default function Dashboard() {
  const status = usePolling(() => api.status(), 10000);
  const perf = usePolling(() => api.performance(), 30000);
  const positions = usePolling(() => api.positions(), 10000);

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Dashboard</h2>

      {/* Status Cards */}
      <div className="grid grid-cols-4 gap-4">
        <Card label="Open Positions" value={status.data?.open_positions ?? '-'} />
        <Card label="Today Trades" value={status.data?.today_trades ?? '-'} />
        <Card
          label="Today PnL"
          value={status.data ? `$${formatNumber(status.data.today_pnl)}` : '-'}
          color={status.data && status.data.today_pnl >= 0 ? 'green' : 'red'}
        />
        <Card
          label="Win Rate"
          value={perf.data ? `${(perf.data.win_rate * 100).toFixed(1)}%` : '-'}
        />
      </div>

      {/* Performance Metrics */}
      {perf.data && (
        <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg p-4">
          <h3 className="text-sm font-medium text-[var(--text-secondary)] mb-3">Performance</h3>
          <div className="grid grid-cols-4 gap-4 text-sm">
            <Metric label="Total Trades" value={perf.data.total_trades} />
            <Metric
              label="Total PnL"
              value={`$${formatNumber(perf.data.total_pnl)}`}
              color={perf.data.total_pnl >= 0 ? 'green' : 'red'}
            />
            <Metric label="Avg PnL" value={`$${formatNumber(perf.data.avg_pnl)}`} />
            <Metric label="Profit Factor" value={perf.data.profit_factor.toFixed(2)} />
            <Metric label="Sharpe Ratio" value={perf.data.sharpe_ratio.toFixed(2)} />
            <Metric label="Max Drawdown" value={`${perf.data.max_drawdown_pct.toFixed(1)}%`} color="red" />
            <Metric label="Max Consec. Losses" value={perf.data.max_consecutive_losses} />
          </div>
        </div>
      )}

      {/* Open Positions Table */}
      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg overflow-hidden">
        <div className="px-4 py-3 border-b border-[var(--border)]">
          <h3 className="text-sm font-medium text-[var(--text-secondary)]">Open Positions</h3>
        </div>
        {positions.loading ? (
          <p className="p-4 text-sm text-[var(--text-secondary)]">Loading...</p>
        ) : !positions.data?.length ? (
          <p className="p-4 text-sm text-[var(--text-secondary)]">No open positions</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[var(--text-secondary)] text-xs border-b border-[var(--border)]">
                <th className="text-left px-4 py-2">Symbol</th>
                <th className="text-left px-4 py-2">Side</th>
                <th className="text-right px-4 py-2">Entry</th>
                <th className="text-right px-4 py-2">Qty</th>
                <th className="text-right px-4 py-2">Stop Loss</th>
                <th className="text-right px-4 py-2">Take Profit</th>
                <th className="text-left px-4 py-2">Strategy</th>
              </tr>
            </thead>
            <tbody>
              {positions.data.map((p) => (
                <tr key={p.id} className="border-b border-[var(--border)] hover:bg-white/[0.02]">
                  <td className="px-4 py-2 font-medium">{p.symbol}</td>
                  <td className={cn('px-4 py-2', p.side === 'LONG' ? 'text-[var(--green)]' : 'text-[var(--red)]')}>
                    {p.side}
                  </td>
                  <td className="px-4 py-2 text-right">{formatPrice(p.entry_price)}</td>
                  <td className="px-4 py-2 text-right">{p.quantity}</td>
                  <td className="px-4 py-2 text-right">{p.stop_loss ? formatPrice(p.stop_loss) : '-'}</td>
                  <td className="px-4 py-2 text-right">{p.take_profit ? formatPrice(p.take_profit) : '-'}</td>
                  <td className="px-4 py-2 text-[var(--text-secondary)]">{p.strategy}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function Card({ label, value, color }: { label: string; value: string | number; color?: string }) {
  const colorClass = color === 'green' ? 'text-[var(--green)]' : color === 'red' ? 'text-[var(--red)]' : '';
  return (
    <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg p-4">
      <p className="text-xs text-[var(--text-secondary)] mb-1">{label}</p>
      <p className={cn('text-xl font-semibold', colorClass)}>{value}</p>
    </div>
  );
}

function Metric({ label, value, color }: { label: string; value: string | number; color?: string }) {
  const colorClass = color === 'green' ? 'text-[var(--green)]' : color === 'red' ? 'text-[var(--red)]' : '';
  return (
    <div>
      <p className="text-[var(--text-secondary)] text-xs">{label}</p>
      <p className={cn('font-medium', colorClass)}>{value}</p>
    </div>
  );
}
