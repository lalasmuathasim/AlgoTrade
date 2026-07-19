ALTER TABLE watchlists ADD COLUMN IF NOT EXISTS is_selected BOOLEAN;

UPDATE watchlists
SET is_selected = FALSE
WHERE is_selected IS NULL;

WITH chosen_watchlist AS (
    SELECT id
    FROM watchlists
    ORDER BY
        CASE WHEN is_selected = TRUE THEN 0 ELSE 1 END,
        created_at ASC,
        name ASC
    LIMIT 1
)
UPDATE watchlists
SET is_selected = CASE
    WHEN id IN (SELECT id FROM chosen_watchlist) THEN TRUE
    ELSE FALSE
END
WHERE EXISTS (SELECT 1 FROM watchlists);

ALTER TABLE watchlists ALTER COLUMN is_selected SET DEFAULT FALSE;
ALTER TABLE watchlists ALTER COLUMN is_selected SET NOT NULL;

DROP INDEX IF EXISTS ux_watchlists_selected_true;
CREATE UNIQUE INDEX IF NOT EXISTS ux_watchlists_selected_true
ON watchlists (is_selected)
WHERE is_selected = TRUE;
