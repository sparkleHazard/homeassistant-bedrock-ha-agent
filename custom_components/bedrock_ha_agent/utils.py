"Utility functions for the Bedrock Home Assistant Agent integration."
import webcolors

def closest_color(rgb_tuple: tuple[int, int, int]) -> str:
    """Find the closest CSS3 color name for a given RGB tuple."""
    min_colors = {}
    for name in webcolors.names('css3'):
        # Get the hex value for this color name
        hex_value = webcolors.name_to_hex(name, 'css3')
        # Convert hex to RGB
        r_c = int(hex_value[1:3], 16)
        g_c = int(hex_value[3:5], 16)
        b_c = int(hex_value[5:7], 16)
        # Calculate distance
        rd = (r_c - rgb_tuple[0]) ** 2
        gd = (g_c - rgb_tuple[1]) ** 2
        bd = (b_c - rgb_tuple[2]) ** 2
        min_colors[(rd + gd + bd)] = name
    return str(min_colors[min(min_colors.keys())])
