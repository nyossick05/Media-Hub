-- Stockfolio Schema
-- Run this in your Supabase SQL editor

-- Portfolios
create table portfolios (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  name text not null default 'My Portfolio',
  benchmark text not null default 'SPY',
  created_at timestamptz default now()
);

-- Holdings (imported from Fidelity CSV)
create table holdings (
  id uuid primary key default gen_random_uuid(),
  portfolio_id uuid references portfolios(id) on delete cascade,
  ticker text not null,
  shares numeric not null,
  cost_basis_per_share numeric,        -- average cost basis
  current_price numeric,               -- cached from Polygon
  price_updated_at timestamptz,
  imported_at timestamptz default now()
);

-- Dividends (manually logged)
create table dividends (
  id uuid primary key default gen_random_uuid(),
  portfolio_id uuid references portfolios(id) on delete cascade,
  ticker text not null,
  amount_per_share numeric not null,
  shares_held numeric not null,
  ex_date date not null,
  pay_date date,
  paid boolean default false,
  created_at timestamptz default now()
);

-- Benchmark snapshots (cached for performance comparison)
create table benchmark_snapshots (
  id uuid primary key default gen_random_uuid(),
  ticker text not null,
  price numeric not null,
  snapshot_date date not null,
  created_at timestamptz default now(),
  unique(ticker, snapshot_date)
);

-- Indexes
create index on holdings(portfolio_id);
create index on dividends(portfolio_id);
create index on dividends(ticker);
create index on benchmark_snapshots(ticker, snapshot_date);

-- Row Level Security
alter table portfolios enable row level security;
alter table holdings enable row level security;
alter table dividends enable row level security;

create policy "Users manage own portfolios" on portfolios
  for all using (auth.uid() = user_id);

create policy "Users manage own holdings" on holdings
  for all using (
    portfolio_id in (select id from portfolios where user_id = auth.uid())
  );

create policy "Users manage own dividends" on dividends
  for all using (
    portfolio_id in (select id from portfolios where user_id = auth.uid())
  );