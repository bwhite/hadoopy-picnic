import Image

orig_img = Image.open('bigimg.jpg')

for z in range(0, 4):
    height = width = 256 * (2**z)
    img = orig_img.resize((height, width))
    ytiles = height / 256
    xtiles = width / 256
    for y in range(ytiles):
        for x in range(xtiles):
            tile = img.crop((x * 256, y * 256, (x + 1) * 256, (y + 1) * 256))
            tile.save('%d_%d_%d.jpg' % (z, x, (ytiles - y) - 1))
