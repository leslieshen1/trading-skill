const BASE = '';

async function fetchJSON<T>(url: string): Promise<T> {
  const res = await fetch(`${BASE}${url}`);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

// Types
export interface Ticker {
  symbol: string;
  market: string;
  price: number;
  change_24h: number;
  volume_24h: number;
  quote_volume_24h: number;
  funding_rate: number | null;
  open_interest: number | null;
}

export interface Position {
  id: number;
  symbol: string;
  market: string;
  side: string;
  signal: string;
  strategy: string;
  entry_price: number;
  quantity: number;
  stop_loss: number | null;
  take_profit: number | null;
  opened_at: number;
}

export interface TradeHistory {
  id: number;
  symbol: string;
  signal: string;
  strategy: string;
  entry_price: number;
  exit_price: number | null;
  pnl: number | null;
  opened_at: number;
  closed_at: number | null;
}

export interface SignalRecord {
  id: number;
  symbol: string;
  strategy: string;
  signal: string;
  confidence: number;
  entry_price: number;
  ai_approved: number | null;
  executed: number;
  timestamp: number;
}

export interface Strategy {
  name: string;
  enabled: boolean;
  type: string;
  config: Record<string, unknown>;
}

export interface BotStatus {
  open_positions: number;
  today_trades: number;
  today_pnl: number;
}

export interface Performance {
  total_trades: number;
  win_rate: number;
  total_pnl: number;
  avg_pnl: number;
  profit_factor: number;
  sharpe_ratio: number;
  max_drawdown_pct: number;
  max_consecutive_losses: number;
}

// API functions
export const api = {
  health: () => fetchJSON<{ status: string }>('/health'),
  tickers: (market = 'futures_um', limit = 50) =>
    fetchJSON<Ticker[]>(`/api/market/tickers?market=${market}&limit=${limit}`),
  positions: () => fetchJSON<Position[]>('/api/trading/positions'),
  history: (limit = 50) => fetchJSON<TradeHistory[]>(`/api/trading/history?limit=${limit}`),
  signals: (limit = 50) => fetchJSON<SignalRecord[]>(`/api/trading/signals?limit=${limit}`),
  strategies: () => fetchJSON<Strategy[]>('/api/strategy/list'),
  status: () => fetchJSON<BotStatus>('/api/monitor/status'),
  performance: () => fetchJSON<Performance>('/api/monitor/performance'),
};
