# Supabase admin-owned default privilege follow-up

## Why this is separate from the migration

The live project was inspected read-only on 2026-11-28:

- The migration/SQL-editor role is `postgres`, and it is not a member of `supabase_admin`.
- `supabase_admin` is a superuser role and is a member of `postgres`; the membership does not grant the reverse `SET ROLE` capability.
- Both roles currently have default ACL entries granting `anon` privileges on future objects in `public`.
- PostgreSQL rejects `ALTER DEFAULT PRIVILEGES FOR ROLE supabase_admin` when executed as `postgres` (`permission denied to change default privileges`).

The ordinary migration therefore does only the operations its executor can safely perform:

1. Revoke existing `anon` table privileges from all 14 public tenant/legacy tables.
2. Remove `anon` table defaults for objects created by `postgres`.
3. Leave `authenticated` and `service_role` privileges unchanged.

It intentionally does **not** claim to change defaults owned by `supabase_admin`. Do not add the failing statement back to the regular migration: the local Supabase replay and a normal `supabase db push` execute as `postgres`.

## Privileged follow-up SQL

The exact privileged SQL is maintained in `supabase/operations/nexus_admin_anon_acl_hardening.sql`. It:
- removes future `anon` table and sequence defaults for `supabase_admin` in `public`;
- revokes current `anon` table privileges from `storage.objects`.

Execute that file only through a secure connection authenticated as `supabase_admin` or another superuser. Do not run it as the ordinary `postgres` migration role.

Then verify the default ACLs:

```sql
SELECT
  owner.rolname AS owner_role,
  n.nspname AS schema_name,
  d.defaclobjtype,
  grantee.rolname AS grantee_role,
  a.privilege_type
FROM pg_default_acl d
JOIN pg_roles owner ON owner.oid = d.defaclrole
JOIN pg_namespace n ON n.oid = d.defaclnamespace
CROSS JOIN LATERAL aclexplode(d.defaclacl) a
LEFT JOIN pg_roles grantee ON grantee.oid = a.grantee
WHERE n.nspname = 'public'
  AND owner.rolname = 'supabase_admin'
  AND grantee.rolname = 'anon'
  AND d.defaclobjtype IN ('r', 'S');
```

Expected result after the privileged operation:
- no rows for `supabase_admin` table or sequence defaults granted to `anon`;
- `has_table_privilege('anon', 'storage.objects', 'SELECT')` returns false.

## Operational boundary

This follow-up has **not** been executed. No database password or privileged role credential was retrieved, changed, or placed in GitHub/ChatGPT. It requires an administrator-controlled connection with the required role; if the project owner cannot obtain that connection through supported Supabase controls, request Supabase platform support rather than weakening role boundaries or changing credentials speculatively.

Until this is complete, all 14 public tenant/legacy tables are covered by the regular migration and the `postgres` defaults are hardened, but future tables created by `supabase_admin` may still inherit its existing `anon` defaults and `storage.objects` retains direct `anon` grants. Storage currently has only private buckets and RLS enabled with no `anon` object policies, so no anonymous object access was observed; the remaining direct grant is defense-in-depth. Treat the overall anonymous-privilege hardening as **partially complete**.
