-- Delete sources that no task references.
-- Task deletion used to leave the source row behind, and nothing reads a
-- source except through the task that owns it, so these rows are unreachable.
-- Uploaded files under TEMP_DIR/uploads are not touched here -- SQL cannot
-- reach the filesystem. Remove them by hand if disk space matters.
DELETE FROM sources s
WHERE NOT EXISTS (
    SELECT 1 FROM tasks t WHERE t.source_id = s.id
);
