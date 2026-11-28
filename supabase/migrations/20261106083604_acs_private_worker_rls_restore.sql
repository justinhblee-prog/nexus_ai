
alter table private.generation_worker_leases enable row level security;
alter table private.generation_idempotency enable row level security;
revoke all on all tables in schema private from public, anon, authenticated;
revoke all on schema private from public, anon, authenticated;
