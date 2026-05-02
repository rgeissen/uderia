-- Scheduler Enhancements: Platform Jobs + Independent Scheduler Gates
-- Note: job_type column is added via _ensure_columns() in task_scheduler.py
-- (SQLite has no ALTER TABLE IF NOT EXISTS for columns — handled in Python)

-- Seed the three platform maintenance jobs (idempotent via INSERT OR IGNORE)
-- The job_type column must exist before these rows are inserted (ensure_columns runs first)
INSERT OR IGNORE INTO scheduled_tasks (id, user_uuid, profile_id, name, prompt, schedule, enabled, job_type)
VALUES
    ('platform-consumption-hourly',   '__platform__', '__platform__',
     'Consumption Hourly Reset',    '__platform_job__', '5 * * * *',   1, 'platform'),
    ('platform-consumption-daily',    '__platform__', '__platform__',
     'Consumption Daily Reset',     '__platform_job__', '5 0 * * *',   1, 'platform'),
    ('platform-consumption-monthly',  '__platform__', '__platform__',
     'Consumption Monthly Rollover','__platform_job__', '10 0 1 * *',  1, 'platform');

-- Independent scheduler gates (INSERT OR IGNORE — safe on re-run)
INSERT OR IGNORE INTO component_settings (setting_key, setting_value)
VALUES
    ('profile_scheduler_enabled',  'true'),
    ('platform_scheduler_enabled', 'true');
