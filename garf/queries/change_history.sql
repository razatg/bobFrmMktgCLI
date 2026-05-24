SELECT
  change_event.change_date_time AS changed_at,
  change_event.user_email AS user_email,
  change_event.client_type AS client_type,
  change_event.change_resource_type AS change_resource_type,
  change_event.resource_change_operation AS operation,
  change_event.change_resource_name AS change_resource_name,
  change_event.campaign~0 AS campaign_id,
  change_event.ad_group~0 AS ad_group_id,
  change_event.asset~0 AS asset_id,
  change_event.changed_fields AS changed_fields
FROM change_event
WHERE change_event.change_date_time BETWEEN "{start_date}" AND "{end_date}"
ORDER BY change_event.change_date_time DESC
LIMIT 10000;
