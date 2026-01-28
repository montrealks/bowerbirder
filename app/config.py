"""
Bowerbirder Configuration

Style presets, output dimensions, and limits.
"""

# Style presets with prompts for Nano Banana Pro
STYLE_PRESETS = {
    "fridge": {
        "name": "On the Fridge",
        "prompt": "Tightly clustered photos pinned with colorful fruit-shaped magnets on a teal refrigerator door, photos overlapping each other significantly, filling most of the frame with minimal background visible, cozy family photo collage"
    },
    "scrapbook": {
        "name": "Old Scrapbook",
        "prompt": "Arrange these photos on a vintage scrapbook page with aged cream paper texture, simple washi tape to hold photos in place, minimal subtle decorations only, photos are the focus not the background, no flowers no stickers no nametags no keys, clean understated nostalgic feel"
    },
    "clean": {
        "name": "Clean",
        "prompt": "Arrange these photos in a clean, modern gallery layout on a pure white background with subtle drop shadows, balanced spacing"
    }
}

# Available aspect ratios (matches Ducker)
ASPECT_RATIOS = ["16:9", "1:1", "9:16"]

# Output dimensions (2K longest edge)
OUTPUT_DIMENSIONS = {
    "16:9": (2048, 1152),
    "1:1": (2048, 2048),
    "9:16": (1152, 2048),
}

# Image optimization settings
OPTIMIZE_MAX_SIZE = 768  # Longest edge in pixels
OPTIMIZE_QUALITY = 85    # JPEG quality (1-100)

# Limits
MIN_IMAGES = 2
MAX_IMAGES = 6
MAX_IMAGE_SIZE_MB = 20
MAX_TOTAL_SIZE_MB = 100

# Result expiry
IMAGE_EXPIRY_MINUTES = 30
