SELECT
  customer.id AS customer_id,
  customer.descriptive_name AS customer_name,
  segments.ad_network_type AS network,
  metrics.reach AS reach,
  metrics.impressions AS impressions,
  metrics.clicks AS clicks,
  metrics.cost_micros / 1000000 AS cost,
  metrics.biddable_app_install_conversions AS installs,
  metrics.biddable_app_post_install_conversions AS in_app_conversions
FROM campaign
WHERE campaign.advertising_channel_type = "MULTI_CHANNEL"
  AND campaign.advertising_channel_sub_type IN ("APP_CAMPAIGN", "APP_CAMPAIGN_FOR_ENGAGEMENT")
  AND segments.date BETWEEN "{start_date}" AND "{end_date}";
