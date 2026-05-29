-- Seed test data for DEV E2E corner-case suite.
-- User: synthetic telegram_id 9999999999999 (13-digit, outside Telegram int64 range).
-- Run: docker exec -i bookmarkbrain_postgres psql -U user -d bookmarkbrain < backend/scripts/seed_dev_e2e.sql
-- Idempotent: wipes prior data for this user, then reseeds.

-- HARD GUARD: refuse to run against production DB.
-- Two layers: (1) db-name allowlist, (2) abort if users table is "large".
-- Prod is expected to have a distinct db name (e.g. bookmarkbrain_prod) AND
-- >100 real users — either check trips the abort.
DO $$
DECLARE
  db TEXT := current_database();
  user_count INT;
BEGIN
  IF db NOT IN ('bookmarkbrain', 'bookmarkbrain_dev', 'bookmarkbrain_test') THEN
    RAISE EXCEPTION 'seed_dev_e2e.sql refuses unknown database: %', db;
  END IF;
  SELECT count(*) INTO user_count FROM users;
  IF user_count > 100 THEN
    RAISE EXCEPTION 'seed_dev_e2e.sql refuses to run: % users in db, likely prod', user_count;
  END IF;
END $$;

BEGIN;

-- Wipe prior dev data (CASCADE handles bookmarks/folders/reminders).
DELETE FROM users WHERE telegram_id = 9999999999999;

-- 1) The DEV user itself.
INSERT INTO users (id, telegram_id, telegram_username, telegram_first_name, created_at)
VALUES (
  '00000000-0000-0000-0000-9999999999e2',
  9999999999999,
  'dev_e2e',
  'DEV Test User',
  now() - interval '30 days'
);

-- 2) Folder for "spaces" corner-case (open existing space).
INSERT INTO folders (id, user_id, name, emoji, bookmarks_count, created_at)
VALUES (
  '11111111-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-9999999999e2',
  'идеи проекта',
  '💡',
  0,
  now() - interval '7 days'
);

-- 3a) Bare URL — ai still pending → frontend shows "Brain читает ссылку…" placeholder.
INSERT INTO bookmarks (id, user_id, source, url, raw_text, title, content_type, ai_status, is_favorite, is_archived, created_at, updated_at)
VALUES (
  '22222222-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-9999999999e2',
  'miniapp',
  'https://www.linkedin.com/posts/example-locked-post-001',
  'https://www.linkedin.com/posts/example-locked-post-001',
  NULL,
  'link',
  'pending',
  false, false,
  now() - interval '5 minutes',
  now() - interval '5 minutes'
);

-- 3b) Bare URL — ai completed but no summary (auth-walled fetch fail) → "контекст не извлёкся" placeholder.
INSERT INTO bookmarks (id, user_id, source, url, raw_text, title, content_type, summary, ai_status, is_favorite, is_archived, created_at, updated_at)
VALUES (
  '22222222-0000-0000-0000-000000000002',
  '00000000-0000-0000-0000-9999999999e2',
  'miniapp',
  'https://x.com/example/status/1234567890',
  'https://x.com/example/status/1234567890',
  NULL,
  'link',
  NULL,
  'completed',
  false, false,
  now() - interval '2 hours',
  now() - interval '2 hours'
);

-- 4) Rich text note with summary + key_ideas → renders brain-block.
INSERT INTO bookmarks (id, user_id, source, url, raw_text, title, content_type, summary, ai_status, item_type, key_ideas, is_favorite, is_archived, created_at, updated_at)
VALUES (
  '22222222-0000-0000-0000-000000000003',
  '00000000-0000-0000-0000-9999999999e2',
  'miniapp',
  NULL,
  'Алгоритмы RLHF — собрать сводку по последним работам Anthropic, OpenAI и DeepMind. Сравнить подходы к reward modeling и constitutional AI.',
  'RLHF — план обзора',
  'note',
  'Краткая сводка: три ведущих лаборатории используют разные подходы к alignment — Anthropic делает упор на constitutional AI, OpenAI на RLHF с human feedback, DeepMind на sparrow-подобные модели.',
  'completed',
  'note',
  '["constitutional AI vs reward modeling", "сравнить семплинг температуру", "RLHF не масштабируется по людям", "alignment tax — реальный"]'::jsonb,
  true,  -- избранное → попадает в фильтр fav
  false,
  now() - interval '1 day',
  now() - interval '1 day'
);

