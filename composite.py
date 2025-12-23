import os
import glob
import re
import xml.etree.ElementTree as ET
import numpy as np
from PIL import Image, ImageDraw, ImageFont

# --- FIX FOR LARGE MAPS ---
Image.MAX_IMAGE_PIXELS = None

# Configuration
INPUT_FOLDER = '.'  
LCF_FILENAME = 'color_scale.lcf'
OUTPUT_NAME = 'composite_coverage'
LEGEND_FILENAME = 'composite_legend.png'
UNDEFINED_PATH_LOSS = 9999.0 

class ColorScale:
    def __init__(self, lcf_path):
        self.color_map = {}
        self.entries = []
        self.load_lcf(lcf_path)

    def load_lcf(self, path):
        if not os.path.exists(path):
            raise FileNotFoundError(f"LCF file not found: {path}")
        
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'): continue
                parts = re.split(r'[;:,]\s*', line)
                if len(parts) >= 4:
                    try:
                        db = float(parts[0])
                        r, g, b = int(parts[1]), int(parts[2]), int(parts[3])
                        self.color_map[(r, g, b)] = db
                        self.entries.append((db, r, g, b))
                    except ValueError:
                        continue
        self.entries.sort(key=lambda x: x[0])
        print(f"Loaded {len(self.color_map)} colors for legend.")

class MapLayer:
    def __init__(self, kml_path):
        self.kml_path = kml_path
        self.base_name = os.path.splitext(kml_path)[0]
        self.png_path = self.base_name + '.png'
        if not os.path.exists(self.png_path):
            if os.path.exists(self.base_name + '.ppm'):
                self.png_path = self.base_name + '.ppm'
            else:
                raise FileNotFoundError(f"Image not found for {kml_path}")
        self.north = 0.0
        self.south = 0.0
        self.east = 0.0
        self.west = 0.0
        self.parse_kml()

    def parse_kml(self):
        try:
            tree = ET.parse(self.kml_path)
            root = tree.getroot()
            for elem in tree.iter():
                if '}' in elem.tag:
                    elem.tag = elem.tag.split('}', 1)[1]
            bbox = root.find('.//LatLonBox')
            if bbox is None: raise ValueError("No <LatLonBox>")
            self.north = float(bbox.findtext('north'))
            self.south = float(bbox.findtext('south'))
            self.east = float(bbox.findtext('east'))
            self.west = float(bbox.findtext('west'))
        except Exception as e:
            raise ValueError(f"XML Error {self.kml_path}: {e}")

