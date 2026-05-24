SELECT
  campaign.id AS campaign_id,
  campaign.name AS campaign_name,
  segments.date AS date,
  metrics.unique_users AS unique_users,
  metrics.average_impression_frequency_per_user AS frequency
FROM campaign
WHERE campaign.advertising_channel_type = "MULTI_CHANNEL"
  AND campaign.advertising_channel_sub_type IN ("APP_CAMPAIGN", "APP_CAMPAIGN_FOR_ENGAGEMENT")
  AND segments.date BETWEEN "{start_date}" AND "{end_date}";
