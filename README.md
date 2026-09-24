# MOHAA Asset Converter

Local browser and converter for Medal of Honor: Allied Assault assets. Point it at a game folder, scan pk3s, preview SKD models with real shader resolve, then convert maps, characters, weapons, vehicles, and props.

## Run

Python 3 with Pillow:

```
pip install pillow
python server.py
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765). On Windows you can also use `start.bat`.

In the UI, set **Assets** to a MOHAA install that contains `main/` (pk3s), then **Scan**. Set **Unreal project** to an Unreal Engine 5.8 `.uproject` (or its folder). Those paths stay local; do not commit `paths.json`.

## Unreal 5.8 Convert

- **Convert to FBX** writes FBX/OBJ into a local `export/` cache.
- **Export to Unreal Engine** imports the selected asset into the chosen 5.8 project.
- **Batch Convert** runs the same pipeline for a category.

Blender is used for FBX when it is installed. Game pk3s, TGA dumps, FBX caches, and Unreal Content are not part of this repository.
