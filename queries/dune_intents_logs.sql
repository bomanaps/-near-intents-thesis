SELECT
    block_date,
    block_height,
    block_time,
    receipt_id,
    executor_account_id,
    index_in_execution_outcome_logs,
    log
FROM near.logs
WHERE executor_account_id IN ('intents.near', 'defuse-alpha.near')
  AND starts_with(log, 'EVENT_JSON:')
  AND block_date >= DATE '2025-10-01'
ORDER BY block_height ASC, index_in_execution_outcome_logs ASC
