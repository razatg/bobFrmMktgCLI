SELECT customer.id AS customer_id, campaign.id AS campaign_id, campaign.name AS campaign_name,
  ad_group.id AS ad_group_id, ad_group.name AS ad_group_name,
  ad_group_ad.ad.id AS ad_id,
  ad_group_ad_asset_view.resource_name AS asset_view_resource_name,
  ad_group_ad_asset_view.asset AS asset_resource_name, asset.id AS asset_id,
  asset.name AS asset_name, asset.type AS asset_type,
  ad_group_ad_asset_view.field_type AS field_type,
  asset.image_asset.full_size.url AS image_url,
  asset.image_asset.full_size.width_pixels AS image_width,
  asset.image_asset.full_size.height_pixels AS image_height,
  asset.image_asset.mime_type AS mime_type, asset.image_asset.file_size AS file_size_bytes
FROM ad_group_ad_asset_view
WHERE campaign.advertising_channel_type = "MULTI_CHANNEL"
  AND campaign.advertising_channel_sub_type IN ("APP_CAMPAIGN", "APP_CAMPAIGN_FOR_ENGAGEMENT")
  AND campaign.status = "ENABLED"
  AND ad_group.status = "ENABLED"
  AND ad_group_ad_asset_view.enabled = TRUE
  AND ad_group_ad.status != "REMOVED"
  AND asset.type = "IMAGE";
