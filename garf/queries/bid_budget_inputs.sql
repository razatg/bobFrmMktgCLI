SELECT
  customer.id AS customer_id,
  campaign.id AS campaign_id,
  campaign.name AS campaign_name,
  campaign.status AS campaign_status,
  campaign.primary_status AS primary_status,
  campaign.primary_status_reasons AS primary_status_reasons,
  campaign.bidding_strategy_type AS bidding_strategy_type,
  campaign.app_campaign_setting.bidding_strategy_goal_type AS app_bidding_goal_type,
  campaign_budget.id AS campaign_budget_id,
  campaign_budget.name AS campaign_budget_name,
  campaign_budget.amount_micros / 1000000 AS daily_budget,
  campaign_budget.status AS campaign_budget_status,
  metrics.average_target_cpa_micros / 1000000 AS target_cpa,
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
