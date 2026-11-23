-- Apply once to a NEW Supabase project using the SQL editor (postgres role).
BEGIN;
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
CREATE TABLE public.users (
 id text PRIMARY KEY, username text UNIQUE NOT NULL CHECK(length(username) BETWEEN 3 AND 80),
 password text NOT NULL, role text NOT NULL CHECK(role IN ('admin','reader')), created_at text NOT NULL);
CREATE TABLE public.sessions (
 token text PRIMARY KEY, user_id text NOT NULL REFERENCES public.users(id) ON DELETE CASCADE, expires double precision NOT NULL);
CREATE INDEX sessions_expiry_idx ON public.sessions(expires);
CREATE INDEX sessions_user_idx ON public.sessions(user_id);
CREATE TABLE public.documents (
 id text PRIMARY KEY, filename text NOT NULL, text text NOT NULL CHECK(length(text)<=24000),
 tags text NOT NULL DEFAULT '[]' CHECK(jsonb_typeof(tags::jsonb)='array'), category text NOT NULL DEFAULT '',
 state text NOT NULL CHECK(state IN ('pending','changed','indexing','ready','failed','deleting')),
 revision integer NOT NULL DEFAULT 1 CHECK(revision>0), indexed_hash text, error text, created_at text NOT NULL,
 object_key text UNIQUE NOT NULL);
CREATE TABLE public.jobs (
 id text PRIMARY KEY, document_id text NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
 state text NOT NULL CHECK(state IN ('queued','indexing','complete','failed')), error text,
 chunks integer DEFAULT 0 CHECK(chunks BETWEEN 0 AND 12), elapsed_ms double precision, created_at text NOT NULL);
CREATE INDEX jobs_document_idx ON public.jobs(document_id);
CREATE TABLE public.embeddings (key text PRIMARY KEY, kind text NOT NULL CHECK(kind IN ('document','question')), vector text NOT NULL);
CREATE TABLE public.counters(name text PRIMARY KEY,value bigint NOT NULL);
CREATE TABLE public.conversations (
 id text PRIMARY KEY,user_id text NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,title text NOT NULL,created_at text NOT NULL);
CREATE INDEX conversations_user_idx ON public.conversations(user_id);
CREATE TABLE public.messages (
 id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,conversation_id text NOT NULL REFERENCES public.conversations(id) ON DELETE CASCADE,
 question text NOT NULL,response text NOT NULL,created_at text NOT NULL);
CREATE INDEX messages_conversation_idx ON public.messages(conversation_id,id);
CREATE TABLE public.query_logs (
 id text PRIMARY KEY,user_id text REFERENCES public.users(id) ON DELETE SET NULL,question text,timestamp text NOT NULL,
 latency_ms double precision NOT NULL,sources text NOT NULL,outcome text NOT NULL);
CREATE TABLE public.vector_chunks (
 id text PRIMARY KEY, document_id text NOT NULL REFERENCES public.documents(id) ON DELETE CASCADE,
 model text NOT NULL,snippet text NOT NULL,section text NOT NULL,page integer NOT NULL CHECK(page BETWEEN 0 AND 10),
 embedding extensions.vector(768) NOT NULL);
CREATE INDEX vector_chunks_document_idx ON public.vector_chunks(document_id,model);
-- Exact cosine search for the bounded 50-document demo; approximate indexes reduce recall at this size.
CREATE TABLE public.upload_intents (
 id text PRIMARY KEY,user_id text NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,filename text NOT NULL,
 object_key text UNIQUE NOT NULL,size integer NOT NULL CHECK(size BETWEEN 1 AND 1048576),expires double precision NOT NULL,
 completed integer NOT NULL DEFAULT 0 CHECK(completed IN (0,1)));
CREATE TABLE public.login_attempts(key text PRIMARY KEY,attempts integer NOT NULL,expires double precision NOT NULL);
-- Existing custom sessions are validated by the backend. There is deliberately no browser DB access.
DO $$ DECLARE table_name text; BEGIN
 FOREACH table_name IN ARRAY ARRAY['users','sessions','documents','jobs','embeddings','counters','conversations','messages','query_logs','vector_chunks','upload_intents','login_attempts'] LOOP
  EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',table_name);
  EXECUTE format('REVOKE ALL ON TABLE public.%I FROM anon,authenticated',table_name);
 END LOOP;
END $$;
REVOKE ALL ON SEQUENCE public.messages_id_seq FROM anon,authenticated;
-- Backend connects as postgres over the TLS transaction pooler. Never expose its password/URL.
INSERT INTO storage.buckets(id,name,public,file_size_limit)
 VALUES ('guidely-documents','guidely-documents',false,1048576)
 ON CONFLICT(id) DO UPDATE SET public=false,file_size_limit=1048576;
-- Do NOT add anonymous/authenticated storage policies. Backend issues narrowly scoped signed URLs.
COMMIT;
