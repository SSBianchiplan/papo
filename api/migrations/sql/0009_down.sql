DROP FUNCTION IF EXISTS papo_user_stats();
ALTER TABLE app_user DROP COLUMN IF EXISTS is_master;