-- 5) Task list — covers checkbox/edit/deadline/overdue корнер-кейсы.
INSERT INTO bookmarks (id, user_id, source, url, raw_text, title, content_type, ai_status, structured_data, is_favorite, is_archived, created_at, updated_at)
VALUES (
  '22222222-0000-0000-0000-000000000004',
  '00000000-0000-0000-0000-9999999999e2',
  'miniapp',
  NULL,
  'Что доделать к релизу',
  'Что доделать к релизу',
  'task_list',
  'completed',
  jsonb_build_object(
    'type', 'task_list',
    'tasks', jsonb_build_array(
      jsonb_build_object('text', 'починить feedCache (мерцание при возврате)', 'done', true,  'deadline', NULL),
      jsonb_build_object('text', 'дедлайн уже просрочен',                       'done', false, 'deadline', to_char(now() - interval '2 days', 'YYYY-MM-DD')),
      jsonb_build_object('text', 'добавить тесты на dedup',                     'done', false, 'deadline', to_char(now() + interval '3 days', 'YYYY-MM-DD')),
      jsonb_build_object('text', 'без дедлайна — просто пункт',                 'done', false, 'deadline', NULL)
    )
  ),
  false, false,
  now() - interval '3 hours',
  now() - interval '3 hours'
);

-- 6) Voice transcription bookmark → covers voice filter chip + typed avatar.
INSERT INTO bookmarks (id, user_id, source, url, raw_text, title, content_type, transcription, media_duration, ai_status, is_favorite, is_archived, created_at, updated_at)
VALUES (
  '22222222-0000-0000-0000-000000000005',
  '00000000-0000-0000-0000-9999999999e2',
  'telegram',
  NULL,
  'Голосовая заметка про идею с автоматическим тегированием по контексту.',
  'голосовая · 0:42',
  'voice',
  'Голосовая заметка про идею с автоматическим тегированием по контексту.',
  42.0,
  'completed',
  false, false,
  now() - interval '6 hours',
  now() - interval '6 hours'
);

-- 7) Archived bookmark — должен НЕ показываться в дефолтной ленте (is_archived filter).
INSERT INTO bookmarks (id, user_id, source, raw_text, title, content_type, ai_status, is_favorite, is_archived, created_at, updated_at)
VALUES (
  '22222222-0000-0000-0000-000000000006',
  '00000000-0000-0000-0000-9999999999e2',
  'miniapp',
  'старая заметка в архиве',
  'архивная',
  'note',
  'completed',
  false, true,
  now() - interval '20 days',
  now() - interval '20 days'
);

-- 8) Two bookmarks inside the folder (for SpaceDetail screen).
INSERT INTO bookmarks (id, user_id, source, raw_text, title, content_type, ai_status, folder_id, created_at, updated_at)
VALUES
  ('22222222-0000-0000-0000-000000000007',
   '00000000-0000-0000-0000-9999999999e2',
   'miniapp', 'идея: shared spaces с тегированием по проектам', 'shared spaces', 'note', 'completed',
   '11111111-0000-0000-0000-000000000001',
   now() - interval '4 days', now() - interval '4 days'),
  ('22222222-0000-0000-0000-000000000008',
   '00000000-0000-0000-0000-9999999999e2',
   'miniapp', 'идея: голосовой /todo с авто-распознаванием дедлайна', 'voice /todo', 'note', 'completed',
   '11111111-0000-0000-0000-000000000001',
   now() - interval '6 days', now() - interval '6 days');

UPDATE folders SET bookmarks_count = 2 WHERE id = '11111111-0000-0000-0000-000000000001';

-- 9) One upcoming reminder linked to the task list — для bell + napomнинаний экрана.
INSERT INTO scheduled_messages (id, user_id, bookmark_id, kind, fire_at, status, payload, created_at)
VALUES (
  '33333333-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-9999999999e2',
  '22222222-0000-0000-0000-000000000004',
  'reminder',
  now() + interval '2 hours',
  'pending',
  '{"source": "miniapp", "text": "проверь задачи к релизу"}'::jsonb,
  now() - interval '1 hour'
);

COMMIT;

-- Verify
SELECT 'users' AS t, count(*) FROM users WHERE telegram_id = 9999999999999
UNION ALL SELECT 'bookmarks', count(*) FROM bookmarks WHERE user_id = '00000000-0000-0000-0000-9999999999e2'
UNION ALL SELECT 'folders',   count(*) FROM folders   WHERE user_id = '00000000-0000-0000-0000-9999999999e2'
UNION ALL SELECT 'reminders', count(*) FROM scheduled_messages WHERE user_id = '00000000-0000-0000-0000-9999999999e2';