def create_legend_image(color_scale):
    print("Generating legend image...")
    
    # Layout Settings
    entry_height = 30       
    box_width = 40          
    box_height = 25         
    padding = 5             # Space between Text and Color Box
    left_margin = 5         # Space between Screen Edge and Text
    
    # 1. Setup Font
    try:
        font = ImageFont.truetype("arialbd.ttf", 16) 
    except IOError:
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except IOError:
            font = ImageFont.load_default()

    # 2. Measure Text to determine strict Width
    # We use a dummy image to calculate text size
    dummy_draw = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    max_text_width = 0
    
    for db, _, _, _ in color_scale.entries:
        label = f"{db:.0f} dB"
        # getbbox returns (left, top, right, bottom)
        bbox = dummy_draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        if text_w > max_text_width:
            max_text_width = text_w

    # Calculate Total Width dynamically
    # [Margin] [Text] [Padding] [ColorBox]
    total_width = int(left_margin + max_text_width + padding + box_width)
    
    num_entries = len(color_scale.entries)
    total_height = (num_entries * entry_height) + (padding * 2)

    # 3. Create Image
    img = Image.new('RGBA', (total_width, total_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    current_y = padding
    for db, r, g, b in color_scale.entries:
        label = f"{db:.0f} dB"
        
        # Calculate X position to align text to the right of the text-area
        # (This keeps the numbers aligned close to the boxes)
        text_bbox = draw.textbbox((0, 0), label, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        
        # Determine exact X for text
        # It ends at: total_width - box_width - padding
        text_x = total_width - box_width - padding - text_w
        
        # Draw Black Outline
        for ox in [-1, 1]:
            for oy in [-1, 1]:
                draw.text((text_x + ox, current_y + oy), label, font=font, fill=(0,0,0,255))
        
        # Draw White Text
        draw.text((text_x, current_y), label, fill=(255, 255, 255, 255), font=font)
        
        # Draw Color Box (Far Right)
        draw.rectangle(
            [total_width - box_width, current_y, total_width, current_y + box_height],
            fill=(r, g, b, 255),
            outline=(0, 0, 0, 255)
        )
        current_y += entry_height

    img.save(LEGEND_FILENAME)
    print(f"Saved {LEGEND_FILENAME} (Width: {total_width}px)")

def create_composite_map():
    lcf_path = os.path.join(INPUT_FOLDER, LCF_FILENAME)
    try:
        color_scale = ColorScale(lcf_path)
    except Exception as e:
        print(f"Error: {e}")
        return

    kml_files = glob.glob(os.path.join(INPUT_FOLDER, '*.kml'))
    layers = []
    
    print("Parsing KML files...")
    for kml in kml_files:
        if OUTPUT_NAME in kml: continue 
        try:
            layer = MapLayer(kml)
            layers.append(layer)
            print(f" - Found: {os.path.basename(kml)}")
        except Exception: pass

    if not layers: return

    global_north = max(l.north for l in layers)
    global_south = min(l.south for l in layers)
    global_east = max(l.east for l in layers)
    global_west = min(l.west for l in layers)

    ref_layer = layers[0]
    with Image.open(ref_layer.png_path) as img:
        w, h = img.size
        ppd_lat = h / (ref_layer.north - ref_layer.south)
        ppd_lon = w / (ref_layer.east - ref_layer.west)

    master_h = int((global_north - global_south) * ppd_lat)
    master_w = int((global_east - global_west) * ppd_lon)

    print(f"Canvas: {master_w}x{master_h} pixels")
    
    master_loss = np.full((master_h, master_w), UNDEFINED_PATH_LOSS, dtype=np.float32)
    master_rgba = np.zeros((master_h, master_w, 4), dtype=np.uint8)

    for layer in layers:
        print(f"Merging {os.path.basename(layer.png_path)}...")
        try:
            with Image.open(layer.png_path) as img:
                img = img.convert('RGB')
                src_arr = np.array(img)
                src_h, src_w, _ = src_arr.shape

                y_start = int((global_north - layer.north) * ppd_lat)
                x_start = int((layer.west - global_west) * ppd_lon)
                y_end = min(y_start + src_h, master_h)
                x_end = min(x_start + src_w, master_w)
                curr_h, curr_w = y_end - y_start, x_end - x_start
                if curr_h <= 0 or curr_w <= 0: continue

                src_chunk = src_arr[:curr_h, :curr_w]
                temp_loss = np.full((curr_h, curr_w), UNDEFINED_PATH_LOSS, dtype=np.float32)
                
                for (r,g,b), db in color_scale.color_map.items():
                    mask = (src_chunk[:,:,0]==r) & (src_chunk[:,:,1]==g) & (src_chunk[:,:,2]==b)
                    temp_loss[mask] = db

                master_slice = master_loss[y_start:y_end, x_start:x_end]
                update_mask = (temp_loss < master_slice) & (temp_loss != UNDEFINED_PATH_LOSS)

                master_loss[y_start:y_end, x_start:x_end] = np.where(update_mask, temp_loss, master_slice)
                
                target_region = master_rgba[y_start:y_end, x_start:x_end]
                src_chunk_rgba = np.zeros((curr_h, curr_w, 4), dtype=np.uint8)
                src_chunk_rgba[..., :3] = src_chunk
                src_chunk_rgba[..., 3] = 255
                
                target_region[update_mask] = src_chunk_rgba[update_mask]
                master_rgba[y_start:y_end, x_start:x_end] = target_region

        except Exception as e:
            print(f"Error: {e}")

    print("Saving composite map...")
    Image.fromarray(master_rgba, 'RGBA').save(f"{OUTPUT_NAME}.png")

    create_legend_image(color_scale)

    print("Writing KML...")
    kml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Folder>',
        '  <name>SPLAT! Composite</name>',
        '  <GroundOverlay>',
        '    <name>Coverage Map</name>',
        f'    <Icon><href>{OUTPUT_NAME}.png</href></Icon>',
        '    <LatLonBox>',
        f'      <north>{global_north}</north>',
        f'      <south>{global_south}</south>',
        f'      <east>{global_east}</east>',
        f'      <west>{global_west}</west>',
        '    </LatLonBox>',
        '  </GroundOverlay>',
        '  <ScreenOverlay>',
        '    <name>Legend</name>',
        f'    <Icon><href>{LEGEND_FILENAME}</href></Icon>',
        '    <overlayXY x="0" y="1" xunits="fraction" yunits="fraction"/>',
        '    <screenXY x="0" y="1" xunits="fraction" yunits="fraction"/>',
        '    <rotationXY x="0" y="0" xunits="fraction" yunits="fraction"/>',
        '    <size x="0" y="0" xunits="pixels" yunits="pixels"/>',
        '  </ScreenOverlay>',
        '</Folder>',
        '</kml>'
    ]

    with open(f"{OUTPUT_NAME}.kml", "w") as f:
        f.write('\n'.join(kml_lines))

    print(f"Done! Created {OUTPUT_NAME}.png, {LEGEND_FILENAME}, and {OUTPUT_NAME}.kml")

if __name__ == "__main__":
    create_composite_map()