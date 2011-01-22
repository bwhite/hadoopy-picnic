import hadoopy
import Image
import numpy as np
import cStringIO as StringIO

_subtile_length = 16
_tile_length = 256
_levels = 4
_initial_image_size = _subtile_length * 2 ** (_levels - 1)
_subtiles_per_tile = _tile_length / _subtile_length


class Mapper(object):

    def __init__(self):
        _target_image = Image.open('target.jpg')
        self.target_tiles = {}
        xtiles = _target_image.size[0] / _tile_length
        ytiles = _target_image.size[1] / _tile_length
        xsubtiles = xtiles * _subtiles_per_tile
        ysubtiles = ytiles * _subtiles_per_tile
        for y in xrange(ysubtiles):
            for x in xrange(xsubtiles):
                tile_id = '%.6d_%.6d' % (x / _subtiles_per_tile,
                                       ytiles - y / _subtiles_per_tile - 1)
                subtile_id = '%.6d_%.6d' % (x, ysubtiles - y - 1)
                key = '\t'.join((tile_id, subtile_id))
                tile = _target_image.crop((x * _subtile_length,
                                           y * _subtile_length,
                                           (x + 1) * _subtile_length,
                                           (y + 1) * _subtile_length))
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
        self._sub_tiles = []

    def _is_last_subtile(self, key):
        pass

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
        self._sub_tiles.append(min(values, key=lambda x: x[0]))
        if self._is_last_subtile(key):
            pass  # TODO Build tile and emit

if __name__ == '__main__':
    hadoopy.run(Mapper, Reducer, combiner)
