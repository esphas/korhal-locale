--- Apply stack-specific locale overrides when anchor mods are active.

local overrides = require("__korhal-locale__/locale-align/conditional-overrides")

local NAME_SECTIONS = {
  ["entity-name"] = "localised_name",
  ["item-name"] = "localised_name",
  ["technology-name"] = "localised_name",
  ["tile-name"] = "localised_name",
  ["tips-and-tricks-item-name"] = "localised_name",
  ["fuel-category-name"] = "localised_name",
}

local DESC_SECTIONS = {
  ["entity-description"] = "localised_description",
  ["item-description"] = "localised_description",
  ["technology-description"] = "localised_description",
  ["tips-and-tricks-item-description"] = "localised_description",
  ["tile-description"] = "localised_description",
}

local SCAN_TYPES = {
  "item",
  "entity",
  "mining-drill",
  "assembling-machine",
  "inserter",
  "pump",
  "ammo-turret",
  "technology",
  "tile",
  "tips-and-tricks-item",
  "gun",
  "fuel-category",
}

local function set_field(proto, field, text)
  if proto and field and text then
    -- Empty first element = literal text; otherwise Factorio treats it as a locale key.
    proto[field] = { "", text }
  end
end

local function apply_surface_property(name, text)
  local bucket = data.raw["surface-property"]
  if bucket and bucket[name] then
    bucket[name].localised_name = { "", text }
  end
end

local function apply_text(name, section, text)
  if section == "surface-property-name" then
    apply_surface_property(name, text)
    return
  end
  local field = NAME_SECTIONS[section] or DESC_SECTIONS[section]
  if not field then
    return
  end
  for _, proto_type in ipairs(SCAN_TYPES) do
    local bucket = data.raw[proto_type]
    if bucket and bucket[name] then
      set_field(bucket[name], field, text)
    end
  end
end

local function apply_conditional_overrides()
  for _, entry in ipairs(overrides) do
    if mods[entry.anchor] then
      apply_text(entry.key, entry.section, entry.text)
    end
  end
end

return apply_conditional_overrides
