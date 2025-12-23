# coverage_utils
Jef's Coverage Utilities

These utilities, written in Python 3, are intended to work with coverage model maps created using SPLAT!.
Each of these utilities expects to be run from a folder containing the Python script and the following SPLAT!-created files for each site:
- siteA.kml # The KML file that defines the lat, lon coordinates of the overlay that could be loaded into Google Earth
- siteA.png # the graphical overlay
- siteA.lcf # the definitions of color scale (Path Loss in this case)

Each of these utilities was based on the original composite.py, and then variations were implemented.
Each defines a default threshold for highest path loss.  Default is 150 dB.  Points beyond this threshold will not be considered for output.
Each uses whatever KML files are found in the folder to determine what will be used in the generated map. You might want to create a BACKUP folder to keep files that you don't want to used for any particular run.  Note that running these scripts creates KML output files that will be included by subsequent runs as if they were supplied by the user, so take care to cleanup your KML files as necessary before each run.

Currently the only script requiring specific action to edit a variable is the composite_mutual_with_target.py which needs a partial name to identify the intended target.kml.

## Descriptions

### composite.py
Creates a composite map using all (.kml, .png, .lcf) site files found in the working folder. 

### composite_best_server.py
Creates a composite map identifying the strongest site at every point.

### composite_redundancy.py
Creates a composite map showing the strongest signal (lowest path loss) at any point that has at least two sources above the threshold.

### composite_mutual_with_target.py

Creates a "Mutual with Target" map using a "Weakest Link" logic to ensure a reliable two-way connection.
Here is the step-by-step breakdown of the logic currently implemented:

1. Identify the Players:
- The Target: The specific site you want to test (e.g., w6ek).
- The Network: All other maps in the folder.
2. Find the Best Partner (The Network Candidate): For every specific pixel, the script looks at all the "Network" maps and finds the strongest signal (Lowest dB path loss) available. This represents the best possible path back to the network from that spot.
3. Calculate the "Limiting Link": The script compares the Target's Signal vs. the Best Network Signal at that point. It selects the WEAKER (Higher dB path loss) of the two.
    Logic: A chain is only as strong as its weakest link. If the Target is strong (110 dB) but the best Network node is weak (145 dB), the effective mutual link quality is 145 dB.
4. The Threshold (The Cutoff): If that "Limiting Link" value is 150 dB or better (lower), the pixel is painted. If the limiting link is worse (e.g., 155 dB), the pixel is left transparent.
5. The Visual: The color displayed represents that Limiting Link value. This gives you a conservative, realistic view of where a repeater could talk to both the Target and the rest of the Network reliably.
