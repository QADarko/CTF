-- Infrastructure bootstrap only. Application migrations remain authoritative.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE SCHEMA IF NOT EXISTS ctf;
CREATE SCHEMA IF NOT EXISTS audit;

COMMENT ON SCHEMA ctf IS
  'CTF application namespace; managed by versioned application migrations.';
COMMENT ON SCHEMA audit IS
  'Append-only workflow, authority, AI-run, attachment, and ERI audit records.';

-- A startup marker proves initialization without prematurely defining domain tables.
CREATE TABLE IF NOT EXISTS ctf.infrastructure_metadata (
  key text PRIMARY KEY,
  value jsonb NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO ctf.infrastructure_metadata (key, value)
VALUES (
  'bootstrap',
  jsonb_build_object(
    'schema_version', 1,
    'purpose', 'CTF Full V1 local infrastructure',
    'domain_schema_owned_by', 'application migrations'
  )
)
ON CONFLICT (key) DO NOTHING;
