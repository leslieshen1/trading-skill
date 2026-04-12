import { useState } from 'react';
import { api } from '../api';
import type { Ticker } from '../api';
import { usePolling, formatNumber, formatPrice, cn } from '../hooks';

type SortKey = 'symbol' | 'price' | 'change_24h' | 'volume_24h' | 'funding_rate';

export default function Market() {
  const [market, setMarket] = useState<'futures_um' | 'spot'>('futures_um');
  const [sortKey, setSortKey] = useState<SortKey>('volume_24h');
  const [sortAsc, setSortAsc] = useState(false);

  const tickers = usePolling(() => api.tickers(market, 100), 10000);

  const sorted = [...(tickers.data ?? [])].sort((a, b) => {
    const av = a[sortKey] ?? 0;
    const bv = b[sortKey] ?? 0;
    if (typeof av === 'string') return sortAsc ? av.localeCompare(bv as string) : (bv as string).localeCompare(av);
    return sortAsc ? (av as number) - (bv as number) : (bv as number) - (av as number);
  });

  const handleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const SortHeader = ({ k, label, align = 'right' }: { k: SortKey; label: string; align?: string }) => (
    <th
      className={cn(
        'px-3 py-2 cursor-pointer hover:text-[var(--text-primary)] select-none',
        align === 'left' ? 'text-left' : 'text-right',
      )}
      onClick={() => handleSort(k)}
    >
      {label} {sortKey === k ? (sortAsc ? '↑' : '↓') : ''}
    </th>
  );

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Market</h2>
        <div className="flex gap-2">
          {(['futures_um', 'spot'] as const).map((m) => (
            <button
              key={m}
              onClick={() => setMarket(m)}
              className={cn(
                'px-3 py-1.5 rounded text-sm',
                market === m
                  ? 'bg-[var(--blue)] text-white'
                  : 'bg-[var(--bg-card)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]',
              )}
            >
              {m === 'futures_um' ? 'USDT-M Futures' : 'Spot'}
            </button>
          ))}
        </div>
      </div>

      <div className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg overflow-hidden">
        {tickers.loading ? (
          <p className="p-4 text-sm text-[var(--text-secondary)]">Loading...</p>
        ) : tickers.error ? (
          <p className="p-4 text-sm text-[var(--red)]">{tickers.error}</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[var(--text-secondary)] text-xs border-b border-[var(--border)]">
                <SortHeader k="symbol" label="Symbol" align="left" />
                <SortHeader k="price" label="Price" />
                <SortHeader k="change_24h" label="24h %" />
                <SortHeader k="volume_24h" label="Volume" />
                {market === 'futures_um' && <SortHeader k="funding_rate" label="Funding" />}
              </tr>
            </thead>
            <tbody>
              {sorted.map((t: Ticker) => (
                <tr key={t.symbol} className="border-b border-[var(--border)] hover:bg-white/[0.02]">
                  <td className="px-3 py-2 font-medium">{t.symbol}</td>
                  <td className="px-3 py-2 text-right">{formatPrice(t.price)}</td>
                  <td className={cn('px-3 py-2 text-right', t.change_24h >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]')}>
                    {t.change_24h >= 0 ? '+' : ''}{t.change_24h.toFixed(2)}%
                  </td>
                  <td className="px-3 py-2 text-right text-[var(--text-secondary)]">${formatNumber(t.quote_volume_24h, 0)}</td>
                  {market === 'futures_um' && (
                    <td className={cn('px-3 py-2 text-right', fundingColor(t.funding_rate))}>
                      {t.funding_rate != null ? `${(t.funding_rate * 100).toFixed(4)}%` : '-'}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function fundingColor(rate: number | null): string {
  if (rate == null) return '';
  if (rate > 0.0001) return 'text-[var(--green)]';
  if (rate < -0.0001) return 'text-[var(--red)]';
  return 'text-[var(--text-secondary)]';
}
