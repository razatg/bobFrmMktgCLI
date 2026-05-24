SELECT
  customer.id AS customer_id,
  campaign.id AS campaign_id,
  campaign.name AS campaign_name,
  segments.date AS date,
  segments.ad_network_type AS network,
  metrics.impressions AS impressions,
  metrics.clicks AS clicks,
  metrics.cost_micros / 1000000 AS cost,
  metrics.average_cpc / 1000000 AS cpc,
  metrics.ctr * 100 AS ctr_percent,
  metrics.conversions AS conversions,
  metrics.all_conversions AS all_conversions,
  metrics.biddable_app_install_conversions AS installs,
  metrics.biddable_app_post_install_conversions AS in_app_conversions,
  metrics.biddable_app_install_conversions / metrics.clicks * 100 AS cti_percent
FROM campaign
WHERE campaign.advertising_channel_type = "MULTI_CHANNEL"
  AND campaign.advertising_channel_sub_type IN ("APP_CAMPAIGN", "APP_CAMPAIGN_FOR_ENGAGEMENT")
  AND segments.date BETWEEN "{start_date}" AND "{end_date}";
