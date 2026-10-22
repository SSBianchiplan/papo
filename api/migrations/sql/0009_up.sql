-- Multiusuário: marca de master (papel papo-master do Keycloak, gravado no login como is_admin)
-- e estatísticas por conta para a gestão de usuários. Só contagens: nenhum conteúdo sai daqui.
ALTER TABLE app_user ADD COLUMN is_master boolean NOT NULL DEFAULT false;

CREATE FUNCTION papo_user_stats()
RETURNS TABLE (user_id uuid, sub text, email text, display_name text, created_at timestamptz, is_admin boolean, is_master boolean,
               conversations bigint, agents bigint, documents bigint, bytes bigint, last_activity timestamptz)
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS $$
  SELECT a.id, a.sub, a.email, a.display_name, a.created_at, a.is_admin, a.is_master,
         (SELECT count(*) FROM conversation c WHERE c.owner_id = a.id),
         (SELECT count(*) FROM agent g WHERE g.owner_id = a.id),
         (SELECT count(*) FROM document d WHERE d.owner_id = a.id),
         (SELECT coalesce(sum(d.size_bytes), 0)::bigint FROM document d WHERE d.owner_id = a.id),
         (SELECT max(m.created_at) FROM message m JOIN conversation c ON c.id = m.conversation_id WHERE c.owner_id = a.id AND m.author = 'user')
    FROM app_user a
$$;
REVOKE ALL ON FUNCTION papo_user_stats() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION papo_user_stats() TO papo_app;
