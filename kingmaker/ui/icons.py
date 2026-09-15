"""Icons and colours for settlement structures (cosmetic only)."""

STRUCTURE_ICONS = {
    "academy": "🎓", "military_academy": "⚔️", "embassy": "🤝", "arena": "🏟️",
    "gladiatorial_arena": "🗡️", "specialized_artisan": "⚙️", "trade_shop": "🏪",
    "bank": "🏦", "tavern_dive": "🍺", "library": "📚", "sacred_grove": "🌳",
    "occult_shop": "🔮", "luxury_store": "💍", "magic_shop": "✨",
    "construction_yard": "🛠️", "tenement": "🏚️", "houses": "🏠", "barracks": "🛡️",
    "castle": "🏰", "cathedral": "⛪", "cemetery": "🪦", "tannery": "🧵",
    "lumberyard": "🪵", "dump": "🗑️", "brewery": "🥃", "general_store": "🛒",
    "herbalist": "🌿", "foundry": "🔥", "keep": "🏯", "smithy": "⚒️",
    "thieves_guild": "🗝️", "granary": "🌾", "garrison": "🎖️",
    "alchemy_laboratory": "⚗️", "magical_streetlamps": "🏮", "inn": "🛏️",
    "rubble": "🧱", "secure_warehouse": "🔒", "mansion": "🏡", "marketplace": "🏬",
    "illicit_market": "🕯️", "pier": "⚓", "monument": "🗿", "mill": "🌀",
    "town_hall": "🏛️", "wooden_wall": "🪵", "stone_wall": "🧱", "museum": "🖼️",
    "orphanage": "🧸", "hospital": "🏥", "palace": "👑", "park": "🌲", "bridge": "🌉",
    "jail": "⛓️", "stockyard": "🐄", "festival_hall": "🍷", "shrine": "🕯️",
    "guildhall": "🏛️", "menagerie": "🦁", "sewer_system": "🚰", "stable": "🐎",
    "paved_streets": "🧱", "stonemason": "🪨", "tavern_popular": "🍻",
    "tavern_luxury": "🍸", "tavern_world_class": "🌍", "theater": "🎭",
    "opera_house": "🎼", "temple": "🛐", "printing_house": "🖨️",
    "arcanists_tower": "🗼", "watchtower": "🔭", "noble_villa": "🏰",
    "university": "🎓", "mint": "🪙", "waterfront": "🚢",
}

TRAIT_COLORS = {
    "residential": "#6f9a4e",
    "infrastructure": "#5b8fb0",
    "yard": "#8a9a5b",
    "building": "#d7b263",
    "famous": "#e0c060",
    "infamous": "#b84a3a",
}


def icon(structure_id: str) -> str:
    return STRUCTURE_ICONS.get(structure_id, "🏗️")


def color(stretches: list[str]) -> str:
    for t in ("famous", "infamous", "residential", "infrastructure", "yard"):
        if t in stretches:
            return TRAIT_COLORS[t]
    return "#d7b263"
