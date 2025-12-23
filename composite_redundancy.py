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
OUTPUT_NAME = 'composite_overlap'  # Changed output name
LEGEND_FILENAME = 'composite_legend.png'

# SIGNAL THRESHOLDS
UNDEFINED_PATH_LOSS = 9999.0 
VALID_THRESHOLD_DB = 150.0     # Signal must be this good (lower is better) to count as a "vote"
MIN_OVERLAP_COUNT = 2          # Pixel is kept only if this many maps have valid signal

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
    entry_height = 30       
    box_width = 40          
    box_height = 25         
    padding = 5             
    left_margin = 5         
    
    try:
        font = ImageFont.truetype("arialbd.ttf", 16) 
    except IOError:
        try:
            font = ImageFont.truetype("arial.ttf", 16)
        except IOError:
            font = ImageFont.load_default()

    dummy_draw = ImageDraw.Draw(Image.new('RGBA', (1, 1)))
    max_text_width = 0
    for db, _, _, _ in color_scale.entries:
        label = f"{db:.0f} dB"
        bbox = dummy_draw.textbbox((0, 0), label, font=font)
        if (bbox[2] - bbox[0]) > max_text_width: max_text_width = bbox[2] - bbox[0]

    total_width = int(left_margin + max_text_width + padding + box_width)
    total_height = (len(color_scale.entries) * entry_height) + (padding * 2)

    img = Image.new('RGBA', (total_width, total_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    current_y = padding
    for db, r, g, b in color_scale.entries:
        label = f"{db:.0f} dB"
        text_bbox = draw.textbbox((0, 0), label, font=font)
        text_w = text_bbox[2] - text_bbox[0]
        text_x = total_width - box_width - padding - text_w
        
        for ox in [-1, 1]:
            for oy in [-1, 1]:
                draw.text((text_x + ox, current_y + oy), label, font=font, fill=(0,0,0,255))
        
        draw.text((text_x, current_y), label, fill=(255, 255, 255, 255), font=font)
        draw.rectangle(
            [total_width - box_width, current_y, total_width, current_y + box_height],
            fill=(r, g, b, 255),
            outline=(0, 0, 0, 255)
        )
        current_y += entry_height

    img.save(LEGEND_FILENAME)
    print(f"Saved {LEGEND_FILENAME}")

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
    
    # BUFFERS
    # 1. Best Signal found so far
    master_loss = np.full((master_h, master_w), UNDEFINED_PATH_LOSS, dtype=np.float32)
    # 2. Visual representation of that best signal
    master_rgba = np.zeros((master_h, master_w, 4), dtype=np.uint8)
    # 3. OVERLAP COUNTER: How many maps have valid signal at this pixel?
    coverage_count = np.zeros((master_h, master_w), dtype=np.uint8)

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
                
                # Convert Colors to dB
                for (r,g,b), db in color_scale.color_map.items():
                    mask = (src_chunk[:,:,0]==r) & (src_chunk[:,:,1]==g) & (src_chunk[:,:,2]==b)
                    temp_loss[mask] = db

                # --- NEW OVERLAP LOGIC ---
                
                # 1. Identify Valid Signal pixels (Must be <= 150 dB)
                valid_signal_mask = temp_loss <= VALID_THRESHOLD_DB
                
                # 2. Update Count Buffer
                # We simply add +1 to the coverage count for every valid pixel in this map
                coverage_count[y_start:y_end, x_start:x_end][valid_signal_mask] += 1

                # 3. Update Visuals (Standard "Best Signal" Logic)
                # We still track the "best" signal in the background. 
                # We will filter out the "lonely" pixels later.
                master_slice = master_loss[y_start:y_end, x_start:x_end]
                
                # Update if new signal is STRONGER (lower) AND VALID
                better_signal_mask = (temp_loss < master_slice) & valid_signal_mask

                master_loss[y_start:y_end, x_start:x_end] = np.where(better_signal_mask, temp_loss, master_slice)
                
                target_region = master_rgba[y_start:y_end, x_start:x_end]
                src_chunk_rgba = np.zeros((curr_h, curr_w, 4), dtype=np.uint8)
                src_chunk_rgba[..., :3] = src_chunk
                src_chunk_rgba[..., 3] = 255
                
                target_region[better_signal_mask] = src_chunk_rgba[better_signal_mask]
                master_rgba[y_start:y_end, x_start:x_end] = target_region

        except Exception as e:
            print(f"Error: {e}")

    # --- FINAL FILTERING ---
    print(f"Applying overlap filter (Min {MIN_OVERLAP_COUNT} maps with signal <= {VALID_THRESHOLD_DB}dB)...")
    
    # Identify pixels that do NOT meet the overlap requirement
    insufficient_overlap_mask = coverage_count < MIN_OVERLAP_COUNT
    
    # Wipe them out (Set to transparent)
    master_rgba[insufficient_overlap_mask] = (0, 0, 0, 0)

    print("Saving composite map...")
    Image.fromarray(master_rgba, 'RGBA').save(f"{OUTPUT_NAME}.png")

    create_legend_image(color_scale)

    print("Writing KML...")
    kml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<kml xmlns="http://www.opengis.net/kml/2.2">',
        '<Folder>',
        '  <name>SPLAT! Overlap Composite</name>',
        '  <GroundOverlay>',
        '    <name>Overlap Map (2+ Sources)</name>',
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