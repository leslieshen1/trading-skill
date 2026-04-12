import { api } from '../api';
import { usePolling, cn } from '../hooks';

export default function Strategies() {
  const strategies = usePolling(() => api.strategies(), 30000);

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold">Strategies</h2>

      {strategies.loading ? (
        <p className="text-sm text-[var(--text-secondary)]">Loading...</p>
      ) : strategies.error ? (
        <p className="text-sm text-[var(--red)]">{strategies.error}</p>
      ) : !strategies.data?.length ? (
        <p className="text-sm text-[var(--text-secondary)]">No strategies configured</p>
      ) : (
        <div className="grid gap-4">
          {strategies.data.map((s) => (
            <div key={s.name} className="bg-[var(--bg-card)] border border-[var(--border)] rounded-lg p-4">
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-3">
                  <h3 className="font-medium">{s.name}</h3>
                  <span className={cn(
                    'text-xs px-2 py-0.5 rounded-full',
                    s.enabled
                      ? 'bg-[var(--green)]/15 text-[var(--green)]'
                      : 'bg-[var(--red)]/15 text-[var(--red)]',
                  )}>
                    {s.enabled ? 'Enabled' : 'Disabled'}
                  </span>
                </div>
                <span className="text-xs text-[var(--text-secondary)] bg-[var(--bg-secondary)] px-2 py-1 rounded">
                  {s.type}
                </span>
              </div>
              {s.config && Object.keys(s.config).length > 0 && (
                <pre className="text-xs text-[var(--text-secondary)] bg-[var(--bg-primary)] rounded p-3 overflow-auto max-h-48">
                  {JSON.stringify(s.config, null, 2)}
                </pre>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
