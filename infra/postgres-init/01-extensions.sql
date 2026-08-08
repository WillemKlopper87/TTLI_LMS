-- Runs once, on first container start, before any migration.
--
-- citext   case-insensitive email domains and tenant slugs
-- pg_trgm  catalogue search, before a dedicated search service is justified
-- pgcrypto gen_random_bytes for tokens

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
