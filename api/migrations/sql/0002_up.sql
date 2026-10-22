-- Execuções órfãs (worker caiu no meio): sem isto a INV-RUN-005 travaria a conversa para sempre.
-- SECURITY DEFINER porque o reaper roda sem usuário (fora do RLS); só faz esta transição, nada mais.
CREATE FUNCTION papo_reap_runs(p_older interval) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE n integer;
BEGIN
  WITH stale AS (
    UPDATE agent_run
       SET status = 'failed', finished_at = now(),
           error = 'Execução interrompida por falha do servidor.'
     WHERE status IN ('queued','running')
       AND coalesce(started_at, queued_at) < now() - p_older
    RETURNING id)
  SELECT count(*) INTO n FROM stale;
  RETURN n;
END $$;
REVOKE ALL ON FUNCTION papo_reap_runs(interval) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION papo_reap_runs(interval) TO papo_app;
