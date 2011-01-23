import hadoopy
import Image
import numpy as np
import re
import cStringIO as StringIO

_subtile_length = 16
_tile_length = 256
_levels = 4
_initial_image_size = _subtile_length * 2 ** (_levels - 1)
_subtiles_per_tile_length = _tile_length / _subtile_length
_subtiles_per_tile = _subtiles_per_tile_length * _subtiles_per_tile_length


class Mapper(object):

    def __init__(self):
        _target_image = Image.open('target.jpg')
        self.target_tiles = {}
        xtiles = _target_image.size[0] / _tile_length
        ytiles = _target_image.size[1] / _tile_length
        xsubtiles = xtiles * _subtiles_per_tile_length
        ysubtiles = ytiles * _subtiles_per_tile_length
        for y in xrange(ysubtiles):
            for x in xrange(xsubtiles):
                tile_id = '%.6d_%.6d' % (x / _subtiles_per_tile_length,
                                         y / _subtiles_per_tile_length)
                subtile_id = '%.6d_%.6d' % (x % _subtiles_per_tile_length,
                                            y % _subtiles_per_tile_length)
                key = '\t'.join((tile_id, subtile_id))
                yp = ysubtiles - y - 1
                tile = _target_image.crop((x * _subtile_length,
                                           yp * _subtile_length,
                                           (x + 1) * _subtile_length,
                                           (yp + 1) * _subtile_length))
                self.target_tiles[key] = np.asarray(tile)

    @staticmethod
    def _image_from_str(s):
        """Load from string, crop to a square, resize to _initial_image_size

        Args:
            s: String of bytes representing a JPEG image

        Returns:
            RGB Image with height/width as _initial_image_size

        Raises:
            ValueError: Image is height/width too small (< _initial_image_size)
                or mode isn't RGB
            IOError: Image is unreadable
        """
        try:
            img = Image.open(StringIO.StringIO(s))
        except IOError, e:
            hadoopy.counter('Stats', 'IMG_BAD')
            raise e
        min_side = min(img.size)
        if min_side < _initial_image_size:
            hadoopy.counter('Stats', 'IMG_TOO_SMALL')
            raise ValueError
        if img.mode != 'RGB':
            hadoopy.counter('Stats', 'IMG_WRONG_MODE')
            raise ValueError
        img = img.crop((0, 0, min_side, min_side))  # TODO: Crop the center instead
        return img.resize((_initial_image_size, _initial_image_size))

    @staticmethod
    def _image_similarity(img0, img1):
        """
        Args:
            img0: Numpy array
            img1: Numpy array

        Returns:
            Float valued distance where smaller means they are more similar
        """
        return np.sum(img0 - img1)

    def map(self, key, value):
        """
        Args:
            key: Unused
            value: JPEG Image Data

        Yields:
            Tuple of (key, value) where
            key: tile_id\tsubtile_id (easily parsable by the
                KeyFieldBasedPartitioner)
            value: (score, images) where images are power of 2 JPEG images
                in descending order by size
        """
        try:
            images = [self._image_from_str(value)]
        except (ValueError, IOError):
            return
        # Keep resizing until we get one for each layer, save them for later use
        prev_size = _initial_image_size
        for layer in range(1, _levels):
            prev_size /= 2
            images.append(images[-1].resize((prev_size, prev_size)))
        scoring_tile = np.asarray(images[-1])
        # Compute score for each tile position, emit for each (TODO Optimize by
        # only emitting when we know the value is larger than we have seen)
        # TODO Should probably convert images to jpeg strings
        for key, target_tile in self.target_tiles.items():
            score = self._image_similarity(target_tile, scoring_tile)
            yield key, (score, images)


def combiner(key, values):
    """
    Args:
        key: (tile_id, subtile_id)
        values: Iterator of (score, images) where images are power of 2 JPEG
            images in descending order by size

    Yields:
        Tuple of (key, value) where
        key: (tile_id, subtile_id)
        value: (score, images) where images are power of 2 JPEG images
            in descending order by size
    """
    yield key, min(values, key=lambda x: x[0])


class Reducer(object):

    def __init__(self):
        self._sub_tiles = {}
        _parse_key_re = re.compile('([0-9]+)_([0-9]+)\t([0-9]+)_([0-9]+)')
        self._parse_key = lambda x: map(int, _parse_key_re.search(x).groups())
        _target_image = Image.open('target.jpg')
        self.num_xtiles = _target_image.size[0] / _tile_length
        self.num_ytiles = _target_image.size[1] / _tile_length

    def _find_output(self, key, scale, subtiles_per_tile_len, subtile_len):
        xtile, ytile, xsubtile, ysubtile = self._parse_key(key)
        xouttile = xtile * scale + xsubtile / subtiles_per_tile_len
        youttile = ytile * scale + ysubtile / subtiles_per_tile_len
        xoffset = (xsubtile % subtiles_per_tile_len) * subtile_len
        yoffset = (subtiles_per_tile_len - (ysubtile % subtiles_per_tile_len) - 1) * subtile_len
        return xouttile, youttile, xoffset, yoffset

    def _image_to_str(self, img):
        out = StringIO.StringIO()
        img.save(out, 'JPEG')
        out.seek(0)
        return out.read()

    def reduce(self, key, values):
        """
        Args:
        key: (tile_id, subtile_id)
        values: Iterator of (score, images) where images are power of 2 JPEG
            images in descending order by size

        Yields:
            Tuple of (key, value) where
            key: Tile name
            value: JPEG Image Data
        """
        self._sub_tiles[key] = min(values, key=lambda x: x[0])[1][::-1]
        # If we don't have all of the necessary subtiles
        if len(self._sub_tiles) != _subtiles_per_tile:
            return
        for level in range(_levels):
            # Each image is smaller than the tile
            scale = 2 ** level
            subtiles_per_tile_len = _subtiles_per_tile_length / scale
            subtile_len = _subtile_length * scale
            cur_subtiles = [(self._find_output(key, scale, subtiles_per_tile_len, subtile_len), images[level])
                         for key, images in self._sub_tiles.items()]
            cur_subtiles.sort(key=lambda x: x[0])
            subtiles_per_tile = subtiles_per_tile_len ** 2
            cur_tile = Image.new('RGB', (_tile_length, _tile_length))
            for subtile_ind, ((xouttile, youttile, xoffset, yoffset), image) in enumerate(cur_subtiles):
                print((xouttile, youttile, xoffset, yoffset))
                cur_tile.paste(image, (xoffset, yoffset))
                if not (subtile_ind + 1) % subtiles_per_tile:
                    tile_name = '%d_%d_%d.jpg' % (level, xouttile, youttile)
                    yield tile_name, self._image_to_str(cur_tile)
                    cur_tile = Image.new('RGB', (_tile_length, _tile_length))
        self._sub_tiles = {}


if __name__ == '__main__':
    hadoopy.run(Mapper, Reducer, combiner)
