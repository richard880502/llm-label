\pset tuples_only on
\pset format unaligned
\pset fieldsep '|'

SELECT 'users', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY id)), '') FROM users t;
SELECT 'projects', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY id)), '') FROM projects t;
SELECT 'rows', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY id)), '') FROM rows t;
SELECT 'tasks', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY id)), '') FROM tasks t;
SELECT 'task_items', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY id)), '') FROM task_items t;
SELECT 'api_tokens', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY id)), '') FROM api_tokens t;
SELECT 'llm_configs', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY id)), '') FROM llm_configs t;
SELECT 'row_llm_results', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY id)), '') FROM row_llm_results t;
SELECT 'audit_log', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY id)), '') FROM audit_log t;
SELECT 'presence', COUNT(*), COALESCE(md5(string_agg(md5(row_to_json(t)::text), '' ORDER BY username, row_id)), '') FROM presence t;
