# App icon

- `ro.svg`: the source (1024 canvas, macOS grid). The cream face of ro (a pill head and two eyes) on an ink ground. The proportions match the pet itself.
- `ro.icns`: built from `ro.svg`. `scripts/build-app.sh` copies it to `Contents/Resources/ro.icns`.

After editing the SVG, rebuild the icns:

```bash
cd assets/icon
qlmanage -t -s 1024 -o /tmp ro.svg            # /tmp/ro.svg.png
mkdir /tmp/ro.iconset
for s in 16 32 128 256 512; do
  sips -z $s $s /tmp/ro.svg.png --out /tmp/ro.iconset/icon_${s}x${s}.png
  sips -z $((s*2)) $((s*2)) /tmp/ro.svg.png --out /tmp/ro.iconset/icon_${s}x${s}@2x.png
done
iconutil -c icns /tmp/ro.iconset -o ro.icns
```
