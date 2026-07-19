ALTER TABLE watchlists ADD COLUMN IF NOT EXISTS is_selected BOOLEAN NOT NULL DEFAULT FALSE;

UPDATE watchlists
SET is_selected = FALSE
WHERE is_selected IS NULL;

WITH first_watchlist AS (
    SELECT id
    FROM watchlists
    ORDER BY created_at ASC, name ASC
    LIMIT 1
)
UPDATE watchlists
SET is_selected = TRUE
WHERE id IN (SELECT id FROM first_watchlist)
  AND NOT EXISTS (
      SELECT 1
      FROM watchlists
      WHERE is_selected = TRUE
  );
