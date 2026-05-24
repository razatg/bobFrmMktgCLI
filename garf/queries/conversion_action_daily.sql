SELECT
  customer.id AS customer_id,
  campaign.id AS campaign_id,
  campaign.name AS campaign_name,
  segments.date AS date,
  segments.conversion_action AS conversion_action,
  segments.conversion_action_name AS conversion_action_name,
  segments.conversion_action_category AS conversion_action_category,
  metrics.conversions AS conversions,
  metrics.all_conversions AS all_conversions,
  metrics.biddable_app_install_conversions AS installs,
  metrics.biddable_app_post_install_conversions AS in_app_conversions
FROM campaign
WHERE campaign.advertising_channel_type = "MULTI_CHANNEL"
  AND campaign.advertising_channel_sub_type IN ("APP_CAMPAIGN", "APP_CAMPAIGN_FOR_ENGAGEMENT")
  AND segments.date BETWEEN "{start_date}" AND "{end_date}";
