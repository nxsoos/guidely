BEGIN;
-- Explicit operator schema works even when the connection search_path excludes extensions.
CREATE FUNCTION public.guidely_match_chunks(query_embedding extensions.vector(768), document_ids text[], model_key text, match_count integer DEFAULT 5)
RETURNS TABLE(id text, document_id text, snippet text, section text, page integer, distance double precision)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path=public,extensions AS $$
 SELECT c.id,c.document_id,c.snippet,c.section,c.page,
        c.embedding OPERATOR(extensions.<=>) query_embedding
 FROM public.vector_chunks c JOIN public.documents d ON d.id=c.document_id
 WHERE c.document_id=ANY(document_ids) AND c.model=model_key AND d.state='ready'
 ORDER BY c.embedding OPERATOR(extensions.<=>) query_embedding LIMIT LEAST(GREATEST(match_count,1),5)
$$;
REVOKE ALL ON FUNCTION public.guidely_match_chunks(extensions.vector,text[],text,integer) FROM PUBLIC,anon,authenticated;
COMMIT;
